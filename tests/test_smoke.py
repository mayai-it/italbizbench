"""Smoke test: l'harness gira e l'agente di riferimento supera i task ben formati."""
from pathlib import Path

from italbizbench.adapters import ReferenceAgent
from italbizbench.runner import run
from italbizbench.sandbox import InvoicingSandbox

TASKS = Path(__file__).resolve().parent.parent / "tasks"


def test_reference_agent_passes_all():
    verdicts, scorecard = run(TASKS, ReferenceAgent())
    assert scorecard["n_tasks"] == 20
    # La baseline rule-based e progettata per essere corretta su tutti i task v0.1.
    assert scorecard["pass_rate"] == 1.0
    # Ben calibrata: confidenza coerente con l'esito, astensione corretta sugli ambigui.
    assert scorecard["calibration_error_mean"] < 0.15


def test_piva_checksum():
    s = InvoicingSandbox()
    assert s.validate_piva("12345678903") is True   # check digit corretto
    assert s.validate_piva("12345678900") is False  # check digit errato
    assert s.validate_piva("1234567890") is False    # 10 cifre
    assert s.validate_piva("DE123456789") is False   # estero: non validabile
