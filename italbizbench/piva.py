"""P.IVA sintetiche: check digit e generazione deterministica.

Unica fonte di verita per l'algoritmo del codice di controllo della partita IVA
italiana (variante di Luhn, vedi docs/FISCAL-RULES.md §1): usato sia dalla sandbox
per la validazione, sia per GENERARE P.IVA fittizie ma formalmente valide per i
task del benchmark. Regola d'oro: mai P.IVA di aziende reali — qui si parte da
basi arbitrarie o da un RNG seedato, non da anagrafi pubblici.
"""
from __future__ import annotations

import random


def check_digit(base10: str) -> int:
    """Check digit (11a cifra) per le prime 10 cifre di una P.IVA italiana.

    Somma delle cifre in posizione dispari (1a, 3a, ...) + cifre in posizione
    pari raddoppiate con riporto (se >9 si sottrae 9); check = (10 - somma%10) % 10.
    """
    if not (base10.isdigit() and len(base10) == 10):
        raise ValueError(f"attese esattamente 10 cifre, ricevuto {base10!r}")
    s = 0
    for i, ch in enumerate(base10):
        d = int(ch)
        if i % 2 == 1:  # posizioni pari (1-indexed): raddoppia con riporto
            d *= 2
            if d > 9:
                d -= 9
        s += d
    return (10 - (s % 10)) % 10


def is_valid_piva(piva: str) -> bool:
    """True se la stringa e una P.IVA italiana formalmente valida (11 cifre + check).

    Le P.IVA con prefisso non numerico (es. 'DE...') non seguono questo algoritmo:
    non validabili con questo metodo -> False.
    """
    if not (piva.isdigit() and len(piva) == 11):
        return False
    return check_digit(piva[:10]) == int(piva[10])


def synthetic_piva(base10: str) -> str:
    """P.IVA sintetica valida a partire da 10 cifre arbitrarie (aggiunge il check)."""
    return base10 + str(check_digit(base10))


def random_synthetic_piva(rng: random.Random) -> str:
    """P.IVA sintetica valida da un RNG seedato (deterministica a parita di seed)."""
    base10 = "".join(str(rng.randrange(10)) for _ in range(10))
    return synthetic_piva(base10)
