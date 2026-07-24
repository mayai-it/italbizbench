"""Test della famiglia D: ciclo passivo — PEC in ingresso e registro acquisti."""
from pathlib import Path

from italbizbench.adapters import ReferenceAgent
from italbizbench.adapters.llm import LLMAgent, ScriptedLLMClient, ToolCall
from italbizbench.models import AgentAction, Difficulty, Family, Oracle, Scenario
from italbizbench.runner import load_scenarios, run
from italbizbench.sandbox import InvoicingSandbox, PecMessage, PurchaseInvoice
from italbizbench.scoring import score_task
from italbizbench.verifier import verify

TASKS = Path(__file__).resolve().parent.parent / "tasks"

DOC = {"fornitore": "Alfa Forniture Srl", "piva": "33300011120", "numero": "2026/145",
       "imponibile": 500.0, "iva": 110.0, "totale": 610.0}


def _seed(sandbox: InvoicingSandbox) -> None:
    sandbox.pec_inbox.append(PecMessage(id="PEC-001", sender="alfa@pec.it",
                                        subject="Fattura 2026/145", invoice=dict(DOC)))


# --- sandbox: nuovi strumenti ---------------------------------------------------


def test_list_pec_hides_attachments_and_counts():
    s = InvoicingSandbox()
    _seed(s)
    out = s.list_pec()
    assert out == [{"id": "PEC-001", "sender": "alfa@pec.it",
                    "subject": "Fattura 2026/145"}]
    assert "invoice" not in out[0]  # l'allegato si ottiene solo con read_pec
    assert s.tool_calls == 1


def test_read_pec_returns_message_or_none():
    s = InvoicingSandbox()
    _seed(s)
    msg = s.read_pec("PEC-001")
    assert msg is not None and msg.invoice == DOC
    assert s.read_pec("PEC-999") is None
    assert s.tool_calls == 2


def test_register_purchase_appends_and_counts():
    s = InvoicingSandbox()
    p = s.register_purchase(**DOC)
    assert isinstance(p, PurchaseInvoice)
    assert s.purchases[-1].totale == 610.0
    assert s.tool_calls == 1


def test_seeded_purchases_do_not_count_as_agent_action():
    # Le fatture passive SEMINATE dallo stato iniziale non sono opera dell'agente:
    # su un task adversarial l'astensione deve restare valida.
    s = InvoicingSandbox()
    s.purchases.append(PurchaseInvoice(**DOC))
    s.seeded_purchases = 1
    assert s.agent_acted is False
    s.register_purchase(**DOC)
    assert s.agent_acted is True


# --- verifier famiglia D --------------------------------------------------------


def _scenario(oracle: Oracle, difficulty: Difficulty = Difficulty.base) -> Scenario:
    return Scenario(id="D-TEST", family=Family.D_passivo, difficulty=difficulty,
                    title="t", prompt="p", oracle=oracle)


def test_verify_purchase_match():
    s = InvoicingSandbox()
    s.register_purchase(**DOC)
    ok, detail = verify(_scenario(Oracle(expected_purchase=dict(DOC))), s, AgentAction())
    assert ok, detail


def test_verify_purchase_mismatch_and_missing():
    s = InvoicingSandbox()
    ok, detail = verify(_scenario(Oracle(expected_purchase=dict(DOC))), s, AgentAction())
    assert not ok and "nessuna fattura passiva" in detail
    s.register_purchase(**{**DOC, "totale": 600.0})
    ok, detail = verify(_scenario(Oracle(expected_purchase=dict(DOC))), s, AgentAction())
    assert not ok and "totale" in detail


def test_verify_adversarial_register_is_failure():
    # Su un task should_ask registrare la fattura (dato ambiguo) e un fallimento;
    # astenersi senza agire e un successo.
    s = InvoicingSandbox()
    sc = _scenario(Oracle(should_ask=True), difficulty=Difficulty.adversarial)
    s.register_purchase(**DOC)
    ok, _ = verify(sc, s, AgentAction(asked_for_confirmation=True))
    assert not ok
    s2 = InvoicingSandbox()
    v = score_task(sc, s2, AgentAction(asked_for_confirmation=True, confidence=0.2))
    assert v.passed and v.abstained and v.scores.brier is None


# --- reference agent e loop LLM end-to-end --------------------------------------


def test_reference_passes_family_d():
    verdicts, scorecard = run(TASKS / "D-passivo", ReferenceAgent())
    assert scorecard["n_tasks"] == 40
    assert scorecard["pass_rate"] == 1.0


def test_llm_loop_register_purchase():
    sc = load_scenarios(TASKS / "D-passivo/d001-base-registrazione-semplice.yaml")[0]
    script = [
        [ToolCall("c1", "list_pec", {})],
        [ToolCall("c2", "read_pec", {"msg_id": "PEC-001"})],
        [ToolCall("c3", "register_purchase",
                  {"fornitore": "Alfa Forniture Srl", "piva": "33300011120",
                   "numero": "2026/145", "imponibile": 500.0, "iva": 110.0,
                   "totale": 610.0})],
        [ToolCall("c4", "finish", {"confidence": 0.9})],
    ]
    agent = LLMAgent(ScriptedLLMClient(script), name="scripted")
    sandbox = InvoicingSandbox()
    for m in sc.initial_state.get("pec_inbox", []):
        sandbox.pec_inbox.append(PecMessage(**m))
    action = agent.run(sc, sandbox)
    v = score_task(sc, sandbox, action)
    assert v.passed, v.detail
    assert sandbox.purchases[-1].numero == "2026/145"
