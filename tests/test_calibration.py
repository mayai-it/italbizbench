"""Test delle metriche di calibrazione con casi calcolati a mano.

Convenzioni verificate qui:
- Brier = media di (p - y)^2 sulle sole predizioni.
- ECE su 10 bin di uguale ampiezza; l'ultimo bin include 1.0.
- Le astensioni (chiedere conferma senza agire) NON entrano in Brier/ECE:
  finiscono in abstention_accuracy.
"""
from italbizbench.models import (
    AgentAction,
    AxisScores,
    Difficulty,
    Family,
    Oracle,
    Scenario,
    Verdict,
)
from italbizbench.sandbox import InvoicingSandbox
from italbizbench.scoring import (
    aggregate,
    brier_score,
    expected_calibration_error,
    reliability_bins,
    score_task,
)


def _verdict(passed: bool, confidence: float, abstained: bool = False) -> Verdict:
    """Costruisce un Verdict minimale per testare l'aggregazione."""
    corr = 1.0 if passed else 0.0
    brier = None if abstained else round((confidence - corr) ** 2, 4)
    return Verdict(
        scenario_id="X-000", family=Family.B_emissione, difficulty=Difficulty.base,
        passed=passed, tool_calls_used=1, confidence=confidence, abstained=abstained,
        scores=AxisScores(correctness=corr, efficiency=1.0, safety=1.0, brier=brier),
    )


# --- Brier ---------------------------------------------------------------------


def test_brier_hand_computed():
    # ((1-1)^2 + (0-0)^2 + (0.8-1)^2 + (0.6-0)^2) / 4 = (0 + 0 + 0.04 + 0.36) / 4 = 0.1
    preds = [(1.0, 1.0), (0.0, 0.0), (0.8, 1.0), (0.6, 0.0)]
    assert brier_score(preds) == 0.1


def test_brier_empty_pool_is_none():
    assert brier_score([]) is None


# --- ECE e reliability bins ----------------------------------------------------


def test_ece_hand_computed():
    # Bin [0.9,1.0]: p=1.0, acc=1.0 -> gap 0.   Bin [0.0,0.1): p=0.0, acc=0 -> gap 0.
    # Bin [0.8,0.9): p=0.8, acc=1.0 -> gap 0.2 (peso 1/4).
    # Bin [0.6,0.7): p=0.6, acc=0.0 -> gap 0.6 (peso 1/4).
    # ECE = 0.25*0.2 + 0.25*0.6 = 0.2
    preds = [(1.0, 1.0), (0.0, 0.0), (0.8, 1.0), (0.6, 0.0)]
    assert expected_calibration_error(preds) == 0.2


def test_ece_two_adjacent_bins():
    # 0.7 cade nel bin [0.7,0.8): conf 0.7, acc 1.0 -> gap 0.3, peso 1/2.
    # 0.8 cade nel bin [0.8,0.9): conf 0.8, acc 1.0 -> gap 0.2, peso 1/2.
    # ECE = 0.5*0.3 + 0.5*0.2 = 0.25
    preds = [(0.7, 1.0), (0.8, 1.0)]
    assert expected_calibration_error(preds) == 0.25


def test_reliability_bins_structure():
    preds = [(0.95, 1.0), (0.92, 0.0), (0.15, 0.0)]
    bins = reliability_bins(preds)
    assert len(bins) == 10
    # Il bin [0.9, 1.0] contiene le due predizioni alte.
    top = bins[-1]
    assert top["n"] == 2
    assert top["mean_confidence"] == round((0.95 + 0.92) / 2, 4)
    assert top["accuracy"] == 0.5
    # Il bin [0.1, 0.2) contiene la predizione bassa.
    low = bins[1]
    assert low["n"] == 1 and low["accuracy"] == 0.0
    # I bin vuoti restano nell'output con valori None (curva riproducibile).
    assert bins[5]["n"] == 0 and bins[5]["accuracy"] is None


def test_last_bin_includes_one():
    bins = reliability_bins([(1.0, 1.0)])
    assert bins[-1]["n"] == 1


# --- Astensioni ----------------------------------------------------------------


def test_abstentions_excluded_from_brier_and_ece():
    # Un agente che si astiene sempre con confidenza 0 NON deve ottenere
    # calibrazione perfetta: senza predizioni, Brier/ECE sono None, non 0.
    verdicts = [_verdict(True, 0.0, abstained=True) for _ in range(5)]
    card = aggregate(verdicts)
    assert card["brier"] is None
    assert card["ece"] is None
    assert card["n_predictions"] == 0
    assert card["n_abstentions"] == 5
    assert card["abstention_accuracy"] == 1.0


def test_mixed_pool_hand_computed():
    verdicts = [
        _verdict(True, 0.9),                    # brier (0.9-1)^2 = 0.01
        _verdict(False, 0.9),                   # brier (0.9-0)^2 = 0.81
        _verdict(True, 0.0, abstained=True),    # astensione corretta: esclusa
        _verdict(False, 0.5, abstained=True),   # astensione sbagliata: esclusa da Brier
    ]
    card = aggregate(verdicts)
    assert card["n_predictions"] == 2
    assert card["brier"] == round((0.01 + 0.81) / 2, 4)
    # 1 astensione corretta su 2.
    assert card["n_abstentions"] == 2
    assert card["abstention_accuracy"] == 0.5


# --- score_task: chi e una predizione e chi no ---------------------------------


def _scenario(should_ask: bool) -> Scenario:
    return Scenario(
        id="B-TEST", family=Family.B_emissione, difficulty=Difficulty.adversarial,
        title="t", prompt="p", oracle=Oracle(should_ask=should_ask),
    )


def test_score_task_marks_abstention():
    sandbox = InvoicingSandbox()
    action = AgentAction(asked_for_confirmation=True, confidence=0.2)
    v = score_task(_scenario(should_ask=True), sandbox, action)
    assert v.abstained is True
    assert v.scores.brier is None
    assert v.passed is True


def test_score_task_acting_on_ambiguous_is_a_prediction():
    # Chi AGISCE su un task ambiguo non e un'astensione: entra nel pool con esito 0
    # e la sua sovraconfidenza viene punita dal Brier.
    from italbizbench.models import InvoiceLine
    sandbox = InvoicingSandbox()
    sandbox.emit_invoice("Rossi Costruzioni Srl",
                         [InvoiceLine(descrizione="x", prezzo_unitario=100.0)])
    action = AgentAction(asked_for_confirmation=False, confidence=0.95)
    v = score_task(_scenario(should_ask=True), sandbox, action)
    assert v.abstained is False
    assert v.passed is False
    assert v.scores.brier == round((0.95 - 0.0) ** 2, 4)


def test_score_task_clamps_confidence():
    sandbox = InvoicingSandbox()
    sandbox.lookup_client("Rossi Costruzioni Srl")
    action = AgentAction(asked_for_confirmation=False, confidence=1.7,
                         result={"valid": True})
    sc = Scenario(
        id="A-TEST", family=Family.A_anagrafiche, difficulty=Difficulty.base,
        title="t", prompt="p", oracle=Oracle(expected_result={"valid": True}),
    )
    v = score_task(sc, sandbox, action)
    assert v.confidence == 1.0
    assert v.scores.brier == 0.0
