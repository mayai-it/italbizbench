"""Test della famiglia C: ciclo scarto -> correzione -> rinvio e note di credito."""
from pathlib import Path

from italbizbench.adapters import ReferenceAgent
from italbizbench.adapters.llm import LLMAgent, ScriptedLLMClient, ToolCall
from italbizbench.models import AgentAction, Difficulty, Family, InvoiceLine, Oracle, Scenario
from italbizbench.runner import load_scenarios, run
from italbizbench.sandbox import Invoice, InvoicingSandbox
from italbizbench.scoring import score_task
from italbizbench.verifier import verify

TASKS = Path(__file__).resolve().parent.parent / "tasks"


# --- sandbox: nuovi strumenti ---------------------------------------------------


def test_sandbox_isolation_between_instances():
    # Regressione: update_client su una sandbox NON deve toccare le anagrafiche
    # di default condivise (deepcopy in InvoicingSandbox).
    s1 = InvoicingSandbox()
    s1.update_client("Rossi Costruzioni Srl", codice_destinatario="SPORCO1")
    s2 = InvoicingSandbox()
    assert s2.clients["Rossi Costruzioni Srl"]["codice_destinatario"] == "ABCDEF1"


def test_update_client_mutates_and_counts():
    s = InvoicingSandbox()
    out = s.update_client("Rossi Costruzioni Srl", codice_destinatario="NUOVO77")
    assert out is not None and out["codice_destinatario"] == "NUOVO77"
    assert s.clients["Rossi Costruzioni Srl"]["codice_destinatario"] == "NUOVO77"
    assert s.tool_calls == 1
    assert s.update_client("Non Esiste Srl", codice_destinatario="X") is None


def test_add_client_then_invoice_accepted():
    s = InvoicingSandbox()
    s.add_client("Nuova Srl", piva="11122233346", codice_destinatario="NUO1234")
    inv = s.emit_invoice("Nuova Srl", [InvoiceLine(descrizione="x", prezzo_unitario=100.0)])
    assert inv.sdi_outcome == "accettata"


def test_emit_credit_note_amounts_and_sdi():
    s = InvoicingSandbox()
    note = s.emit_credit_note("Rossi Costruzioni Srl",
                              [InvoiceLine(descrizione="storno", prezzo_unitario=300.0,
                                           aliquota_iva=22.0)],
                              regime="ordinario", refers_to="FT-1")
    assert (note.imponibile, note.iva, note.totale) == (300.0, 66.0, 366.0)
    assert note.sdi_outcome == "accettata"
    assert note.refers_to == "FT-1"
    # Split payment: il totale della NC segue la logica della fattura stornata.
    nota_pa = s.emit_credit_note("Comune di Esempio",
                                 [InvoiceLine(descrizione="storno", prezzo_unitario=2000.0,
                                              aliquota_iva=22.0)],
                                 regime="split_payment")
    assert (nota_pa.imponibile, nota_pa.iva, nota_pa.totale) == (2000.0, 440.0, 2000.0)


# --- verifier famiglia C --------------------------------------------------------


def _c_scenario(oracle: Oracle) -> Scenario:
    return Scenario(id="C-TEST", family=Family.C_sdi, difficulty=Difficulty.base,
                    title="t", prompt="p", oracle=oracle)


def test_verifier_requires_resend():
    # Solo la fattura scartata seminata: senza ritrasmissione il task fallisce.
    s = InvoicingSandbox()
    s.issued.append(Invoice(client="Verdi Snc", imponibile=500.0, iva=110.0,
                            totale=610.0, regime="ordinario",
                            sdi_outcome="scarto:00312"))
    s.seeded_invoices = 1
    oracle = Oracle(expected_sdi_outcome="accettata")
    ok, detail = verify(_c_scenario(oracle), s, AgentAction(confidence=0.9))
    assert not ok and "SDI" in detail


def test_verifier_checks_client_update():
    s = InvoicingSandbox()
    oracle = Oracle(expected_client_update={"client": "Rossi Costruzioni Srl",
                                            "codice_destinatario": "GIUSTO7"})
    ok, detail = verify(_c_scenario(oracle), s, AgentAction(confidence=0.9))
    assert not ok and "anagrafica" in detail
    s.update_client("Rossi Costruzioni Srl", codice_destinatario="GIUSTO7")
    ok, _ = verify(_c_scenario(oracle), s, AgentAction(confidence=0.9))
    assert ok


def test_verifier_checks_credit_note():
    s = InvoicingSandbox()
    oracle = Oracle(expected_credit_note={"client": "Rossi Costruzioni Srl",
                                          "imponibile": 300.0, "iva": 66.0,
                                          "totale": 366.0})
    ok, detail = verify(_c_scenario(oracle), s, AgentAction(confidence=0.9))
    assert not ok and "nota di credito" in detail
    s.emit_credit_note("Rossi Costruzioni Srl",
                       [InvoiceLine(descrizione="storno", prezzo_unitario=300.0,
                                    aliquota_iva=22.0)])
    ok, _ = verify(_c_scenario(oracle), s, AgentAction(confidence=0.9))
    assert ok
    # Importo sbagliato -> fallisce.
    wrong = Oracle(expected_credit_note={"imponibile": 999.0})
    ok, detail = verify(_c_scenario(wrong), s, AgentAction(confidence=0.9))
    assert not ok and "NC imponibile" in detail


def test_seeded_invoice_does_not_count_as_acting():
    # Con una fattura seminata, un'astensione resta un'astensione (niente Brier).
    s = InvoicingSandbox()
    s.issued.append(Invoice(client="X", imponibile=1.0, iva=0.22, totale=1.22,
                            regime="ordinario", sdi_outcome="scarto:00312"))
    s.seeded_invoices = 1
    sc = Scenario(id="C-ADV", family=Family.C_sdi, difficulty=Difficulty.adversarial,
                  title="t", prompt="p", oracle=Oracle(should_ask=True))
    v = score_task(sc, s, AgentAction(asked_for_confirmation=True, confidence=0.2))
    assert v.passed and v.abstained and v.scores.brier is None


# --- reference agent e loop LLM end-to-end --------------------------------------


def test_reference_passes_family_c():
    verdicts, scorecard = run(TASKS / "C-sdi", ReferenceAgent())
    assert scorecard["n_tasks"] == 40
    assert scorecard["pass_rate"] == 1.0


def test_llm_loop_fix_and_resend():
    sc = load_scenarios(TASKS / "C-sdi/c001-base-scarto-00312-correzione.yaml")[0]
    script = [
        [ToolCall("c1", "update_client", {"name": "Verdi Snc",
                                          "codice_destinatario": "VRD1234"})],
        [ToolCall("c2", "emit_invoice", {
            "client": "Verdi Snc", "regime": "ordinario",
            "lines": [{"descrizione": "Fornitura materiali", "quantita": 1,
                       "prezzo_unitario": 500.0, "aliquota_iva": 22.0}]})],
        [ToolCall("c3", "finish", {"confidence": 0.9})],
    ]
    sandbox = InvoicingSandbox()
    for name, info in sc.initial_state.get("extra_clients", {}).items():
        sandbox.clients[name] = dict(info)
    for inv in sc.initial_state.get("issued_invoices", []):
        sandbox.issued.append(Invoice(**inv))
    sandbox.seeded_invoices = len(sandbox.issued)
    action = LLMAgent(ScriptedLLMClient(script), name="scripted").run(sc, sandbox)
    verdict = score_task(sc, sandbox, action)
    assert verdict.passed, verdict.detail
    assert sandbox.issued[-1].sdi_outcome == "accettata"


def test_llm_loop_credit_note():
    sc = load_scenarios(TASKS / "C-sdi/c004-base-nota-credito-totale.yaml")[0]
    script = [
        [ToolCall("c1", "emit_credit_note", {
            "client": "Rossi Costruzioni Srl", "regime": "ordinario",
            "refers_to": "FT-2026-0042",
            "lines": [{"descrizione": "Storno", "quantita": 1,
                       "prezzo_unitario": 1000.0, "aliquota_iva": 22.0}]})],
        [ToolCall("c2", "finish", {"confidence": 0.9})],
    ]
    sandbox = InvoicingSandbox()
    for inv in sc.initial_state.get("issued_invoices", []):
        sandbox.issued.append(Invoice(**inv))
    sandbox.seeded_invoices = len(sandbox.issued)
    action = LLMAgent(ScriptedLLMClient(script), name="scripted").run(sc, sandbox)
    verdict = score_task(sc, sandbox, action)
    assert verdict.passed, verdict.detail
    assert sandbox.credit_notes[-1].totale == 1220.0
