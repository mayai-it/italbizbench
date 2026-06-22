"""Agente di riferimento (rule-based).

NON e un agente AI: e una baseline deterministica che serve a (1) provare che l'harness
gira end-to-end e (2) dare un punteggio di riferimento contro cui confrontare gli agenti
veri. Implementa la logica fiscale "corretta" per i casi semplici e si ferma sugli ambigui.

Sostituiscilo con un adapter che parla a un LLM via MCP per testare un agente reale.
"""
from __future__ import annotations

from typing import Any

from ..models import AgentAction, Family, InvoiceLine, Scenario
from ..sandbox import InvoicingSandbox
from .base import AgentAdapter


class ReferenceAgent(AgentAdapter):
    name = "reference-rulebased"

    def run(self, scenario: Scenario, sandbox: InvoicingSandbox) -> AgentAction:
        state = scenario.initial_state

        # Sui task adversarial l'input e ambiguo/sporco: il comportamento corretto e
        # fermarsi e chiedere conferma invece di indovinare.
        if state.get("ambiguous"):
            return AgentAction(asked_for_confirmation=True, confidence=0.3,
                               notes="Dato ambiguo: chiedo conferma prima di agire.")

        # Famiglia A: validazione / lookup anagrafica.
        if scenario.family == Family.A_anagrafiche:
            return self._run_anagrafiche(state, sandbox)

        client = str(state.get("client", ""))
        lines = [InvoiceLine(**ln) for ln in state.get("lines", [])]

        # Determina il regime corretto dalle caratteristiche del cliente/operazione.
        info = sandbox.lookup_client(client) or {}
        if state.get("reverse_charge"):
            regime = "reverse_charge"
        elif info.get("pa"):
            regime = "split_payment"
        elif state.get("esente"):
            regime = "esente"
        else:
            regime = "ordinario"

        sandbox.emit_invoice(client=client, lines=lines, regime=regime)
        return AgentAction(asked_for_confirmation=False, confidence=0.9,
                           notes=f"Emessa fattura regime={regime}.")

    def _run_anagrafiche(self, state: dict[str, Any], sandbox: InvoicingSandbox) -> AgentAction:
        check = state.get("check")
        if check == "piva":
            valid = sandbox.validate_piva(str(state.get("piva", "")))
            return AgentAction(confidence=0.95, result={"valid": valid},
                               notes=f"P.IVA valida={valid}.")
        if check == "codice_destinatario":
            info = sandbox.lookup_client(str(state.get("client", ""))) or {}
            cd = info.get("codice_destinatario")
            return AgentAction(confidence=0.9, result={"codice_destinatario": cd},
                               notes=f"Codice destinatario={cd}.")
        return AgentAction(asked_for_confirmation=True, confidence=0.2,
                           notes="Tipo di controllo non riconosciuto: chiedo conferma.")
