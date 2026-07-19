"""Test dell'intervallo di Wilson con valori calcolati a mano."""
from italbizbench.scoring import wilson_ci


def test_wilson_8_of_10():
    # Caso classico 8/10 (z=1.96): intervallo (0.490, 0.943).
    assert wilson_ci(8, 10) == (0.49, 0.943)


def test_wilson_extremes_not_degenerate():
    # A differenza del bootstrap percentile, Wilson NON collassa su (p, p)
    # quando la proporzione e 0/n o n/n: e il motivo per cui lo riportiamo.
    assert wilson_ci(20, 20) == (0.839, 1.0)
    assert wilson_ci(0, 20) == (0.0, 0.161)


def test_wilson_empty():
    assert wilson_ci(0, 0) == (0.0, 0.0)


def test_wilson_bounds_clamped():
    lo, hi = wilson_ci(1, 2)
    assert 0.0 <= lo <= hi <= 1.0
