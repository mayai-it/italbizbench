"""Testa il loop di tool-use dell'LLMAgent SENZA rete, usando il client scriptato.

Verifica che: (1) il loop esegua le tool-call sulla sandbox e chiuda con finish,
(2) un agente che si ferma e chiede conferma superi un task adversarial.
"""
from pathlib import Path

from italbizbench.adapters.llm import LLMAgent, ScriptedLLMClient, ToolCall
from italbizbench.runner import load_scenarios
from italbizbench.sandbox import InvoicingSandbox
from italbizbench.scoring import score_task

TASKS = Path(__file__).resolve().parent.parent / "tasks"


def _scenario(rel: str):
    return load_scenarios(TASKS / rel)[0]


def test_llm_loop_emits_and_passes():
    sc = _scenario("B-emissione/b001-base-ordinario.yaml")
    script = [
        [ToolCall("c1", "lookup_client", {"name": "Rossi Costruzioni Srl"})],
        [ToolCall("c2", "emit_invoice", {
            "client": "Rossi Costruzioni Srl", "regime": "ordinario",
            "lines": [{"descrizione": "Consulenza", "quantita": 1,
                       "prezzo_unitario": 1000.0, "aliquota_iva": 22.0}],
        })],
        [ToolCall("c3", "finish", {"confidence": 0.9})],
    ]
    agent = LLMAgent(ScriptedLLMClient(script), name="scripted")
    sandbox = InvoicingSandbox()
    action = agent.run(sc, sandbox)
    verdict = score_task(sc, sandbox, action)
    assert verdict.passed
    assert sandbox.issued and sandbox.issued[-1].iva == 220.0


def test_llm_loop_text_turn_ends_with_user_message():
    # Regressione: un turno di solo testo (nessuna tool call) NON deve lasciare
    # la conversazione con un assistant in coda — l'API Anthropic lo tratta come
    # prefill e risponde 400. Il loop deve accodare un sollecito user e proseguire.
    sc = _scenario("B-emissione/b001-base-ordinario.yaml")
    script: list[list[ToolCall]] = [
        [],  # il "modello" divaga in testo puro senza chiamare strumenti
        [ToolCall("c1", "finish", {"confidence": 0.5})],
    ]
    agent = LLMAgent(ScriptedLLMClient(script), name="scripted")
    action = agent.run(sc, InvoicingSandbox())
    assert action is not None
    roles = [m["role"] for m in agent.last_messages]
    # Dopo il turno di solo testo: prompt utente, testo assistant, sollecito user
    # (poi il turno di finish aggiunge il suo assistant con le tool call).
    assert roles[:3] == ["user", "assistant", "user"]
    for prev, cur in zip(roles, roles[1:], strict=False):
        assert not (prev == "assistant" and cur == "assistant")


def test_llm_loop_abstains_on_adversarial():
    sc = _scenario("B-emissione/b005-adversarial-ambiguo.yaml")
    script = [[ToolCall("c1", "finish",
                        {"confidence": 0.2, "asked_for_confirmation": True,
                         "notes": "Importo non specificato."})]]
    agent = LLMAgent(ScriptedLLMClient(script), name="scripted")
    sandbox = InvoicingSandbox()
    action = agent.run(sc, sandbox)
    verdict = score_task(sc, sandbox, action)
    assert verdict.passed
    assert not sandbox.issued  # non ha emesso nulla
