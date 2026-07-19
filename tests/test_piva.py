"""Test dell'helper P.IVA: check digit, validazione e generazione sintetica."""
import random

import pytest

from italbizbench.piva import check_digit, is_valid_piva, random_synthetic_piva, synthetic_piva


def test_check_digit_known_vector():
    # Vettore noto (stesso caso dello smoke test della sandbox): 1234567890 -> 3.
    assert check_digit("1234567890") == 3
    assert synthetic_piva("1234567890") == "12345678903"


def test_check_digit_rejects_bad_input():
    with pytest.raises(ValueError):
        check_digit("123")            # troppo corta
    with pytest.raises(ValueError):
        check_digit("12345678901")    # 11 cifre: attese le prime 10
    with pytest.raises(ValueError):
        check_digit("12345A7890")     # non numerica


def test_is_valid_piva():
    assert is_valid_piva("12345678903") is True
    assert is_valid_piva("12345678900") is False   # check digit errato
    assert is_valid_piva("1234567890") is False    # 10 cifre
    assert is_valid_piva("123456789012") is False  # 12 cifre
    assert is_valid_piva("DE123456789") is False   # prefisso estero
    assert is_valid_piva("") is False


def test_synthetic_piva_always_valid():
    # Qualunque base di 10 cifre produce una P.IVA formalmente valida.
    for base in ["0000000000", "9999999999", "0555666777", "1029384756"]:
        assert is_valid_piva(synthetic_piva(base))


def test_random_synthetic_piva_deterministic_and_valid():
    a = random_synthetic_piva(random.Random(42))
    b = random_synthetic_piva(random.Random(42))
    assert a == b                       # stesso seed -> stessa P.IVA
    rng = random.Random(7)
    for _ in range(100):
        p = random_synthetic_piva(rng)
        assert len(p) == 11 and is_valid_piva(p)
