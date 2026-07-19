"""Test del supporto al test set privato e della risoluzione degli ID modello."""
from pathlib import Path

import pytest

from italbizbench.adapters import ReferenceAgent
from italbizbench.adapters.hints import endpoint_unreachable_hint, model_not_accepted_hint
from italbizbench.runner import (
    DEFAULT_MODELS,
    MODEL_ENV_VARS,
    load_all_scenarios,
    main,
    resolve_model,
    run,
)

TASKS = Path(__file__).resolve().parent.parent / "tasks"

PRIVATE_TASK = """\
id: AP-001-base-piva-privata
family: A-anagrafiche
difficulty: base
title: Task privato di esempio
prompt: 'La P.IVA "12345678903" e valida?'
initial_state:
  check: piva
  piva: "12345678903"
oracle:
  expected_result:
    valid: true
max_tool_calls: 4
"""


def _private_dir(tmp_path: Path, task_yaml: str = PRIVATE_TASK) -> Path:
    d = tmp_path / "tasks-private"
    d.mkdir()
    (d / "ap001.yaml").write_text(task_yaml, encoding="utf-8")
    return d


# --- test set privato ----------------------------------------------------------


def test_private_tasks_added_to_public(tmp_path: Path) -> None:
    private = _private_dir(tmp_path)
    verdicts, scorecard = run([TASKS / "A-anagrafiche", private], ReferenceAgent())
    assert scorecard["n_tasks"] == 41  # 40 pubblici + 1 privato
    assert any(v.scenario_id == "AP-001-base-piva-privata" for v in verdicts)


def test_duplicate_ids_across_sources_rejected(tmp_path: Path) -> None:
    # Stesso ID di un task pubblico: il runner deve rifiutare, non sovrascrivere.
    dup = PRIVATE_TASK.replace("AP-001-base-piva-privata", "A-001-base-piva-valida")
    private = _private_dir(tmp_path, dup)
    with pytest.raises(ValueError, match="duplicati"):
        load_all_scenarios([TASKS / "A-anagrafiche", private])


def test_missing_private_dir_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main([str(TASKS / "A-anagrafiche"),
              "--private-dir", str(tmp_path / "non-esiste")])


def test_gitignore_excludes_private_tasks() -> None:
    gitignore = (TASKS.parent / ".gitignore").read_text(encoding="utf-8")
    assert "tasks-private/*" in gitignore
    assert "!tasks-private/README.md" in gitignore


# --- risoluzione ID modello ----------------------------------------------------


def test_resolve_model_precedence() -> None:
    env = {MODEL_ENV_VARS["anthropic"]: "modello-da-env"}
    # --model vince su tutto.
    assert resolve_model("anthropic", "modello-cli", env) == "modello-cli"
    # Poi la variabile d'ambiente.
    assert resolve_model("anthropic", None, env) == "modello-da-env"
    # Infine il default del vendor.
    assert resolve_model("anthropic", None, {}) == DEFAULT_MODELS["anthropic"]


def test_default_models_declared_for_every_vendor() -> None:
    assert set(DEFAULT_MODELS) == {"anthropic", "openai", "local"}
    assert set(MODEL_ENV_VARS) == set(DEFAULT_MODELS)
    # I default devono essere ID plausibili, non vuoti.
    assert all(m for m in DEFAULT_MODELS.values())


def test_default_models_priced_in_cost_table() -> None:
    # Ogni modello di default (tranne il locale, a costo 0 comunque presente)
    # deve avere un prezzo in costs.yaml: run di default -> costo stimabile.
    from italbizbench.costs import load_cost_table
    table = load_cost_table()
    for vendor, model in DEFAULT_MODELS.items():
        assert model in table.models, f"{vendor}: {model} manca in costs.yaml"


# --- messaggi d'errore chiari --------------------------------------------------


def test_model_not_accepted_hint_is_actionable() -> None:
    msg = model_not_accepted_hint("Anthropic", "claude-vecchio-1",
                                  "ITALBIZBENCH_MODEL_ANTHROPIC", "404 not found")
    assert "claude-vecchio-1" in msg
    assert "--model" in msg
    assert "ITALBIZBENCH_MODEL_ANTHROPIC" in msg
    assert "404 not found" in msg


def test_endpoint_unreachable_hint_mentions_base_url() -> None:
    msg = endpoint_unreachable_hint("OpenAI-compatibile",
                                    "http://localhost:11434/v1", "connection refused")
    assert "http://localhost:11434/v1" in msg
    assert "--base-url" in msg
