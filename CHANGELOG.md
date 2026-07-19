# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/), versioning roughly
[SemVer](https://semver.org/) with dated benchmark releases planned from v1.0.

## [Unreleased]

### Added
- **Efficienza con costo reale (token + €).** `LLMResponse` cattura l'usage di token
  riportato dall'API (Anthropic: `input/output_tokens`; OpenAI-compat:
  `prompt/completion_tokens`, assente su alcuni server locali); `LLMAgent` lo accumula
  per run (azzerato a ogni task, contato anche il turno di `finish`). La scorecard
  riporta `tokens_input_total`, `tokens_output_total` e `cost_eur_total` calcolato da
  una **tabella prezzi configurabile** (`costs.yaml`, override con `--costs`). Modello
  non in tabella → costo `null` ("non stimabile"), mai un prezzo inventato. Il
  reference agent resta una baseline valida a costo 0. Test con usage mockato,
  senza rete (`tests/test_costs.py`).

### Changed
- **Calibrazione vera al posto del placeholder.** L'asse calibrazione non è più la media
  di |confidenza − esito|: la scorecard riporta **Brier score**, **ECE** (Expected
  Calibration Error su 10 bin di uguale ampiezza) e i dati completi della **reliability
  curve** (confidenza media vs accuratezza per bin). Per task, `AxisScores.brier` è il
  contributo (p − y)².
- **Le astensioni non sono predizioni a confidenza 0.** Chiedere conferma senza agire è
  un rifiuto di predire: escluso da Brier/ECE e misurato a parte con
  `abstention_accuracy` (quota di astensioni avvenute dove astenersi era corretto).
  Chiude il buco per cui un agente che non faceva nulla con confidenza 0 otteneva
  calibrazione "perfetta". Chi invece agisce su un task ambiguo entra nel pool con
  esito 0: la sovraconfidenza resta punita.
- `Verdict` espone `confidence` (clampata in [0, 1]) e `abstained`; `aggregate()` riporta
  `brier`, `ece`, `reliability_bins`, `n_predictions`, `n_abstentions`,
  `abstention_accuracy`.

### Fixed
- **Reverse charge non sconta l'imposta di bollo** (principio di alternatività IVA/bollo):
  rimosso il bollo €2 erroneamente applicato (oracoli B-002, B-009 corretti).
- Rimosso l'uso improprio del codice SDI `00400` per "PA senza split payment" (lo split
  payment non è un controllo di scarto SDI).

### Added
- `docs/FISCAL-RULES.md`: ogni regola fiscale tracciata con fonte e stato di validazione.
- Adapter **OpenAI-compatibile** (`openai_client.py`): un solo client per GPT e per modelli
  locali (Ollama / llama.cpp / vLLM) cambiando `--base-url`.
- Runner: opzioni `--agent {reference,anthropic,openai,local}`, `--base-url`, `--save`
  (salvataggio transcript per riproducibilita).
- Hardening: gestione errori sulle tool-call (argomenti malformati non interrompono il run).

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
