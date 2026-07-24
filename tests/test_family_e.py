"""Test della famiglia E: riconciliazione movimenti bancari <-> fatture emesse."""
from pathlib import Path

from italbizbench.adapters import ReferenceAgent
from italbizbench.adapters.llm import LLMAgent, ScriptedLLMClient, ToolCall
from italbizbench.models import AgentAction, Difficulty, Family, Oracle, Scenario
from italbizbench.runner import load_scenarios, run
from italbizbench.sandbox import BankTransaction, Invoice, InvoicingSandbox
from italbizbench.scoring import score_task
from italbizbench.verifier import verify

TASKS = Path(__file__).resolve().parent.parent / "tasks"


def _seed(sandbox: InvoicingSandbox) -> None:
    sandbox.issued.append(Invoice(client="Rossi Costruzioni Srl", imponibile=500.0,
                                  iva=110.0, totale=610.0, regime="ordinario",
                                  sdi_outcome="accettata", numero="FT-1"))
    sandbox.seeded_invoices = 1
    sandbox.transactions.append(BankTransaction(id="TX-1", data="2026-07-10",
                                                importo=610.0,
                                                controparte="Rossi Costruzioni Srl",
                                                causale="Saldo FT-1"))


# --- sandbox: nuovi strumenti ---------------------------------------------------


def test_list_transactions_and_open_invoices_count():
    s = InvoicingSandbox()
    _seed(s)
    assert s.list_transactions()[0]["id"] == "TX-1"
    assert s.list_open_invoices() == [{"numero": "FT-1",
                                       "client": "Rossi Costruzioni Srl",
                                       "totale": 610.0}]
    assert s.tool_calls == 2


def test_reconcile_marks_paid_and_counts():
    s = InvoicingSandbox()
    _seed(s)
    out = s.reconcile("TX-1", "FT-1")
    assert out == {"tx_id": "TX-1", "numero": "FT-1", "paid": True}
    assert s.issued[0].paid is True
    assert s.list_open_invoices() == []  # la fattura incassata esce dalle aperte
    assert s.tool_calls == 2


def test_reconcile_unknown_returns_error_without_side_effects():
    s = InvoicingSandbox()
    _seed(s)
    assert "error" in s.reconcile("TX-999", "FT-1")
    assert "error" in s.reconcile("TX-1", "FT-999")
    assert not s.reconciliations and s.issued[0].paid is False


def test_reconciliation_is_agent_action():
    # Le fatture/movimenti seminati non contano; la riconciliazione si.
    s = InvoicingSandbox()
    _seed(s)
    assert s.agent_acted is False
    s.reconcile("TX-1", "FT-1")
    assert s.agent_acted is True


# --- verifier famiglia E --------------------------------------------------------


def _scenario(oracle: Oracle, difficulty: Difficulty = Difficulty.base) -> Scenario:
    return Scenario(id="E-TEST", family=Family.E_riconciliazione, difficulty=difficulty,
                    title="t", prompt="p", oracle=oracle)


ORACLE = Oracle(expected_reconciliations=[{"tx_id": "TX-1", "numero": "FT-1"}])


def test_verify_exact_match():
    s = InvoicingSandbox()
    _seed(s)
    s.reconcile("TX-1", "FT-1")
    ok, detail = verify(_scenario(ORACLE), s, AgentAction())
    assert ok, detail


def test_verify_missing_and_spurious_matches():
    s = InvoicingSandbox()
    _seed(s)
    ok, detail = verify(_scenario(ORACLE), s, AgentAction())
    assert not ok and "mancante" in detail
    # Abbinamento indebito: un movimento riconciliato alla fattura sbagliata.
    s.issued.append(Invoice(client="Gialli Srl", imponibile=100.0, iva=22.0,
                            totale=122.0, regime="ordinario", numero="FT-2"))
    s.reconcile("TX-1", "FT-2")
    ok, detail = verify(_scenario(ORACLE), s, AgentAction())
    assert not ok and "indebito" in detail and "mancante" in detail


def test_verify_adversarial_reconcile_is_failure():
    s = InvoicingSandbox()
    _seed(s)
    sc = _scenario(Oracle(should_ask=True), difficulty=Difficulty.adversarial)
    v = score_task(sc, s, AgentAction(asked_for_confirmation=True, confidence=0.2))
    assert v.passed and v.abstained
    s.reconcile("TX-1", "FT-1")
    ok, _ = verify(sc, s, AgentAction(asked_for_confirmation=True))
    assert not ok


# --- reference agent e loop LLM end-to-end --------------------------------------


def test_reference_passes_family_e():
    verdicts, scorecard = run(TASKS / "E-riconciliazione", ReferenceAgent())
    assert scorecard["n_tasks"] == 8
    assert scorecard["pass_rate"] == 1.0


def test_llm_loop_reconcile():
    sc = load_scenarios(TASKS / "E-riconciliazione/e001-base-abbinamento-semplice.yaml")[0]
    script = [
        [ToolCall("c1", "list_transactions", {})],
        [ToolCall("c2", "list_open_invoices", {})],
        [ToolCall("c3", "reconcile", {"tx_id": "TX-001", "numero": "FT-2026-0101"})],
        [ToolCall("c4", "finish", {"confidence": 0.9})],
    ]
    agent = LLMAgent(ScriptedLLMClient(script), name="scripted")
    sandbox = InvoicingSandbox()
    for inv in sc.initial_state.get("issued_invoices", []):
        sandbox.issued.append(Invoice(**inv))
    sandbox.seeded_invoices = len(sandbox.issued)
    for tx in sc.initial_state.get("transactions", []):
        sandbox.transactions.append(BankTransaction(**tx))
    action = agent.run(sc, sandbox)
    v = score_task(sc, sandbox, action)
    assert v.passed, v.detail
    assert sandbox.issued[0].paid is True
