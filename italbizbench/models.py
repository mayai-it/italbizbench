"""Modelli dati del benchmark.

Uno *scenario* descrive un task: stato iniziale della sandbox, l'istruzione data
all'agente, e l'oracolo (verita di riferimento) con cui il verifier giudica l'esito.
Tutto deve essere deterministicamente verificabile: niente giudizi soggettivi.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Difficulty(StrEnum):
    base = "base"            # caso pulito
    tricky = "tricky"        # eccezione fiscale (reverse charge, split payment, bollo...)
    adversarial = "adversarial"  # dato sporco/ambiguo: l'agente DOVREBBE fermarsi e chiedere


class Family(StrEnum):
    A_anagrafiche = "A-anagrafiche"
    B_emissione = "B-emissione"
    C_sdi = "C-sdi"
    D_passivo = "D-passivo"
    E_riconciliazione = "E-riconciliazione"
    F_orchestrazione = "F-orchestrazione"


class InvoiceLine(BaseModel):
    """Riga di fattura. Importi in euro, IVA come aliquota percentuale (es. 22.0)."""
    descrizione: str
    quantita: float = 1.0
    prezzo_unitario: float
    aliquota_iva: float = 22.0
    natura: str | None = None  # es. N6.1 reverse charge, N4 esente art.10


class Oracle(BaseModel):
    """Verita di riferimento per la verifica deterministica.

    Per i task `adversarial` l'esito atteso puo essere `should_ask=True`: l'agente
    corretto NON agisce, chiede conferma. Indovinare = fallire la sicurezza.
    """
    should_ask: bool = False
    expected_imponibile: float | None = None
    expected_iva: float | None = None
    expected_totale: float | None = None
    expected_regime: str | None = None       # es. "reverse_charge", "split_payment", "ordinario"
    expected_sdi_outcome: str | None = None   # "accettata" | "scarto:<codice>"
    expected_result: dict[str, Any] | None = None  # famiglia A: risposta strutturata attesa
    # Famiglia C (gestione scarti SDI):
    # - expected_client_update: {"client": nome, campo: valore, ...} — l'anagrafica deve
    #   risultare corretta cosi a fine task (es. codice destinatario sistemato).
    # - expected_credit_note: {"client": ..., "imponibile": ..., "iva": ..., "totale": ...,
    #   ["sdi_outcome": ...]} — l'ultima nota di credito emessa deve combaciare.
    expected_client_update: dict[str, Any] | None = None
    expected_credit_note: dict[str, Any] | None = None
    tolerance: float = 0.01                   # tolleranza sugli importi (arrotondamenti)


class Scenario(BaseModel):
    id: str
    family: Family
    difficulty: Difficulty
    title: str
    prompt: str                               # istruzione in linguaggio naturale all'agente
    initial_state: dict[str, Any] = Field(default_factory=dict)  # seed sandbox (clienti, ecc.)
    oracle: Oracle
    max_tool_calls: int = 10


class AgentAction(BaseModel):
    """Azione dichiarata dall'agente al termine del task."""
    asked_for_confirmation: bool = False
    confidence: float = 0.5                   # 0..1, autovalutazione per la calibrazione
    result: dict[str, Any] = Field(default_factory=dict)  # famiglia A: risposta strutturata
    notes: str = ""


class UsageStats(BaseModel):
    """Consumo di risorse di un run: token e costo in euro.

    Il costo e calcolato dalla tabella prezzi configurabile (``costs.yaml``);
    ``cost_eur=None`` significa "modello non in tabella, costo non stimabile".
    Il reference agent (rule-based, zero token) resta valido a costo 0.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cost_eur: float | None = None


class AxisScores(BaseModel):
    correctness: float                        # 0..1
    efficiency: float                         # 0..1 (1 = nessun giro a vuoto)
    safety: float                             # 0..1
    # Contributo Brier del task: (confidenza - esito)^2, piu basso e meglio.
    # None quando il task e un'astensione (nessuna predizione da calibrare):
    # le astensioni sono valutate a parte con abstention_accuracy, NON come
    # predizioni a confidenza 0 — altrimenti "non fare nulla" varrebbe
    # calibrazione perfetta.
    brier: float | None


class Verdict(BaseModel):
    scenario_id: str
    family: Family
    difficulty: Difficulty
    passed: bool
    tool_calls_used: int
    confidence: float                         # confidenza dichiarata, clampata in [0, 1]
    abstained: bool                           # ha chiesto conferma SENZA agire
    scores: AxisScores
    usage: UsageStats | None = None           # token/costo del run (None = non tracciato)
    detail: str = ""
