"""Provenienza dei transcript: un report non deve MAI attribuire a un agente i
risultati prodotti da un altro.

Il difetto storico: `--replay-only` rigioca i transcript di X ma etichetta il
report con l'agente passato da riga di comando (default `reference`), quindi un
run reale finiva in leaderboard sotto il nome sbagliato, con token a zero e costo
non stimabile. Qui si fissa il contratto.
"""
import json
from pathlib import Path

import pytest

from italbizbench.adapters import ReferenceAgent
from italbizbench.runner import RUN_META, read_run_meta, write_run_meta
from italbizbench.runner import main as runner_main

TASK = Path(__file__).resolve().parent.parent / "tasks" / "A-anagrafiche"
TASK_ONE = TASK / "a001-base-piva-valida.yaml"


def _run(argv: list[str]) -> int:
    return runner_main(argv)


def test_run_with_save_records_provenance(tmp_path: Path) -> None:
    """Ogni run con --save lascia un meta.json con l'agente che l'ha prodotto."""
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json"]) == 0
    meta = read_run_meta(tmp_path)
    assert meta is not None
    assert meta["agent"] == ReferenceAgent.name


TRANSCRIPT = [
    {"role": "user", "content": "..."},
    {"role": "assistant", "tool_calls": [
        {"id": "t1", "name": "validate_piva", "arguments": {"piva": "12345678903"}}]},
    {"role": "tool", "content": [{"tool_call_id": "t1", "content": "{}"}]},
    {"role": "assistant", "tool_calls": [
        {"id": "t2", "name": "finish",
         "arguments": {"confidence": 1, "result": {"valid": True}}}]},
]


def _seed_transcripts(save_dir: Path, agent: str | None = None,
                      model: str | None = None) -> None:
    """Cartella di run finta: un transcript e, se richiesto, la sua provenienza."""
    save_dir.mkdir(parents=True, exist_ok=True)
    (save_dir / "A-001-base-piva-valida.json").write_text(
        json.dumps(TRANSCRIPT), encoding="utf-8")
    if agent is not None:
        write_run_meta(save_dir, agent, model)


def test_resume_refuses_a_different_model_of_the_same_vendor(tmp_path: Path) -> None:
    """Rigiocare i transcript di X dichiarando Y e' un errore, non un warning —
    anche quando X e Y sono due modelli dello STESSO vendor."""
    _seed_transcripts(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK_ONE), "--save", str(tmp_path), "--json",
              "--replay-only", "--agent", "anthropic", "--model", "claude-opus-5"])
    assert exc.value.code == 2  # argparse error


def test_unspecified_agent_is_adopted_from_the_marker(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Senza --agent il default NON deve poter ri-etichettare un run: l'etichetta
    viene adottata dal marcatore della cartella.

    E' il difetto che ha mislabellato runs/sonnet-5-v3 come 'reference-rulebased':
    bastava dimenticare --agent perche' valesse il default.
    """
    _seed_transcripts(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json",
                 "--replay-only"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["agent"] == "anthropic:claude-sonnet-5"
    assert report["agent_provenance"] == "transcript-meta"


def test_a_fresh_run_cannot_relabel_someone_elses_transcripts(tmp_path: Path) -> None:
    """Il controllo non vale solo con --resume: un run nuovo sulla cartella di un
    altro agente ne riscriverebbe il marcatore, lasciando i suoi transcript sotto
    il nome sbagliato (e il replay successivo li certificherebbe)."""
    _seed_transcripts(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK_ONE), "--save", str(tmp_path), "--json", "--agent", "reference"])
    assert exc.value.code == 2
    # Il marcatore originale e' intatto.
    meta = read_run_meta(tmp_path)
    assert meta is not None and meta["agent"] == "anthropic:claude-sonnet-5"


def test_replay_does_not_overwrite_the_live_report(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Il report di un run dal vivo e' l'unico artefatto con token e costo reali:
    un replay scrive a fianco, non sopra."""
    _seed_transcripts(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    live = {"agent": "anthropic:claude-sonnet-5",
            "scorecard": {"n_tasks": 1, "tokens_input_total": 5000,
                          "cost_eur_total": 0.42}}
    (tmp_path / "report.json").write_text(json.dumps(live), encoding="utf-8")
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json",
                 "--replay-only"]) == 0
    capsys.readouterr()
    assert json.loads((tmp_path / "report.json").read_text()) == live
    replayed = json.loads((tmp_path / "report-replay.json").read_text())
    assert replayed["scorecard"]["replayed"] == 1


def test_a_trials_run_cannot_share_a_directory_with_a_single_trial_run(
        tmp_path: Path) -> None:
    """Rigiocare (o estendere) con un k diverso mescolerebbe misure incomparabili:
    i transcript .trialN esistono solo per il k originale."""
    _seed_transcripts(tmp_path, "reference-rulebased", None)
    write_run_meta(tmp_path, "reference-rulebased", None, trials=3)
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK_ONE), "--save", str(tmp_path), "--json", "--agent", "reference"])
    assert exc.value.code == 2


@pytest.mark.parametrize("marker", ['{"agent": "anthro', '{"agent": 42}', "[]"])
def test_a_tampered_marker_is_an_error_not_a_legacy_dir(tmp_path: Path,
                                                       marker: str) -> None:
    """Un marcatore troncato/manomesso non equivale a un marcatore assente:
    trattarlo come 'cartella legacy' declasserebbe l'attribuzione in silenzio.

    L'agente e' indicato esplicitamente proprio per escludere l'altra uscita a 2
    (quella di 'cartella legacy senza --agent'): senza questo, il test passerebbe
    anche col difetto presente.
    """
    _seed_transcripts(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    (tmp_path / RUN_META).write_text(marker, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK_ONE), "--save", str(tmp_path), "--json", "--replay-only",
              "--agent", "anthropic", "--model", "claude-sonnet-5"])
    assert exc.value.code == 2


def test_a_marker_does_not_hijack_a_new_live_run(tmp_path: Path) -> None:
    """L'etichetta si adotta dal marcatore solo RIPRENDENDO quella cartella.

    Adottarla anche per un run nuovo dirotterebbe un comando senza --agent — che
    documentiamo come reference rule-based, gratuito — verso l'API a pagamento del
    vendor registrato nella cartella.
    """
    _seed_transcripts(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    # Senza --resume: deve fermarsi per mismatch (reference vs anthropic), non
    # silenziosamente eseguire 240 task a pagamento.
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK_ONE), "--save", str(tmp_path), "--json"])
    assert exc.value.code == 2


def test_a_trials_run_is_protected_even_without_transcripts(tmp_path: Path) -> None:
    """L'agente reference non registra transcript: la cartella ha solo il report,
    che resta un risultato da non sovrascrivere con una misura diversa."""
    assert _run([str(TASK), "--save", str(tmp_path), "--json", "--agent", "reference",
                 "--trials", "3"]) == 0
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK), "--save", str(tmp_path), "--json", "--agent", "reference"])
    assert exc.value.code == 2


def test_task_sources_are_anchored_in_the_marker(tmp_path: Path) -> None:
    """Un run sui pubblici + il set privato e uno sui soli pubblici misurano cose
    diverse: il secondo non deve poter sostituire il primo nella stessa cartella."""
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json",
                 "--agent", "reference"]) == 0
    meta = read_run_meta(tmp_path)
    assert meta is not None and meta["sources"] == [str(TASK_ONE)]
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK), "--save", str(tmp_path), "--json", "--agent", "reference"])
    assert exc.value.code == 2


def test_a_mixed_resume_does_not_report_an_understated_cost(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """In un resume misto token e costo coprono solo i task eseguiti dal vivo: il
    costo torna non stimabile (un costo sottostimato e' un numero sbagliato) e i
    token sono dichiarati come soglia minima."""
    _seed_transcripts(tmp_path, "reference-rulebased", None)
    write_run_meta(tmp_path, "reference-rulebased", None, 1, [str(TASK)])
    assert _run([str(TASK), "--save", str(tmp_path), "--json", "--resume",
                 "--agent", "reference"]) == 0
    s = json.loads(capsys.readouterr().out)["scorecard"]
    assert s["replayed"] == 1
    assert s["tokens_partial"] is True
    assert s["cost_eur_total"] is None


def test_resume_with_the_right_agent_mixes_replay_and_live_execution(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Il caso felice: `--resume` con l'agente coerente rigioca cio' che c'e' ed
    esegue il resto, mantenendo l'etichetta e contando i soli task rigiocati."""
    _seed_transcripts(tmp_path, "reference-rulebased", None)
    assert _run([str(TASK), "--save", str(tmp_path), "--json", "--resume",
                 "--agent", "reference"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["agent"] == "reference-rulebased"
    assert report["scorecard"]["n_tasks"] == 40      # tutta la famiglia A
    assert report["scorecard"]["replayed"] == 1      # uno solo era gia' a disco
    assert report["agent_provenance"] == "transcript-meta"
    # Un resume scrive il report principale: non e' un replay puro.
    assert (tmp_path / "report.json").exists()


def test_a_live_run_declares_provenance_run(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Un run dal vivo attribuisce per costruzione: il valore va comunque dichiarato."""
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["agent_provenance"] == "run"
    assert "replayed" not in report["scorecard"]


def test_replay_with_no_matching_transcript_writes_no_report(tmp_path: Path) -> None:
    """Zero verdetti non e' un report vuoto da pubblicare: e' un errore."""
    write_run_meta(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    (tmp_path / "Z-999-inesistente.json").write_text(
        json.dumps(TRANSCRIPT), encoding="utf-8")
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json",
                 "--replay-only"]) == 1
    assert not (tmp_path / "report-replay.json").exists()


def test_legacy_dir_without_meta_requires_explicit_agent(tmp_path: Path) -> None:
    """Cartella di un harness precedente: l'etichetta va dichiarata, non dedotta."""
    _seed_transcripts(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run([str(TASK_ONE), "--save", str(tmp_path), "--json", "--replay-only"])
    assert exc.value.code == 2


def test_replay_only_is_offline_and_keeps_the_original_label(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--replay-only` e' 100% offline — non costruisce il client del vendor, quindi
    non richiede SDK ne chiave API — e il report porta l'etichetta giusta, dice
    quanti task sono rigiocati e come e' stata stabilita la provenienza."""
    _seed_transcripts(tmp_path, "anthropic:claude-sonnet-5", "claude-sonnet-5")
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json", "--replay-only",
                 "--agent", "anthropic", "--model", "claude-sonnet-5"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["agent"] == "anthropic:claude-sonnet-5"
    assert report["scorecard"]["replayed"] == 1
    assert report["agent_provenance"] == "transcript-meta"
    # Un replay non riconta token ne costo: la scorecard non deve far credere
    # che quel run sia stato gratuito.
    assert report["scorecard"]["tokens_input_total"] == 0


def test_replay_does_not_promote_a_declared_provenance(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Una provenienza soltanto dichiarata non viene promossa a verificata:
    nessun meta.json inventato, e il report lo dice."""
    _seed_transcripts(tmp_path)
    assert _run([str(TASK_ONE), "--save", str(tmp_path), "--json", "--replay-only",
                 "--agent", "anthropic", "--model", "claude-sonnet-5"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["agent"] == "anthropic:claude-sonnet-5"
    assert report["agent_provenance"] == "dichiarata-da-cli"
    assert not (tmp_path / RUN_META).exists()
