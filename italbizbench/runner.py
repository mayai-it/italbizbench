"""Runner: carica i task YAML, esegue un adapter, produce la scorecard.

Uso:
    python -m italbizbench.runner tasks/B-emissione
    python -m italbizbench.runner tasks/B-emissione --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from .adapters import AgentAdapter, ReferenceAgent
from .costs import CostTable, compute_cost_eur, load_cost_table
from .models import Scenario, UsageStats, Verdict
from .sandbox import InvoicingSandbox
from .scoring import aggregate, score_task


def load_scenarios(path: Path) -> list[Scenario]:
    files = sorted(path.rglob("*.yaml")) if path.is_dir() else [path]
    scenarios = []
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        scenarios.append(Scenario(**data))
    return scenarios


def _run_usage(agent: AgentAdapter, cost_table: CostTable) -> UsageStats:
    """Usage del run appena concluso, con costo dalla tabella prezzi.

    Un agente senza tracciamento token (es. il reference rule-based) non consuma
    nulla: usage a zero e costo 0.0 — resta un punto di confronto valido e gratuito.
    """
    raw = getattr(agent, "last_usage", None)
    if raw is None:
        return UsageStats(input_tokens=0, output_tokens=0, cost_eur=0.0)
    if not isinstance(raw, UsageStats):  # adapter esotico: nessuna stima affidabile
        return UsageStats(input_tokens=0, output_tokens=0, cost_eur=None)
    model = getattr(agent, "model", None)
    cost = compute_cost_eur(raw, model if isinstance(model, str) else None, cost_table)
    return UsageStats(input_tokens=raw.input_tokens, output_tokens=raw.output_tokens,
                      cost_eur=cost)


def run(path: Path, agent: AgentAdapter, save_dir: Path | None = None,
        cost_table: CostTable | None = None) -> tuple[list[Verdict], dict[str, Any]]:
    if cost_table is None:
        cost_table = load_cost_table()
    verdicts: list[Verdict] = []
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
    for sc in load_scenarios(path):
        sandbox = InvoicingSandbox(clients=dict(InvoicingSandbox().clients))
        for name, info in sc.initial_state.get("extra_clients", {}).items():
            sandbox.clients[name] = info
        action = agent.run(sc, sandbox)
        verdicts.append(score_task(sc, sandbox, action, usage=_run_usage(agent, cost_table)))
        # Salva il transcript dell'agente (per riproducibilita / debug dei run reali).
        transcript = getattr(agent, "last_messages", None)
        if save_dir is not None and transcript is not None:
            (save_dir / f"{sc.id}.json").write_text(
                json.dumps(transcript, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return verdicts, aggregate(verdicts)


def _build_agent(args: argparse.Namespace) -> AgentAdapter:
    """Costruisce l'agente scelto. Import pigri: i client SDK servono solo se usati."""
    if args.agent == "reference":
        return ReferenceAgent()

    from .adapters.llm import LLMAgent
    if args.agent == "anthropic":
        from .adapters.anthropic_client import AnthropicLLMClient
        model = args.model or "claude-sonnet-4-6"
        return LLMAgent(AnthropicLLMClient(model=model), name=f"anthropic:{model}")
    if args.agent == "openai":
        from .adapters.openai_client import OpenAIClient
        model = args.model or "gpt-4o"
        return LLMAgent(OpenAIClient(model=model), name=f"openai:{model}")
    # local: API OpenAI-compatibile (default Ollama)
    from .adapters.openai_client import OpenAIClient
    model = args.model or "qwen2.5"
    base_url = args.base_url or "http://localhost:11434/v1"
    return LLMAgent(OpenAIClient(model=model, base_url=base_url, api_key="local"),
                    name=f"local:{model}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ItalBizBench runner")
    p.add_argument("tasks", type=Path, help="cartella o file di task YAML")
    p.add_argument("--agent", choices=["reference", "anthropic", "openai", "local"],
                   default="reference", help="agente da valutare (default: reference rule-based)")
    p.add_argument("--model", default=None,
                   help="modello LLM (default per vendor se omesso)")
    p.add_argument("--base-url", default=None,
                   help="endpoint OpenAI-compatibile (per --agent local, es. Ollama)")
    p.add_argument("--save", type=Path, default=None,
                   help="cartella dove salvare i transcript degli agenti LLM")
    p.add_argument("--costs", type=Path, default=None,
                   help="tabella costi YAML (default: costs.yaml alla radice del repo)")
    p.add_argument("--json", action="store_true", help="output JSON")
    args = p.parse_args(argv)

    agent: AgentAdapter = _build_agent(args)
    verdicts, scorecard = run(args.tasks, agent, save_dir=args.save,
                              cost_table=load_cost_table(args.costs))

    if args.json:
        print(json.dumps({
            "agent": agent.name,
            "scorecard": scorecard,
            "verdicts": [v.model_dump(mode="json") for v in verdicts],
        }, indent=2, ensure_ascii=False))
        return 0

    print(f"\n=== ItalBizBench — agente: {agent.name} ===")
    for v in verdicts:
        mark = "PASS" if v.passed else "FAIL"
        cal = "astensione" if v.abstained else f"brier={v.scores.brier}"
        print(f"[{mark}] {v.scenario_id:24} ({v.difficulty.value:11}) "
              f"corr={v.scores.correctness} eff={v.scores.efficiency} "
              f"saf={v.scores.safety} conf={v.confidence} {cal}  {v.detail}")
    print("\n--- Scorecard ---")
    print(f"Task: {scorecard['n_tasks']}  Pass-rate: {scorecard['pass_rate']} "
          f"(IC95% {scorecard['correctness_ci95']})")
    print(f"Efficienza media: {scorecard['efficiency_mean']}  "
          f"Sicurezza media: {scorecard['safety_mean']}")
    cost = scorecard["cost_eur_total"]
    print(f"Token: {scorecard['tokens_input_total']} in / "
          f"{scorecard['tokens_output_total']} out  "
          f"Costo: {'non stimabile' if cost is None else f'EUR {cost}'}")
    print(f"Calibrazione (su {scorecard['n_predictions']} predizioni): "
          f"Brier={scorecard['brier']}  ECE={scorecard['ece']}")
    print(f"Astensioni: {scorecard['n_abstentions']} "
          f"(accuratezza: {scorecard['abstention_accuracy']})")
    print(f"Per difficolta: {scorecard['by_difficulty']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
