# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/), versioning roughly
[SemVer](https://semver.org/) with dated benchmark releases planned from v1.0.

## [Unreleased]

### Fixed
- **Reverse charge non sconta l'imposta di bollo** (principio di alternatività IVA/bollo):
  rimosso il bollo €2 erroneamente applicato (oracoli B-002, B-009 corretti).
- Rimosso l'uso improprio del codice SDI `00400` per "PA senza split payment" (lo split
  payment non è un controllo di scarto SDI).

### Added
- `docs/FISCAL-RULES.md`: ogni regola fiscale tracciata con fonte e stato di validazione.

## [0.1.0] — 2026-06-21

### Added
- Benchmark harness: `Scenario` / `Oracle` / `Verdict` models, recursive task runner,
  deterministic per-family verifier.
- Invoicing **sandbox** with an **SDI simulator** (no live APIs; synthetic clients).
- Scoring on **4 axes** (correctness, efficiency, safety, calibration) with **bootstrap
  confidence intervals** on the pass-rate.
- **20 tasks** across two families on 3 difficulty tiers:
  - Family **A — Anagrafiche** (7): P.IVA check-digit validation, recipient code lookup.
  - Family **B — Emissione** (13): ordinary, reverse charge, split payment (PA), exempt
    art.10, stamp duty, SDI rejections, adversarial cases.
- **Reference rule-based agent** (baseline) and a vendor-agnostic **LLM tool-use adapter**
  with an Anthropic client and a `ScriptedLLMClient` for offline tests.
- Project tooling: `ruff`, `mypy --strict`, `pytest`, `Makefile`, CI on Python 3.11–3.13.

### Notes
- Fiscal rules in the sandbox are a first approximation, pending review by an accountant
  before any results are published.

[0.1.0]: https://github.com/mayai-it/italbizbench/releases/tag/v0.1.0
