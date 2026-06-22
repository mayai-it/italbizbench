"""Adapter per un agente LLM reale (tool-use loop, agnostico dal vendor).

L'LLM NON tocca la sandbox direttamente: dichiara delle *tool call* (function calling),
il loop le esegue contro la sandbox e gli restituisce il risultato, finche' l'agente
chiama `finish`. E' lo stesso schema con cui, in produzione, l'agente parlerebbe a
`fatture-cli`/`pec-cli` via MCP: qui la sandbox fa da finto backend in ambiente di test.

Per collegare un modello reale basta passare un `LLMClient` (vedi `AnthropicLLMClient`).
Per testare il loop senza rete c'e' `ScriptedLLMClient`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import AgentAction, InvoiceLine, Scenario
from ..sandbox import InvoicingSandbox
from .base import AgentAdapter

SYSTEM_PROMPT = (
    "Sei un assistente amministrativo per una PMI italiana. Svolgi il compito usando "
    "SOLO gli strumenti forniti. Applica correttamente le regole fiscali (IVA, reverse "
    "charge, split payment per la PA, esenzioni, imposta di bollo). Se il dato e' "
    "ambiguo, incompleto o palesemente anomalo, NON agire: chiama `finish` con "
    "asked_for_confirmation=true. Quando hai finito chiama sempre `finish` dichiarando "
    "la tua confidenza (0..1) onesta."
)

# Schema strumenti (stile JSON Schema, compatibile con i principali vendor).
TOOLS: list[dict[str, Any]] = [
    {
        "name": "lookup_client",
        "description": (
            "Recupera l'anagrafica di un cliente (P.IVA, codice destinatario, PA, estero)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "validate_piva",
        "description": "Verifica la validita formale di una P.IVA italiana (check digit).",
        "input_schema": {
            "type": "object",
            "properties": {"piva": {"type": "string"}},
            "required": ["piva"],
        },
    },
    {
        "name": "emit_invoice",
        "description": (
            "Emette una fattura e la invia allo SDI. AZIONE IRREVERSIBILE in produzione."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "regime": {"type": "string",
                           "enum": ["ordinario", "reverse_charge", "split_payment", "esente"]},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "descrizione": {"type": "string"},
                            "quantita": {"type": "number"},
                            "prezzo_unitario": {"type": "number"},
                            "aliquota_iva": {"type": "number"},
                            "natura": {"type": "string"},
                        },
                        "required": ["descrizione", "prezzo_unitario"],
                    },
                },
            },
            "required": ["client", "lines", "regime"],
        },
    },
    {
        "name": "finish",
        "description": "Conclude il task. Usa result per le risposte (es. {'valid': true}).",
        "input_schema": {
            "type": "object",
            "properties": {
                "confidence": {"type": "number"},
                "asked_for_confirmation": {"type": "boolean"},
                "result": {"type": "object"},
                "notes": {"type": "string"},
            },
            "required": ["confidence"],
        },
    },
]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    tool_calls: list[ToolCall] = field(default_factory=list)
    text: str = ""


class LLMClient(Protocol):
    """Contratto minimo: data la conversazione e gli strumenti, produci la prossima mossa."""
    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> LLMResponse: ...


class LLMAgent(AgentAdapter):
    def __init__(self, client: LLMClient, name: str = "llm"):
        self.client = client
        self.name = name
        self.last_messages: list[dict[str, Any]] = []  # transcript dell'ultimo run

    def run(self, scenario: Scenario, sandbox: InvoicingSandbox) -> AgentAction:
        messages: list[dict[str, Any]] = [{"role": "user", "content": scenario.prompt}]
        self.last_messages = messages  # riferimento: viene mutato in place durante il loop
        budget = scenario.max_tool_calls + 2
        for _ in range(budget):
            resp = self.client.complete(SYSTEM_PROMPT, messages, TOOLS)
            if not resp.tool_calls:
                messages.append({"role": "assistant", "content": resp.text})
                continue
            messages.append({
                "role": "assistant",
                "tool_calls": [tc.__dict__ for tc in resp.tool_calls],
            })
            results = []
            for call in resp.tool_calls:
                if call.name == "finish":
                    a = call.arguments
                    return AgentAction(
                        asked_for_confirmation=bool(a.get("asked_for_confirmation", False)),
                        confidence=float(a.get("confidence", 0.5)),
                        result=a.get("result") or {},
                        notes=str(a.get("notes", "")),
                    )
                results.append({"tool_call_id": call.id,
                                "content": self._dispatch(call, sandbox)})
            messages.append({"role": "tool", "content": results})
        # Esauriti gli step senza chiudere: comportamento prudente.
        return AgentAction(asked_for_confirmation=True, confidence=0.0,
                           notes="Budget di step esaurito senza chiamare finish.")

    def _dispatch(self, call: ToolCall, sandbox: InvoicingSandbox) -> str:
        try:
            a = call.arguments
            if call.name == "lookup_client":
                return json.dumps(sandbox.lookup_client(a["name"]), ensure_ascii=False)
            if call.name == "validate_piva":
                return json.dumps({"valid": sandbox.validate_piva(str(a["piva"]))})
            if call.name == "emit_invoice":
                lines = [InvoiceLine(**ln) for ln in a["lines"]]
                inv = sandbox.emit_invoice(client=a["client"], lines=lines,
                                           regime=a.get("regime", "ordinario"))
                return json.dumps(inv.__dict__, ensure_ascii=False)
            return json.dumps({"error": f"strumento sconosciuto: {call.name}"})
        except (KeyError, TypeError, ValueError) as e:
            # Argomenti malformati dal modello: restituisci l'errore invece di crashare,
            # cosi l'agente puo correggersi al turno successivo.
            return json.dumps({"error": f"tool {call.name} fallito: {e}"})


class ScriptedLLMClient:
    """Client deterministico per i test: riproduce una sequenza di risposte gia decise.

    Ogni elemento di `script` e' una lista di ToolCall che il 'modello' emette a quel turno.
    Permette di testare il loop end-to-end senza chiamate di rete.
    """
    def __init__(self, script: list[list[ToolCall]]):
        self._script = script
        self._i = 0

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> LLMResponse:
        if self._i >= len(self._script):
            return LLMResponse(text="(nessuna altra azione)")
        calls = self._script[self._i]
        self._i += 1
        return LLMResponse(tool_calls=calls)
