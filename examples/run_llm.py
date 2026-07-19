"""Esempio: esegui ItalBizBench con un agente LLM reale (Anthropic).

Prerequisiti:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-...

Uso:
    python examples/run_llm.py                 # tutta la suite
    python examples/run_llm.py tasks/A-anagrafiche --model claude-sonnet-5
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from italbizbench.adapters.anthropic_client import AnthropicLLMClient
from italbizbench.adapters.llm import LLMAgent
from italbizbench.runner import run

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("tasks", nargs="?", default=str(ROOT / "tasks"))
    p.add_argument("--model", default="claude-sonnet-5")
    args = p.parse_args()

    agent = LLMAgent(AnthropicLLMClient(model=args.model), name=f"anthropic:{args.model}")
    verdicts, scorecard = run(Path(args.tasks), agent)

    for v in verdicts:
        print(("PASS" if v.passed else "FAIL"), v.scenario_id, "-", v.detail)
    print("\nScorecard:", json.dumps(scorecard, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
