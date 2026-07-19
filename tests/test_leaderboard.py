"""Test del generatore di leaderboard: HTML valido, self-contained, deterministico."""
import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from italbizbench.adapters import ReferenceAgent
from italbizbench.leaderboard import build_html, load_report, main
from italbizbench.runner import main as runner_main

TASKS = Path(__file__).resolve().parent.parent / "tasks"


class _Checker(HTMLParser):
    """Verifica il bilanciamento dei tag (abbastanza per dire 'HTML ben formato')."""

    VOID = {"meta", "br", "img", "hr", "input", "link", "line", "circle", "path"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"tag chiuso fuori ordine: {tag} (stack: {self.stack[-3:]})")
        else:
            self.stack.pop()


def _assert_well_formed(html: str) -> None:
    checker = _Checker()
    checker.feed(html)
    checker.close()
    assert not checker.errors, checker.errors
    assert not checker.stack, f"tag mai chiusi: {checker.stack}"


def _fake_report(agent: str, pass_rate: float) -> dict[str, object]:
    """Report sintetico con la stessa forma dell'output --json del runner."""
    bins: list[dict[str, object]] = [
        {"lo": i / 10, "hi": (i + 1) / 10, "n": 0, "mean_confidence": None, "accuracy": None}
        for i in range(10)
    ]
    bins[8] = {"lo": 0.8, "hi": 0.9, "n": 12, "mean_confidence": 0.85, "accuracy": 0.75}
    bins[9] = {"lo": 0.9, "hi": 1.0, "n": 30, "mean_confidence": 0.95, "accuracy": 0.9}
    return {
        "agent": agent,
        "scorecard": {
            "n_tasks": 80, "pass_rate": pass_rate,
            "correctness_ci95": [pass_rate - 0.08, pass_rate + 0.06],
            "correctness_wilson_ci95": [pass_rate - 0.09, pass_rate + 0.05],
            "efficiency_mean": 0.9, "safety_mean": 0.95,
            "tokens_input_total": 120000, "tokens_output_total": 15000,
            "cost_eur_total": 0.55, "brier": 0.08, "ece": 0.11,
            "reliability_bins": bins, "n_predictions": 42, "n_abstentions": 8,
            "abstention_accuracy": 0.875,
            "by_difficulty": {"adversarial": 0.7, "base": 0.95, "tricky": 0.8},
        },
        "verdicts": [],
    }


def test_build_html_well_formed_and_complete() -> None:
    html = build_html([_fake_report("agente-b", 0.75), _fake_report("agente-a", 0.85)])
    _assert_well_formed(html)
    assert html.startswith("<!DOCTYPE html>")
    assert "agente-a" in html and "agente-b" in html
    # Un grafico reliability per agente.
    assert html.count("<svg") == 2
    # Ordinati per pass-rate decrescente: agente-a prima di agente-b.
    assert html.index("agente-a") < html.index("agente-b")
    # Breakdown per difficolta presente.
    assert "adversarial" in html and "tricky" in html


def test_build_html_is_deterministic() -> None:
    reports = [_fake_report("x", 0.8), _fake_report("y", 0.6)]
    assert build_html(reports) == build_html(reports)


def test_build_html_is_self_contained() -> None:
    html = build_html([_fake_report("solo", 0.9)])
    # Nessuna risorsa esterna a runtime: niente script, niente CSS/font remoti.
    assert "<script" not in html
    assert "<link" not in html
    assert "@import" not in html and "url(" not in html


def test_build_html_handles_missing_values() -> None:
    report = _fake_report("senza-costi", 0.5)
    scorecard = report["scorecard"]
    assert isinstance(scorecard, dict)
    scorecard["cost_eur_total"] = None
    scorecard["brier"] = None
    scorecard["ece"] = None
    scorecard["abstention_accuracy"] = None
    html = build_html([report])
    _assert_well_formed(html)
    assert "—" in html  # i dati mancanti sono resi come em dash, non 'None'
    assert "None" not in html


def test_load_report_rejects_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_report(bad)


def test_end_to_end_runner_to_leaderboard(tmp_path: Path,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    # runner --json --save produce report.json; la leaderboard lo legge e genera l'HTML.
    save_dir = tmp_path / "runs" / "reference"
    rc = runner_main([str(TASKS / "A-anagrafiche"), "--json", "--save", str(save_dir)])
    assert rc == 0
    capsys.readouterr()  # scarta lo stdout del runner
    report_path = save_dir / "report.json"
    assert report_path.exists()
    report = load_report(report_path)
    assert report["agent"] == ReferenceAgent.name

    out = tmp_path / "board.html"
    rc = main([str(report_path), "-o", str(out), "--title", "Test board"])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    _assert_well_formed(html)
    assert "Test board" in html and ReferenceAgent.name in html
