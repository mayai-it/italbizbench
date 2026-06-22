"""Interfaccia agnostica dell'agente.

Per testare un agente nuovo (Claude, GPT, modello locale via MCP) basta implementare
`run(scenario, sandbox)`: l'agente legge il prompt, chiama gli strumenti della sandbox,
e restituisce un AgentAction che dichiara cosa ha fatto e quanto e sicuro.

Per un agente reale, qui dentro si apre la sessione MCP verso `fatture-cli`/`pec-cli`
e si lascia che il modello decida le chiamate. La sandbox registra i tool-call.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import AgentAction, Scenario
from ..sandbox import InvoicingSandbox


class AgentAdapter(ABC):
    name: str = "abstract"

    @abstractmethod
    def run(self, scenario: Scenario, sandbox: InvoicingSandbox) -> AgentAction:
        """Esegue il task agendo sulla sandbox. Ritorna l'azione dichiarata."""
        raise NotImplementedError
