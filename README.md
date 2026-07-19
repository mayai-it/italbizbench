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
- **Calibration done properly**: Brier score, ECE (Expected Calibration Error) over
  confidence bins, and the full reliability curve (mean confidence vs observed accuracy
  per bin) — not a naive |confidence − outcome| average.
- **Abstentions are not confidence-0 predictions.** When the agent stops and asks for
  confirmation instead of acting, that is a *refusal to predict*, not a prediction:
  it is excluded from Brier/ECE and scored separately as `abstention_accuracy`
  (the share of abstentions that happened where abstaining was in fact correct).
  Counting abstentions as p=0 would make "never do anything" a perfectly calibrated
  strategy. Acting on an ambiguous task *does* enter the pool (with outcome 0), so
  overconfidence on dirty data is punished, not hidden.
- **Bootstrap *and* Wilson confidence intervals** on the pass-rate: two agents at 0.81
  and 0.79 are "different" only if their CIs don't overlap. The average alone is
  misleading. Wilson is a closed-form interval that stays honest even at extreme
  proportions (0/n, n/n), where the percentile bootstrap collapses to a degenerate
  (p, p).

### How many tasks before the CIs can tell two agents apart?

Be suspicious of benchmarks that rank on a handful of tasks. The half-width of a
Wilson/Wald interval scales as `~1.96·√(p(1−p)/n)`. In practice:

| n tasks | CI half-width @ p≈0.8 | can distinguish pass-rates that differ by… |
|---|---|---|
| 20 | ±0.18 | ~0.35 — almost nothing |
| 40 (one family) | ±0.12 | ~0.25 |
| 80 (current suite) | ±0.09 | ~0.18 |
| 300 | ±0.045 | ~0.09 (≈10 points) |

So with the current 80 tasks the benchmark can separate *clearly different* agents
(e.g. 0.95 vs 0.75), but **not** agents ~10 points apart — that needs roughly 300
tasks (or paired per-task comparisons, planned for a later release). This is stated
here so nobody reads a 2-point leaderboard gap as signal.

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
[PASS] B-002-tricky-reverse-charge (tricky) corr=1.0 eff=1.0 saf=1.0 conf=0.9 brier=0.01  OK
...
--- Scorecard ---
Task: 80  Pass-rate: 1.0 (IC95% bootstrap (1.0, 1.0), Wilson (0.954, 1.0))
Efficienza media: 1.0  Sicurezza media: 1.0
Token: 0 in / 0 out  Costo: EUR 0.0
Calibrazione (su 58 predizioni): Brier=0.0077  ECE=0.0845
Astensioni: 22 (accuratezza: 1.0)
Per difficolta: {'adversarial': 1.0, 'base': 1.0, 'tricky': 1.0}
```

## Task families

Each task = scenario + sandbox seed + deterministic oracle. Three difficulty tiers:
`base` (clean case), `tricky` (fiscal edge case), `adversarial` (dirty/ambiguous input
where the agent *should* stop and ask for confirmation).

| Family | now | Examples |
|---|---|---|
| **A — Anagrafiche / validation** | ✅ 40 tasks | P.IVA check digit (valid/invalid/transposed/foreign), recipient code (private 7-char / PA 6-char / foreign), dirty data |
| **B — Invoice issuance** | ✅ 40 tasks | Ordinary (all VAT rates), reverse charge, split payment (PA), exempt art.10, stamp-duty threshold edge cases, SDI rejections |
| **C — SDI handling** | ✅ 8 tasks (scaffold) | Rejection 00312/00200 → fix registry → resend; total & partial credit notes (TD04), split-payment credit note |
| D — Inbound / PEC | roadmap | Read PEC, extract invoice, register supplier doc |
| E — Reconciliation | roadmap | Match payments↔invoices, VAT period, deadlines |
| F — Orchestration | roadmap | Multi-step "close the month" |

## Testing a real LLM agent

The agent never touches the sandbox directly: it declares *tool calls* (function calling),
the loop runs them against the sandbox and feeds back the result until it calls `finish`.
This is the same shape the agent would use to talk to `fatture-cli` / `pec-cli` over MCP.

```bash
# Claude (Anthropic)
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
python -m italbizbench.runner tasks --agent anthropic --model claude-sonnet-5

# GPT (OpenAI)
pip install openai
export OPENAI_API_KEY=sk-...
python -m italbizbench.runner tasks --agent openai --model gpt-5.6-sol

# Local model (Ollama / llama.cpp / vLLM — any OpenAI-compatible endpoint)
python -m italbizbench.runner tasks --agent local --model qwen2.5 \
    --base-url http://localhost:11434/v1

# Save per-task transcripts for reproducibility / debugging
python -m italbizbench.runner tasks --agent anthropic --save runs/claude
```

All three LLM agents share one tool-use loop; only the client differs. To plug in another
vendor, implement the `LLMClient` protocol (a single `complete(system, messages, tools)`
method). The loop, verifiers and scoring stay identical. For deterministic offline tests
there's `ScriptedLLMClient`.

**Model IDs are configurable, and stale ones fail loudly.** Default per-vendor model IDs
live in `runner.DEFAULT_MODELS` (checked against the vendors' official docs on
2026-07-19) and can be overridden per run with `--model` or persistently with the
`ITALBIZBENCH_MODEL_ANTHROPIC` / `ITALBIZBENCH_MODEL_OPENAI` / `ITALBIZBENCH_MODEL_LOCAL`
environment variables. If the API rejects a model ID (or the endpoint is unreachable),
the run fails immediately with an actionable message — never a silent fallback to a
stale default.

### Private held-out test set

Public benchmarks get gamed. The repo ships the structure for a **private task set**:
`tasks-private/` is git-ignored (only its README is committed), uses the same YAML
format and rules as `tasks/`, and is added to a run with
`--private-dir tasks-private`. The runner refuses duplicate task IDs across sources.
Published results must state whether they include the private set.

> **Swapping the sandbox for the real backend (in TEST):** in `LLMAgent._dispatch`, route
> the tool calls to `fatture-cli` pointed at the **test** environment of Fatture in Cloud
> instead of the in-memory sandbox. Never production.

### Static leaderboard (GitHub Pages ready)

Each `--save` run also writes the full JSON report (`report.json`). Feed any number of
them to the leaderboard generator to get a **single self-contained HTML page** —
inline CSS, inline SVG reliability curves, no JavaScript, no external resources,
readable in light and dark mode, deterministic (same input → same bytes):

```bash
python -m italbizbench.runner tasks --agent anthropic --json --save runs/claude > /dev/null
python -m italbizbench.runner tasks --agent openai   --json --save runs/gpt    > /dev/null
python -m italbizbench.leaderboard runs/claude/report.json runs/gpt/report.json \
    -o leaderboard.html
```

The page shows the ranking (pass-rate with bootstrap + Wilson CIs, the 4 axes, tokens
and cost), the per-difficulty breakdown and one reliability curve per agent. Publish it
as-is on GitHub Pages.

### Token usage and cost (€)

The efficiency axis is not just tool-call discipline: every LLM run records the token
usage reported by the API, and the scorecard shows total tokens and the cost in euro,
computed from a **configurable per-model price table** ([`costs.yaml`](costs.yaml),
override with `--costs my-prices.yaml`). A model missing from the table yields
`cost_eur: null` ("not estimable") — never a silently invented price. The reference
agent uses no tokens and stays a valid, zero-cost baseline.

## Structure

```
italbizbench/
  models.py            # Scenario, Oracle, Verdict (pydantic)
  sandbox.py           # invoicing mock + SDI simulator (no live API)
  verifier.py          # deterministic outcome check, per family
  scoring.py           # 4 axes + bootstrap & Wilson CIs + calibration (Brier/ECE)
  costs.py             # per-model price table (costs.yaml) -> cost in EUR per run
  piva.py              # P.IVA check digit + synthetic (valid) P.IVA generator
  leaderboard.py       # N runner reports -> static self-contained HTML leaderboard
  runner.py            # load YAML -> run agent -> scorecard
  adapters/
    base.py            # vendor-agnostic agent interface
    reference.py       # rule-based baseline (NOT an LLM): proves the harness runs
    llm.py             # tool-use loop for a real LLM agent
    anthropic_client.py# Anthropic API client (lazy import)
    openai_client.py   # OpenAI-compatible client — GPT and local models (lazy import)
tasks/
  A-anagrafiche/       # 40 tasks
  B-emissione/         # 40 tasks
  C-sdi/               # 8 tasks (scaffold): rejected-invoice recovery, credit notes
examples/run_llm.py    # run the suite with an Anthropic agent
docs/blueprint.md      # design rationale & roadmap
```

## Engineering notes

- **Deterministic oracles only.** A task is admitted only if its outcome can be checked
  programmatically (amounts, regime, SDI result). No LLM-as-judge.
- **Calibration is treated carefully.** The calibration axis reports Brier score and ECE
  computed *only* on tasks where the agent actually made a prediction. Abstaining
  (asking for confirmation without acting) is measured separately via
  `abstention_accuracy` — otherwise the benchmark would reward agents that never act.
- **Statistical honesty.** Pass-rate ships with bootstrap CIs; point estimates alone are
  not used to rank agents.
- **The fiscal rules are sourced, not yet professionally certified.** Every rule (VAT, bollo,
  reverse charge, split payment, SDI codes) is documented with its source and a validation
  status in [docs/FISCAL-RULES.md](docs/FISCAL-RULES.md). Numbers should be labelled
  "rules verified against sources, not yet certified by an accountant".

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
