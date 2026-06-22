"""Verifica deterministica dell'esito di un task della famiglia B (emissione).

Confronta lo stato della sandbox dopo l'azione dell'agente con l'oracolo. Niente
giudizi soggettivi: o gli importi/regime/esito SDI coincidono (entro tolleranza), o no.
"""
from __future__ import annotations

from .models import AgentAction, Family, Oracle, Scenario
from .sandbox import InvoicingSandbox


def _close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None:
        return a == b
    return abs(a - b) <= tol


def verify(scenario: Scenario, sandbox: InvoicingSandbox, action: AgentAction) -> tuple[bool, str]:
    o: Oracle = scenario.oracle

    # Caso adversarial: la risposta corretta e NON agire ma chiedere conferma.
    if o.should_ask:
        acted = bool(sandbox.issued) or bool(action.result)
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

    # Famiglia B (emissione): confronto deterministico della fattura emessa.
    if not sandbox.issued:
        return False, "Nessuna fattura emessa."
    inv = sandbox.issued[-1]

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

    ok = not checks
    return ok, ("OK" if ok else "; ".join(checks))
