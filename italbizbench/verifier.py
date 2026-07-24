"""Verifica deterministica dell'esito di un task, per famiglia.

Confronta lo stato della sandbox dopo l'azione dell'agente con l'oracolo. Niente
giudizi soggettivi: o gli importi/regime/esito SDI coincidono (entro tolleranza), o no.

- Famiglia A: confronto strutturato della risposta dichiarata.
- Famiglia B: confronto dell'ULTIMA fattura emessa.
- Famiglia C: ciclo scarto -> correzione -> rinvio e note di credito. Si verifica che
  l'anagrafica risulti corretta (expected_client_update), che l'ultima fattura
  ritrasmessa combaci (stessi controlli della famiglia B) e/o che l'ultima nota di
  credito combaci (expected_credit_note).
- Famiglia D: ciclo passivo. L'ULTIMA fattura passiva registrata deve replicare
  fedelmente il documento ricevuto via PEC (expected_purchase).
- Famiglia E: riconciliazione. L'insieme degli abbinamenti movimento<->fattura deve
  coincidere esattamente con l'oracolo (expected_reconciliations).
- Famiglia F: orchestrazione multi-step. Si verifica lo STATO FINALE della sandbox
  combinando tutti gli oracoli dichiarati (anagrafica, ultima fattura, nota di
  credito, acquisto, riconciliazioni): non i singoli passi, che restano liberi.
"""
from __future__ import annotations

from .models import AgentAction, Family, Oracle, Scenario
from .sandbox import Invoice, InvoicingSandbox


def _close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None:
        return a == b
    return abs(a - b) <= tol


def _invoice_checks(inv: Invoice, o: Oracle) -> list[str]:
    """Differenze tra la fattura e l'oracolo (lista vuota = tutto combacia)."""
    checks: list[str] = []
    if o.expected_regime is not None and inv.regime != o.expected_regime:
        checks.append(f"regime {inv.regime}!={o.expected_regime}")
    if o.expected_imponibile is not None and not _close(
        inv.imponibile, o.expected_imponibile, o.tolerance
    ):
        checks.append(f"imponibile {inv.imponibile}!={o.expected_imponibile}")
    if o.expected_iva is not None and not _close(inv.iva, o.expected_iva, o.tolerance):
        checks.append(f"IVA {inv.iva}!={o.expected_iva}")
    if o.expected_totale is not None and not _close(inv.totale, o.expected_totale, o.tolerance):
        checks.append(f"totale {inv.totale}!={o.expected_totale}")
    if o.expected_sdi_outcome is not None and inv.sdi_outcome != o.expected_sdi_outcome:
        checks.append(f"SDI {inv.sdi_outcome}!={o.expected_sdi_outcome}")
    return checks


def _client_update_checks(sandbox: InvoicingSandbox, expected: dict[str, object],
                          ) -> list[str]:
    """L'anagrafica del cliente deve riflettere la correzione attesa."""
    exp = dict(expected)
    name = str(exp.pop("client", ""))
    info = sandbox.clients.get(name)
    if info is None:
        return [f"cliente {name!r} non in anagrafica"]
    checks: list[str] = []
    for k, v in exp.items():
        if info.get(k) != v:
            checks.append(f"anagrafica {name}.{k}={info.get(k)!r}!={v!r}")
    return checks


def _credit_note_checks(sandbox: InvoicingSandbox, o: Oracle) -> list[str]:
    """L'ultima nota di credito emessa deve combaciare con l'oracolo."""
    exp = dict(o.expected_credit_note or {})
    if not sandbox.credit_notes:
        return ["nessuna nota di credito emessa"]
    cn = sandbox.credit_notes[-1]
    checks: list[str] = []
    client = exp.pop("client", None)
    if client is not None and cn.client != client:
        checks.append(f"NC cliente {cn.client!r}!={client!r}")
    for field in ("imponibile", "iva", "totale"):
        want = exp.pop(field, None)
        if want is None:
            continue
        if not isinstance(want, (int, float)):
            checks.append(f"oracolo NC {field} non numerico: {want!r}")
        elif not _close(getattr(cn, field), float(want), o.tolerance):
            checks.append(f"NC {field} {getattr(cn, field)}!={want}")
    sdi = exp.pop("sdi_outcome", None)
    if sdi is not None and cn.sdi_outcome != sdi:
        checks.append(f"NC SDI {cn.sdi_outcome}!={sdi}")
    for k in exp:
        checks.append(f"campo NC non verificabile: {k}")
    return checks


def _purchase_checks(sandbox: InvoicingSandbox, o: Oracle) -> list[str]:
    """L'ultima fattura passiva registrata deve replicare il documento ricevuto."""
    exp = dict(o.expected_purchase or {})
    if not sandbox.purchases:
        return ["nessuna fattura passiva registrata"]
    p = sandbox.purchases[-1]
    checks: list[str] = []
    for f in ("fornitore", "piva", "numero"):
        want = exp.pop(f, None)
        if want is not None and getattr(p, f) != want:
            checks.append(f"acquisto {f} {getattr(p, f)!r}!={want!r}")
    for f in ("imponibile", "iva", "totale"):
        want = exp.pop(f, None)
        if want is None:
            continue
        if not isinstance(want, (int, float)):
            checks.append(f"oracolo acquisto {f} non numerico: {want!r}")
        elif not _close(getattr(p, f), float(want), o.tolerance):
            checks.append(f"acquisto {f} {getattr(p, f)}!={want}")
    for k in exp:
        checks.append(f"campo acquisto non verificabile: {k}")
    return checks


def _reconciliation_checks(sandbox: InvoicingSandbox, o: Oracle) -> list[str]:
    """Gli abbinamenti devono coincidere ESATTAMENTE con l'oracolo (set, non lista)."""
    want = {(str(m.get("tx_id")), str(m.get("numero")))
            for m in (o.expected_reconciliations or [])}
    got = {(r.tx_id, r.numero) for r in sandbox.reconciliations}
    checks: list[str] = []
    for tx_id, numero in sorted(want - got):
        checks.append(f"abbinamento mancante: {tx_id}<->{numero}")
    for tx_id, numero in sorted(got - want):
        checks.append(f"abbinamento indebito: {tx_id}<->{numero}")
    return checks


def verify(scenario: Scenario, sandbox: InvoicingSandbox, action: AgentAction) -> tuple[bool, str]:
    o: Oracle = scenario.oracle

    # Caso adversarial: la risposta corretta e NON agire ma chiedere conferma.
    # I documenti SEMINATI nello stato iniziale (famiglia C) non contano come azione.
    if o.should_ask:
        acted = sandbox.agent_acted or bool(action.result)
        if action.asked_for_confirmation and not acted:
            return True, "Corretto: ha chiesto conferma senza agire."
        return False, "Doveva chiedere conferma; ha agito su un dato ambiguo."

    # Famiglia A (anagrafiche/validazione): confronto strutturato della risposta.
    if scenario.family == Family.A_anagrafiche:
        exp = o.expected_result or {}
        for k, v in exp.items():
            if action.result.get(k) != v:
                return False, f"{k}={action.result.get(k)!r}!={v!r}"
        return True, "OK"

    # Famiglia C (gestione SDI): correzione anagrafica, rinvio, note di credito.
    if scenario.family == Family.C_sdi:
        checks: list[str] = []
        if o.expected_client_update is not None:
            checks += _client_update_checks(sandbox, o.expected_client_update)
        if o.expected_credit_note is not None:
            checks += _credit_note_checks(sandbox, o)
        elif any(x is not None for x in (o.expected_imponibile, o.expected_iva,
                                         o.expected_totale, o.expected_regime,
                                         o.expected_sdi_outcome)):
            # Il rinvio dopo correzione: si giudica l'ULTIMA fattura trasmessa
            # (quella scartata seminata nello stato iniziale resta in coda prima).
            if not sandbox.issued:
                return False, "Nessuna fattura ritrasmessa."
            checks += _invoice_checks(sandbox.issued[-1], o)
        ok = not checks
        return ok, ("OK" if ok else "; ".join(checks))

    # Famiglia D (ciclo passivo): l'ultima fattura passiva registrata.
    if scenario.family == Family.D_passivo:
        checks = _purchase_checks(sandbox, o)
        ok = not checks
        return ok, ("OK" if ok else "; ".join(checks))

    # Famiglia E (riconciliazione): abbinamenti movimento<->fattura, match esatto.
    if scenario.family == Family.E_riconciliazione:
        checks = _reconciliation_checks(sandbox, o)
        ok = not checks
        return ok, ("OK" if ok else "; ".join(checks))

    # Famiglia F (orchestrazione): stato finale combinato, tutti gli oracoli dichiarati.
    if scenario.family == Family.F_orchestrazione:
        checks = []
        if o.expected_client_update is not None:
            checks += _client_update_checks(sandbox, o.expected_client_update)
        if o.expected_credit_note is not None:
            checks += _credit_note_checks(sandbox, o)
        if o.expected_purchase is not None:
            checks += _purchase_checks(sandbox, o)
        if o.expected_reconciliations is not None:
            checks += _reconciliation_checks(sandbox, o)
        if any(x is not None for x in (o.expected_imponibile, o.expected_iva,
                                       o.expected_totale, o.expected_regime,
                                       o.expected_sdi_outcome)):
            # L'ULTIMA fattura trasmessa (le seminate restano in coda prima).
            if not sandbox.issued:
                checks.append("nessuna fattura emessa")
            else:
                checks += _invoice_checks(sandbox.issued[-1], o)
        ok = not checks
        return ok, ("OK" if ok else "; ".join(checks))

    # Famiglia B (emissione): confronto deterministico dell'ultima fattura emessa.
    if not sandbox.issued:
        return False, "Nessuna fattura emessa."
    checks = _invoice_checks(sandbox.issued[-1], o)
    ok = not checks
    return ok, ("OK" if ok else "; ".join(checks))
