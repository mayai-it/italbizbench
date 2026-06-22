[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Built for AI agents](https://img.shields.io/badge/Built%20for-AI%20agents-purple)](https://mayai.it)
[![Tests](https://github.com/mayai-it/italbizbench/actions/workflows/ci.yml/badge.svg)](https://github.com/mayai-it/italbizbench/actions/workflows/ci.yml)
[![mypy](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://github.com/astral-sh/ruff)

> 🇮🇹 [Documentazione in italiano](README.it.md) — versione ridotta.

# italbizbench

**A benchmark that measures how well an AI agent actually does the fiscal and
administrative work of an Italian SME.**

Everyone says AI agents "automate the Italian business". Nobody measures whether it's
true. ItalBizBench puts an agent in front of invoices, SDI rejections, reverse charge
and split payment — using the same tools an admin clerk would — and gives it an honest
score: **does it complete the task correctly? And when it isn't sure, does it stop or
does it guess?**

Part of [MayAI](https://mayai.it).

## Why this exists

Generic agent benchmarks exist (MCP Atlas, Tool-Decathlon, VoiceBench) but nothing is
vertical to the Italian context: VAT, reverse charge, split payment, recipient code (codice
destinatario), SDI rejection codes, deadlines. ItalBizBench fills that gap and positions
itself as a **neutral yardstick**, not yet another automation agent.

- **Italian-native**: tasks built around real VAT regimes, FatturaPA/SDI behaviour and
  Italian administrative workflows.
- **Agent-first**: the agent acts through tool calls (function calling) exactly as it would
  against `fatture-cli` / `pec-cli` over MCP in production.
- **Deterministic**: every task has a programmatic oracle — no subjective grading.

## What makes it different (the statistics)

The leaderboard does not report a single average. It reports:

- **4 axes**: correctness, efficiency (tool-calls / cost), safety (irreversible actions
  avoided), and **calibration** (does the agent know when it doesn't know?).
- **Bootstrap confidence intervals** on the pass-rate: two agents at 0.81 and 0.79 are
  "different" only if their CIs don't overlap. The average alone is misleading.

## Golden rule

The benchmark **never touches live APIs**. Issuing an invoice or sending a PEC are
irreversible actions. Everything runs in a **sandbox/mock** (`italbizbench/sandbox.py`).
In production the sandbox is swapped for `fatture-cli` pointed at the **test** environment
of Fatture in Cloud — never production. All client data is **synthetic** (fictitious VAT
numbers): never real customer data.

## Installation

```bash
git clone https://github.com/mayai-it/italbizbench.git
cd italbizbench
pip install -e .            # core
pip install -e ".[dev]"     # with ruff, mypy, pytest
```

Requires Python 3.11+.

## Quick start

```bash
# Run the whole suite (recursive over all families) with the reference agent
python -m italbizbench.runner tasks

# A single family
python -m italbizbench.runner tasks/B-emissione

# JSON output (to build a leaderboard)
python -m italbizbench.runner tasks --json
```

Example output:

```
[PASS] B-002-tricky-reverse-charge (tricky) corr=1.0 eff=1.0 saf=1.0 calE=0.1  OK
...
--- Scorecard ---
Task: 20  Pass-rate: 1.0 (CI95% (1.0, 1.0))
Efficiency: 1.0  Safety: 1.0  Calibration error: 0.073
By difficulty: {'adversarial': 1.0, 'base': 1.0, 'tricky': 1.0}
```

## Task families

Each task = scenario + sandbox seed + deterministic oracle. Three difficulty tiers:
`base` (clean case), `tricky` (fiscal edge case), `adversarial` (dirty/ambiguous input
where the agent *should* stop and ask for confirmation).

| Family | v0.1 | Examples |
|---|---|---|
| **A — Anagrafiche / validation** | ✅ 7 tasks | P.IVA check digit, recipient code (private 7-char / PA 6-char / foreign) |
| **B — Invoice issuance** | ✅ 13 tasks | Ordinary, reverse charge, split payment (PA), exempt art.10, stamp duty, SDI rejections |
| C — SDI handling | roadmap | Rejection codes, credit notes, correct-and-resend |
| D — Inbound / PEC | roadmap | Read PEC, extract invoice, register supplier doc |
| E — Reconciliation | roadmap | Match payments↔invoices, VAT period, deadlines |
| F — Orchestration | roadmap | Multi-step "close the month" |

## Testing a real LLM agent

The agent never touches the sandbox directly: it declares *tool calls* (function calling),
the loop runs them against the sandbox and feeds back the result until it calls `finish`.
This is the same shape the agent would use to talk to `fatture-cli` / `pec-cli` over MCP.

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
python -m italbizbench.runner tasks --agent llm --model claude-sonnet-4-6
# or: python examples/run_llm.py
```

To plug in another vendor, implement the `LLMClient` protocol (a single
`complete(system, messages, tools)` method). The loop, verifiers and scoring stay identical.
For deterministic offline tests there's `ScriptedLLMClient`.

> **Swapping the sandbox for the real backend (in TEST):** in `LLMAgent._dispatch`, route
> the tool calls to `fatture-cli` pointed at the **test** environment of Fatture in Cloud
> instead of the in-memory sandbox. Never production.

## Structure

```
italbizbench/
  models.py            # Scenario, Oracle, Verdict (pydantic)
  sandbox.py           # invoicing mock + SDI simulator (no live API)
  verifier.py          # deterministic outcome check, per family
  scoring.py           # 4 axes + bootstrap CI
  runner.py            # load YAML -> run agent -> scorecard
  adapters/
    base.py            # vendor-agnostic agent interface
    reference.py       # rule-based baseline (NOT an LLM): proves the harness runs
    llm.py             # tool-use loop for a real LLM agent
    anthropic_client.py# Anthropic API client (lazy import)
tasks/
  A-anagrafiche/       # 7 tasks
  B-emissione/         # 13 tasks
examples/run_llm.py    # run the suite with an Anthropic agent
docs/blueprint.md      # design rationale & roadmap
```

## Engineering notes

- **Deterministic oracles only.** A task is admitted only if its outcome can be checked
  programmatically (amounts, regime, SDI result). No LLM-as-judge.
- **Calibration is treated carefully.** Correctly abstaining with low confidence on an
  ambiguous input is *good* calibration, not an error — otherwise the benchmark rewards
  overconfident agents.
- **Statistical honesty.** Pass-rate ships with bootstrap CIs; point estimates alone are
  not used to rank agents.
- **The fiscal rules in the sandbox are a first approximation.** Stamp duty, split payment
  and foreign reverse charge are internally consistent but pending review by an accountant
  (roadmap v0.2) before any numbers are announced.

## Quality bar

`pytest` green, `ruff` clean, `mypy --strict` with zero ignores. CI runs the three on
Python 3.11 / 3.12 / 3.13.

## Development

```bash
make dev     # pip install -e ".[dev]"
make test    # pytest
make lint    # ruff
make types   # mypy --strict
make check    # lint + types + test
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution workflow.

> This repository contains a `CLAUDE.md` with instructions for AI coding agents.
> Published for transparency; not required reading for users.

## Roadmap

- **v0.1** (this): families A+B (20 tasks), reference agent, real LLM adapter, scoring + CI. ✅
- **v0.2**: family C (SDI rejections / credit notes), private test set, fiscal rules validated
  by an accountant, first real LLM run published.
- **v0.3**: families D (PEC / inbound) and E (reconciliation), 3–4 agents compared.
- **v1.0**: family F (multi-step orchestration), public leaderboard, dated `v2026.x` releases.

## License

MIT — see [LICENSE](LICENSE).
