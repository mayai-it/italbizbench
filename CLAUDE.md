# CLAUDE.md

Instructions for AI coding agents working on this repository. Published for transparency;
not required reading for human users.

## What this project is

ItalBizBench is a **benchmark**, not a product or a CLI. It measures how well an AI agent
performs Italian fiscal/administrative tasks. The deliverable is the harness + the task set
+ the scoring, kept rigorous and reproducible.

## Non-negotiable rules

1. **Never call live APIs.** All execution happens in `italbizbench/sandbox.py` (in-memory).
   In production the sandbox is swapped for `fatture-cli` pointed at a **test** environment —
   never production. Do not add code that issues real invoices or sends real PEC.
2. **Synthetic data only.** Fictitious VAT numbers and company names. Never real customer data.
3. **Deterministic oracles only.** A task is valid only if its outcome can be checked
   programmatically. No LLM-as-judge in the scoring path.
4. **Fiscal correctness or explicit approximation.** If a rule is uncertain, flag it; a wrong
   oracle silently corrupts every score.

## Architecture

- `models.py` — pydantic schemas (`Scenario`, `Oracle`, `AgentAction`, `Verdict`).
- `sandbox.py` — invoicing state + SDI simulator; the only place that "acts".
- `verifier.py` — deterministic check, dispatched by `Family`.
- `scoring.py` — 4 axes + bootstrap CI. Keep statistics honest (CIs, not bare means).
- `adapters/` — agents. `reference.py` is the rule-based baseline; `llm.py` is the
  vendor-agnostic tool-use loop; new vendors implement the `LLMClient` protocol.
- `tasks/<Family>/*.yaml` — one scenario per file.

## Before committing

Run `make check` (ruff + mypy --strict + pytest). All three must be green. Add a test when
you change harness behaviour. Keep agent-specific code inside `adapters/`.
