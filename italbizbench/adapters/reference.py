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

        # Famiglia C: ciclo scarto -> correzione -> rinvio, note di credito.
        if scenario.family == Family.C_sdi:
            return self._run_sdi(state, sandbox)

        # Famiglia D: ciclo passivo — leggi la PEC e registra la fattura ricevuta.
        if scenario.family == Family.D_passivo:
            return self._run_passivo(state, sandbox)

        client = str(state.get("client", ""))
        lines = [InvoiceLine(**ln) for ln in state.get("lines", [])]
        regime = self._regime(state, sandbox, client)
        sandbox.emit_invoice(client=client, lines=lines, regime=regime)
        return AgentAction(asked_for_confirmation=False, confidence=0.9,
                           notes=f"Emessa fattura regime={regime}.")

    def _regime(self, state: dict[str, Any], sandbox: InvoicingSandbox, client: str) -> str:
        """Regime corretto dalle caratteristiche del cliente/operazione."""
        info = sandbox.lookup_client(client) or {}
        if state.get("reverse_charge"):
            return "reverse_charge"
        if info.get("pa"):
            return "split_payment"
        if state.get("esente"):
            return "esente"
        return "ordinario"

    def _run_sdi(self, state: dict[str, Any], sandbox: InvoicingSandbox) -> AgentAction:
        client = str(state.get("client", ""))
        action = state.get("action")

        if action == "fix_and_resend":
            # 1) corregge (o censisce, se `new`) l'anagrafica; 2) ritrasmette la fattura.
            fix = dict(state.get("fix", {}))
            is_new = bool(fix.pop("new", False))
            if fix and (is_new or sandbox.update_client(client, **fix) is None):
                sandbox.add_client(client, piva=str(fix.get("piva", "")),
                                   codice_destinatario=str(fix.get("codice_destinatario", "")),
                                   pa=bool(fix.get("pa", False)),
                                   estero=bool(fix.get("estero", False)))
            lines = [InvoiceLine(**ln) for ln in state.get("lines", [])]
            regime = self._regime(state, sandbox, client)
            sandbox.emit_invoice(client=client, lines=lines, regime=regime)
            return AgentAction(asked_for_confirmation=False, confidence=0.9,
                               notes=f"Anagrafica corretta e fattura ritrasmessa ({regime}).")

        if action == "credit_note":
            lines = [InvoiceLine(**ln) for ln in state.get("credit_lines", [])]
            regime = self._regime(state, sandbox, client)
            sandbox.emit_credit_note(client=client, lines=lines, regime=regime,
                                     refers_to=str(state.get("refers_to", "")))
            return AgentAction(asked_for_confirmation=False, confidence=0.9,
                               notes="Nota di credito emessa a storno.")

        return AgentAction(asked_for_confirmation=True, confidence=0.2,
                           notes="Azione SDI non riconosciuta: chiedo conferma.")

    def _run_passivo(self, state: dict[str, Any], sandbox: InvoicingSandbox) -> AgentAction:
        if state.get("action") != "register_purchase":
            return AgentAction(asked_for_confirmation=True, confidence=0.2,
                               notes="Azione sul ciclo passivo non riconosciuta: chiedo conferma.")
        msg = sandbox.read_pec(str(state.get("pec_id", "")))
        if msg is None or msg.invoice is None:
            return AgentAction(asked_for_confirmation=True, confidence=0.2,
                               notes="Messaggio PEC o fattura non trovati: chiedo conferma.")
        doc = msg.invoice
        sandbox.register_purchase(
            fornitore=str(doc["fornitore"]), piva=str(doc["piva"]),
            numero=str(doc["numero"]), imponibile=float(doc["imponibile"]),
            iva=float(doc["iva"]), totale=float(doc["totale"]))
        return AgentAction(asked_for_confirmation=False, confidence=0.9,
                           notes="Fattura passiva registrata dal messaggio PEC.")

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
