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


def test_partial_and_replayed_runs_are_flagged() -> None:
    """Un run interrotto o rigiocato non deve sembrare un run completo e pulito."""
    complete = _fake_report("completo", 0.9)
    partial = _fake_report("interrotto", 0.8)
    assert isinstance(partial["scorecard"], dict)
    partial["scorecard"]["partial"] = True
    partial["scorecard"]["n_tasks_expected"] = 240
    replayed = _fake_report("rigiocato", 0.7)
    assert isinstance(replayed["scorecard"], dict)
    replayed["scorecard"]["replayed"] = 124
    replayed["agent_provenance"] = "dichiarata-da-cli"

    html = build_html([complete, partial, replayed])
    _assert_well_formed(html)
    assert "parziale 80/240" in html
    assert "replay non verificato 124" in html
    # La riga pulita non porta marcatori.
    assert html.count('class="flag"') == 2 + 2 + 2  # 2 in legenda + 2 righe x 2 tabelle


def test_pass_hat_k_column_appears_and_drives_the_ranking() -> None:
    """Su report a trial ripetuti la classifica espone pass^k e ci si ordina:
    mostrare il solo pass-rate medio nasconderebbe l'affidabilita."""
    flaky = _fake_report("incostante", 0.9)   # bravo in media...
    assert isinstance(flaky["scorecard"], dict)
    flaky["scorecard"].update({"trials": 3, "n_scenarios": 40, "pass_hat_k": 0.5,
                               "pass_hat_k_wilson_ci95": [0.35, 0.65]})
    steady = _fake_report("costante", 0.8)    # ...ma meno affidabile di questo
    assert isinstance(steady["scorecard"], dict)
    steady["scorecard"].update({"trials": 3, "n_scenarios": 40, "pass_hat_k": 0.75,
                                "pass_hat_k_wilson_ci95": [0.6, 0.86]})

    html = build_html([flaky, steady])
    _assert_well_formed(html)
    assert "pass^k" in html
    # Ordinati per pass^k, non per pass-rate: 'costante' (0.75) prima di
    # 'incostante' (0.5) anche se quest'ultimo ha il pass-rate medio piu alto.
    assert html.index("costante") < html.index("incostante")
    # Header e righe restano allineati (nessuna colonna orfana).
    head = html.split("<thead><tr>")[1].split("</tr></thead>")[0]
    first_row = html.split("<tbody>")[1].split("</tr>")[0]
    assert head.count('<th scope="col">') == (
        first_row.count("<td") + first_row.count('<th scope="row">'))


def test_pass_hat_k_column_is_absent_without_trials() -> None:
    html = build_html([_fake_report("singolo-trial", 0.9)])
    assert "pass^k" not in html


def test_mixed_trial_reports_are_not_ranked_on_pass_hat_k() -> None:
    """Un run a trial singolo non ha un pass^k: ordinarci sopra lo tratterebbe
    come se valesse zero, spedendo un run completo dietro a chiunque abbia
    ripetuto i trial."""
    single = _fake_report("completo-trial-singolo", 0.9)   # nessun pass^k
    repeated = _fake_report("ripetuto", 0.5)
    assert isinstance(repeated["scorecard"], dict)
    repeated["scorecard"].update({"trials": 3, "n_scenarios": 40,
                                  "pass_hat_k": 0.45,
                                  "pass_hat_k_wilson_ci95": [0.3, 0.6]})

    html = build_html([repeated, single])
    _assert_well_formed(html)
    # Colonna presente (c'e' un report che la ha) ma ordinamento sul pass-rate.
    assert "pass^k" in html
    assert html.index("completo-trial-singolo") < html.index("ripetuto")
    # E la pagina avvisa che le due categorie non sono confrontabili.
    assert "non sono confrontabili" in html


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
