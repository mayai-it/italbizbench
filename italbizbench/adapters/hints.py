"""Messaggi d'errore chiari per i problemi di configurazione dei client LLM.

Funzioni pure (testabili senza SDK e senza rete): i client le usano per
trasformare gli errori API criptici in indicazioni operative. Meglio fallire
subito con un messaggio esplicito che degradare in silenzio su un default stantio.
"""
from __future__ import annotations


def model_not_accepted_hint(vendor: str, model: str, env_var: str, error: object) -> str:
    """Messaggio per modello rifiutato dall'API (ID inesistente/ritirato)."""
    return (
        f"Modello '{model}' non accettato dall'API {vendor}. Verifica che l'ID sia "
        f"tra i modelli attuali del vendor e correggilo con --model oppure con la "
        f"variabile d'ambiente {env_var}. Errore API: {error}"
    )


def endpoint_unreachable_hint(vendor: str, base_url: str | None, error: object) -> str:
    """Messaggio per endpoint non raggiungibile (rete, base URL errata, server spento)."""
    dove = base_url or "endpoint di default del vendor"
    return (
        f"API {vendor} non raggiungibile ({dove}). Controlla rete/credenziali e, per i "
        f"modelli locali, che il server sia attivo e --base-url corretto. Errore: {error}"
    )
