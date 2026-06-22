# Contributing to italbizbench

Thanks for your interest! ItalBizBench is part of [MayAI](https://mayai.it).

## Development setup

```bash
git clone https://github.com/mayai-it/italbizbench.git
cd italbizbench
make dev      # editable install with dev extras (ruff, mypy, pytest)
make check    # lint + types + tests — must be green before a PR
```

## Adding a task

A good task is **deterministically verifiable** and **side-effect free**. To add one:

1. Pick a family folder under `tasks/` (e.g. `tasks/B-emissione/`).
2. Create a YAML file following the `Scenario` schema in `italbizbench/models.py`:
   `id`, `family`, `difficulty`, `prompt`, `initial_state`, and an `oracle` with the
   expected outcome.
3. Use **synthetic data only** — fictitious VAT numbers, invented company names. Never real
   customer data.
4. If the task needs a new tool or a new verification path, extend `sandbox.py` /
   `verifier.py` accordingly, with the rule kept internally consistent.
5. Run `make check`. The reference agent should pass any well-formed task it is designed to
   handle; add a test in `tests/` if you introduce new harness behaviour.

### Difficulty tiers

- `base` — clean, unambiguous case.
- `tricky` — a fiscal edge case (reverse charge, split payment, exemption, stamp duty, SDI
  rejection).
- `adversarial` — dirty or ambiguous input where the correct behaviour is to **stop and ask**
  (`oracle.should_ask: true`), not to guess.

## Fiscal accuracy

Fiscal rules must be correct or explicitly flagged as approximate. If you're unsure about a
rule (bollo thresholds, split payment, intra-EU reverse charge), open an issue rather than
guessing — a wrong oracle is worse than a missing task.

## Code style

- `ruff` for linting and import order, `mypy --strict` for types (zero unmotivated ignores).
- Conventional, descriptive commit messages.
- Keep the harness vendor-agnostic: agent-specific code lives in `adapters/`.

## Pull requests

1. Branch from `main`.
2. `make check` green locally.
3. Describe what you changed and why; link any related issue.

For bugs and ideas, open an [issue](https://github.com/mayai-it/italbizbench/issues).
