"""Smoke test: l'harness gira e l'agente di riferimento supera i task ben formati."""
from pathlib import Path

from italbizbench.adapters import ReferenceAgent
from italbizbench.runner import run
from italbizbench.sandbox import InvoicingSandbox

TASKS = Path(__file__).resolve().parent.parent / "tasks"


def test_reference_agent_passes_all():
    verdicts, scorecard = run(TASKS, ReferenceAgent())
    assert scorecard["n_tasks"] == 240  # 40 per ciascuna famiglia A-F
    # La baseline rule-based e progettata per essere corretta su tutti i task ben formati.
    assert scorecard["pass_rate"] == 1.0
    # Ben calibrata: predice con confidenza alta e passa (Brier basso), e si astiene
    # esattamente sui task adversarial (accuratezza di astensione 1.0).
    assert scorecard["brier"] is not None and scorecard["brier"] < 0.05
    assert scorecard["abstention_accuracy"] == 1.0
    assert scorecard["n_predictions"] + scorecard["n_abstentions"] == 240


def test_partial_report_on_midrun_failure():
    # Un errore API a meta run (credito esaurito, rete) non deve buttare via i
    # verdetti raccolti: scorecard parziale, etichettata come tale.
    class ExplodingAgent(ReferenceAgent):
        name = "exploding"

        def __init__(self) -> None:
            self.calls = 0

        def run(self, scenario, sandbox):  # type: ignore[override]
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("credito esaurito (simulato)")
            return super().run(scenario, sandbox)

    verdicts, scorecard = run(TASKS / "A-anagrafiche", ExplodingAgent())
    assert len(verdicts) == 2
    assert scorecard["partial"] is True
    assert scorecard["n_tasks_expected"] == 40
    assert scorecard["n_tasks"] == 2


def test_piva_checksum():
    s = InvoicingSandbox()
    assert s.validate_piva("12345678903") is True   # check digit corretto
    assert s.validate_piva("12345678900") is False  # check digit errato
    assert s.validate_piva("1234567890") is False    # 10 cifre
    assert s.validate_piva("DE123456789") is False   # estero: non validabile
