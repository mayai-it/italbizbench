"""Test di pass^k: trial ripetuti, affidabilita separata dalla fortuna del singolo run."""
from pathlib import Path

from italbizbench.adapters import ReferenceAgent
from italbizbench.models import AgentAction, InvoiceLine, Scenario
from italbizbench.runner import run
from italbizbench.sandbox import InvoicingSandbox

TASKS = Path(__file__).resolve().parent.parent / "tasks"
TASK_B001 = TASKS / "B-emissione" / "b001-base-ordinario.yaml"


class FlakyAgent(ReferenceAgent):
    """Sbaglia esattamente un trial su tre: pass@1 alto, pass^3 a zero."""
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, scenario: Scenario, sandbox: InvoicingSandbox) -> AgentAction:
        self.calls += 1
        if self.calls % 3 == 2:  # il secondo trial di ogni terna fallisce
            sandbox.emit_invoice(client=str(scenario.initial_state.get("client", "")),
                                 lines=[InvoiceLine(descrizione="importo errato",
                                                    prezzo_unitario=1.0)])
            return AgentAction(confidence=0.9)
        return super().run(scenario, sandbox)


def test_pass_hat_k_punishes_flakiness():
    verdicts, scorecard = run(TASK_B001, FlakyAgent(), trials=3)
    assert len(verdicts) == 3
    assert [v.passed for v in verdicts] == [True, False, True]
    assert scorecard["pass_rate"] == 0.667  # pass@1 medio sui trial
    assert scorecard["trials"] == 3
    assert scorecard["n_scenarios"] == 1
    assert scorecard["pass_hat_k"] == 0.0   # basta UN trial fallito


def test_stable_agent_pass_hat_k_equals_pass_rate():
    verdicts, scorecard = run(TASK_B001, ReferenceAgent(), trials=3)
    assert scorecard["pass_rate"] == 1.0
    assert scorecard["pass_hat_k"] == 1.0


def test_single_trial_has_no_pass_hat_k():
    _, scorecard = run(TASK_B001, ReferenceAgent())
    assert "pass_hat_k" not in scorecard


def test_trials_incompatible_with_resume(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        run(TASK_B001, ReferenceAgent(), save_dir=tmp_path, resume=True, trials=2)
