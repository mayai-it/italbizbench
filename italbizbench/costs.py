"""Tabella costi per modello e calcolo del costo (in euro) di un run.

I prezzi vivono in un file YAML configurabile (default: ``costs.yaml`` alla radice
del repo) cosi si aggiornano senza toccare il codice: i listini cambiano spesso.
Formato:

    currency: EUR
    models:
      nome-modello: {input_per_mtok: 2.80, output_per_mtok: 14.00}

I prezzi sono per **1 milione di token**. Un modello assente dalla tabella produce
``cost_eur=None`` ("costo non stimabile"), mai un prezzo inventato in silenzio.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import UsageStats

# Percorso di default: costs.yaml alla radice del repository.
DEFAULT_COSTS_PATH = Path(__file__).resolve().parent.parent / "costs.yaml"


class ModelCost(BaseModel):
    """Prezzo di un modello, per milione di token."""
    input_per_mtok: float
    output_per_mtok: float


class CostTable(BaseModel):
    """Tabella prezzi caricata da YAML. Vuota = nessun costo stimabile."""
    currency: str = "EUR"
    models: dict[str, ModelCost] = Field(default_factory=dict)


def load_cost_table(path: Path | None = None) -> CostTable:
    """Carica la tabella costi; se il file non esiste ritorna una tabella vuota."""
    p = path if path is not None else DEFAULT_COSTS_PATH
    if not p.exists():
        return CostTable()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return CostTable(**data)


def compute_cost_eur(
    usage: UsageStats, model: str | None, table: CostTable
) -> float | None:
    """Costo in euro del run dato l'usage e il modello; None se il prezzo non e noto."""
    if model is None:
        return None
    mc = table.models.get(model)
    if mc is None:
        return None
    cost = (usage.input_tokens * mc.input_per_mtok
            + usage.output_tokens * mc.output_per_mtok) / 1_000_000
    return round(cost, 6)
