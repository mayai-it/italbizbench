"""Test della famiglia F: orchestrazione multi-step, oracolo sullo stato finale."""
from pathlib import Path

from italbizbench.adapters import ReferenceAgent
from italbizbench.adapters.llm import LLMAgent, ScriptedLLMClient, ToolCall
from italbizbench.models import AgentAction, Difficulty, Family, Oracle, Scenario
from italbizbench.runner import load_scenarios, run
from italbizbench.sandbox import BankTransaction, Invoice, InvoicingSandbox
from italbizbench.scoring import score_task
from italbizbench.verifier import verify

TASKS = Path(__file__).resolve().parent.parent / "tasks"


def _scenario(oracle: Oracle, expected_tool_calls: int = 3) -> Scenario:
    return Scenario(id="F-TEST", family=Family.F_orchestrazione,
                    difficulty=Difficulty.base, title="t", prompt="p",
                    oracle=oracle, expected_tool_calls=expected_tool_calls)


def _seed_recon(sandbox: InvoicingSandbox) -> None:
    sandbox.issued.append(Invoice(client="Verdi Snc", imponibile=300.0, iva=66.0,
                                  totale=366.0, regime="ordinario",
                                  sdi_outcome="accettata", numero="FT-1"))
    sandbox.seeded_invoices = len(sandbox.issued)
    sandbox.transactions.append(BankTransaction(id="TX-1", data="2026-07-24",
                                                importo=366.0, controparte="Verdi Snc",
                                                causale="FT-1"))


ORACLE = Oracle(expected_regime="ordinario", expected_imponibile=500.0,
                expected_iva=110.0, expected_totale=610.0,
                expected_sdi_outcome="accettata",
                expected_reconciliations=[{"tx_id": "TX-1", "numero": "FT-1"}])


# --- verifier famiglia F: oracolo combinato -------------------------------------


def test_verify_combined_final_state():
    from italbizbench.models import InvoiceLine
    s = InvoicingSandbox()
    _seed_recon(s)
    s.emit_invoice("Rossi Costruzioni Srl",
                   [InvoiceLine(descrizione="x", prezzo_unitario=500.0,
                                aliquota_iva=22.0)])
    s.reconcile("TX-1", "FT-1")
    ok, detail = verify(_scenario(ORACLE), s, AgentAction())
    assert ok, detail


def test_verify_fails_if_any_piece_missing():
    from italbizbench.models import InvoiceLine
    # Solo emissione, riconciliazione mancante -> fallisce.
    s = InvoicingSandbox()
    _seed_recon(s)
    s.emit_invoice("Rossi Costruzioni Srl",
                   [InvoiceLine(descrizione="x", prezzo_unitario=500.0,
                                aliquota_iva=22.0)])
    ok, detail = verify(_scenario(ORACLE), s, AgentAction())
    assert not ok and "abbinamento mancante" in detail
    # Solo riconciliazione, emissione sbagliata -> fallisce sull'importo.
    s2 = InvoicingSandbox()
    _seed_recon(s2)
    s2.emit_invoice("Rossi Costruzioni Srl",
                    [InvoiceLine(descrizione="x", prezzo_unitario=999.0,
                                 aliquota_iva=22.0)])
    s2.reconcile("TX-1", "FT-1")
    ok, detail = verify(_scenario(ORACLE), s2, AgentAction())
    assert not ok and "imponibile" in detail


# --- efficienza: budget per-task -------------------------------------------------


def test_expected_tool_calls_default_and_custom():
    assert Scenario(id="x", family=Family.F_orchestrazione,
                    difficulty=Difficulty.base, title="t", prompt="p",
                    oracle=Oracle()).expected_tool_calls == 3
    # Con budget 6 dichiarato, 6 chiamate = efficienza piena; 12 = 0.5.
    s = InvoicingSandbox()
    s.tool_calls = 6
    v = score_task(_scenario(Oracle(should_ask=True), expected_tool_calls=6), s,
                   AgentAction(asked_for_confirmation=True))
    assert v.scores.efficiency == 1.0
    s.tool_calls = 12
    v = score_task(_scenario(Oracle(should_ask=True), expected_tool_calls=6), s,
                   AgentAction(asked_for_confirmation=True))
    assert v.scores.efficiency == 0.5


# --- reference agent e loop LLM end-to-end --------------------------------------


def test_reference_passes_family_f():
    verdicts, scorecard = run(TASKS / "F-orchestrazione", ReferenceAgent())
    assert scorecard["n_tasks"] == 40
    assert scorecard["pass_rate"] == 1.0
    assert scorecard["efficiency_mean"] == 1.0


def test_llm_loop_multi_step():
    sc = load_scenarios(
        TASKS / "F-orchestrazione/f001-base-emissione-e-incasso.yaml")[0]
    script = [
        [ToolCall("c1", "emit_invoice",
                  {"client": "Rossi Costruzioni Srl", "regime": "ordinario",
                   "lines": [{"descrizione": "Consulenza tecnica",
                              "prezzo_unitario": 500.0, "aliquota_iva": 22.0}]})],
        [ToolCall("c2", "reconcile",
                  {"tx_id": "TX-201", "numero": "FT-2026-0201"})],
        [ToolCall("c3", "finish", {"confidence": 0.9})],
    ]
    agent = LLMAgent(ScriptedLLMClient(script), name="scripted")
    sandbox = InvoicingSandbox()
    for inv in sc.initial_state.get("issued_invoices", []):
        sandbox.issued.append(Invoice(**inv))
    sandbox.seeded_invoices = len(sandbox.issued)
    for t in sc.initial_state.get("transactions", []):
        sandbox.transactions.append(BankTransaction(**t))
    action = agent.run(sc, sandbox)
    v = score_task(sc, sandbox, action)
    assert v.passed, v.detail


def test_adversarial_partial_execution_fails():
    # Su un task F adversarial anche eseguire SOLO il passo chiaro e un errore:
    # il dato ambiguo va chiarito PRIMA di agire.
    sc = load_scenarios(
        TASKS / "F-orchestrazione/"
        "f030-adversarial-chiusura-con-bonifico-cumulativo.yaml")[0]
    sandbox = InvoicingSandbox()
    for inv in sc.initial_state.get("issued_invoices", []):
        sandbox.issued.append(Invoice(**inv))
    sandbox.seeded_invoices = len(sandbox.issued)
    from italbizbench.models import InvoiceLine
    sandbox.emit_invoice("Rossi Costruzioni Srl",
                         [InvoiceLine(descrizione="x", prezzo_unitario=500.0,
                                      aliquota_iva=22.0)])
    ok, _ = verify(sc, sandbox, AgentAction(asked_for_confirmation=True))
    assert not ok
