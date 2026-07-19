"""Test del costo reale (token + euro) con usage MOCKATO — niente rete, niente SDK.

Copre: caricamento tabella costi, calcolo del costo a mano, accumulo token
nell'LLMAgent, estrazione usage dai formati di risposta Anthropic/OpenAI,
e il reference agent che resta a costo 0.
"""
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from italbizbench.adapters import ReferenceAgent
from italbizbench.adapters.anthropic_client import usage_from_response as usage_anthropic
from italbizbench.adapters.llm import LLMAgent, LLMResponse, ToolCall
from italbizbench.adapters.openai_client import usage_from_response as usage_openai
from italbizbench.costs import CostTable, ModelCost, compute_cost_eur, load_cost_table
from italbizbench.models import UsageStats
from italbizbench.runner import load_scenarios, run
from italbizbench.sandbox import InvoicingSandbox

TASKS = Path(__file__).resolve().parent.parent / "tasks"


# --- tabella costi -------------------------------------------------------------


def test_load_cost_table_from_yaml(tmp_path: Path) -> None:
    f = tmp_path / "costs.yaml"
    f.write_text(
        "currency: EUR\nmodels:\n  modello-x: {input_per_mtok: 2.0, output_per_mtok: 10.0}\n",
        encoding="utf-8",
    )
    table = load_cost_table(f)
    assert table.currency == "EUR"
    assert table.models["modello-x"].input_per_mtok == 2.0


def test_load_cost_table_missing_file_is_empty(tmp_path: Path) -> None:
    table = load_cost_table(tmp_path / "inesistente.yaml")
    assert table.models == {}


def test_bundled_costs_yaml_is_valid() -> None:
    # La tabella di default committata nel repo deve caricarsi ed essere in euro.
    table = load_cost_table()
    assert table.currency == "EUR"
    assert len(table.models) > 0


# --- calcolo costo (a mano) ----------------------------------------------------


def _table() -> CostTable:
    return CostTable(models={"modello-x": ModelCost(input_per_mtok=2.0, output_per_mtok=10.0)})


def test_compute_cost_hand_computed() -> None:
    # 1000 token in a 2 EUR/M + 500 token out a 10 EUR/M
    # = 1000*2/1e6 + 500*10/1e6 = 0.002 + 0.005 = 0.007 EUR
    usage = UsageStats(input_tokens=1000, output_tokens=500)
    assert compute_cost_eur(usage, "modello-x", _table()) == 0.007


def test_compute_cost_unknown_model_is_none() -> None:
    usage = UsageStats(input_tokens=1000, output_tokens=500)
    assert compute_cost_eur(usage, "modello-ignoto", _table()) is None
    assert compute_cost_eur(usage, None, _table()) is None


# --- accumulo nell'LLMAgent ----------------------------------------------------


class UsageStubClient:
    """Client fittizio: risposte pre-decise CON usage, come farebbe un'API vera."""

    model = "modello-x"

    def __init__(self) -> None:
        self._turns = [
            LLMResponse(tool_calls=[ToolCall("c1", "lookup_client",
                                             {"name": "Rossi Costruzioni Srl"})],
                        usage=UsageStats(input_tokens=100, output_tokens=20)),
            LLMResponse(tool_calls=[ToolCall("c2", "emit_invoice", {
                "client": "Rossi Costruzioni Srl", "regime": "ordinario",
                "lines": [{"descrizione": "Consulenza", "quantita": 1,
                           "prezzo_unitario": 1000.0, "aliquota_iva": 22.0}]})],
                        usage=UsageStats(input_tokens=150, output_tokens=30)),
            LLMResponse(tool_calls=[ToolCall("c3", "finish", {"confidence": 0.9})],
                        usage=UsageStats(input_tokens=200, output_tokens=10)),
        ]
        self._i = 0

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> LLMResponse:
        resp = self._turns[self._i]
        self._i += 1
        return resp


def test_llm_agent_accumulates_usage() -> None:
    sc = load_scenarios(TASKS / "B-emissione/b001-base-ordinario.yaml")[0]
    agent = LLMAgent(UsageStubClient(), name="stub")
    agent.run(sc, InvoicingSandbox())
    # Anche il turno che chiude con `finish` viene contato.
    assert agent.last_usage.input_tokens == 100 + 150 + 200
    assert agent.last_usage.output_tokens == 20 + 30 + 10
    assert agent.model == "modello-x"


def test_llm_agent_usage_resets_between_runs() -> None:
    sc = load_scenarios(TASKS / "B-emissione/b001-base-ordinario.yaml")[0]
    agent = LLMAgent(UsageStubClient(), name="stub")
    agent.run(sc, InvoicingSandbox())
    first = agent.last_usage.input_tokens
    agent.client = UsageStubClient()  # nuova sequenza di turni
    agent.run(sc, InvoicingSandbox())
    assert agent.last_usage.input_tokens == first  # non raddoppia: azzerato a inizio run


def test_runner_attaches_cost_to_verdicts() -> None:
    verdicts, scorecard = run(TASKS / "B-emissione/b001-base-ordinario.yaml",
                              LLMAgent(UsageStubClient(), name="stub"),
                              cost_table=_table())
    v = verdicts[0]
    assert v.usage is not None
    assert v.usage.input_tokens == 450 and v.usage.output_tokens == 60
    # 450*2/1e6 + 60*10/1e6 = 0.0009 + 0.0006 = 0.0015 EUR
    assert v.usage.cost_eur == 0.0015
    assert scorecard["tokens_input_total"] == 450
    assert scorecard["cost_eur_total"] == 0.0015


# --- estrazione usage dai formati dei vendor -----------------------------------


def test_usage_from_anthropic_response() -> None:
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=123, output_tokens=45))
    u = usage_anthropic(resp)
    assert u is not None and (u.input_tokens, u.output_tokens) == (123, 45)
    assert usage_anthropic(SimpleNamespace(usage=None)) is None


def test_usage_from_openai_response() -> None:
    resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=200, completion_tokens=50))
    u = usage_openai(resp)
    assert u is not None and (u.input_tokens, u.output_tokens) == (200, 50)
    # Server locali OpenAI-compatibili possono omettere usage del tutto.
    assert usage_openai(SimpleNamespace(usage=None)) is None


# --- reference agent: costo 0 ----------------------------------------------------


def test_reference_agent_has_zero_cost() -> None:
    verdicts, scorecard = run(TASKS / "A-anagrafiche", ReferenceAgent(), cost_table=_table())
    assert all(v.usage is not None and v.usage.cost_eur == 0.0 for v in verdicts)
    assert scorecard["tokens_input_total"] == 0
    assert scorecard["cost_eur_total"] == 0.0
