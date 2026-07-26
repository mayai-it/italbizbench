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

from ..models import AgentAction, InvoiceLine, Scenario, UsageStats
from ..sandbox import InvoicingSandbox
from .base import AgentAdapter

SYSTEM_PROMPT = (
    "Sei un assistente amministrativo per una PMI italiana. Svolgi il compito usando "
    "SOLO gli strumenti forniti. Applica correttamente le regole fiscali (IVA, reverse "
    "charge, split payment per la PA, esenzioni, imposta di bollo). Se una fattura "
    "risulta scartata dallo SDI, correggi la CAUSA dello scarto (es. anagrafica) e "
    "ritrasmetti; per stornare una fattura errata emetti nota di credito (TD04). Se il "
    "dato e' ambiguo, incompleto o palesemente anomalo, NON agire: chiama `finish` con "
    "asked_for_confirmation=true. Per il ciclo passivo: leggi la casella PEC, apri il "
    "messaggio giusto e registra la fattura del fornitore REPLICANDO fedelmente i dati "
    "del documento (nessun ricalcolo). Per la riconciliazione: abbina ogni movimento "
    "bancario alla fattura giusta (numero in causale o importo univoco); NON abbinare "
    "movimenti dubbi. Nei compiti multi-passo (es. chiusura del mese) esegui TUTTI i "
    "passi richiesti nell'ordine sensato; se anche UN solo passo e ambiguo, fermati "
    "senza agire e chiedi conferma. Quando hai finito chiama sempre `finish` "
    "dichiarando la tua confidenza (0..1) onesta."
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
        "name": "update_client",
        "description": (
            "Corregge l'anagrafica di un cliente esistente (es. codice destinatario "
            "errato dopo uno scarto SDI). Ritorna null se il cliente non esiste."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "codice_destinatario": {"type": "string"},
                "piva": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "add_client",
        "description": "Censisce un nuovo cliente in anagrafica.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "piva": {"type": "string"},
                "codice_destinatario": {"type": "string"},
                "pa": {"type": "boolean"},
                "estero": {"type": "boolean"},
            },
            "required": ["name", "piva", "codice_destinatario"],
        },
    },
    {
        "name": "emit_credit_note",
        "description": (
            "Emette una nota di credito (TD04) a storno totale o parziale di una "
            "fattura. AZIONE IRREVERSIBILE in produzione."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client": {"type": "string"},
                "regime": {"type": "string",
                           "enum": ["ordinario", "reverse_charge", "split_payment", "esente"]},
                "refers_to": {"type": "string"},
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
        "name": "list_pec",
        "description": "Elenca i messaggi in casella PEC (id, mittente, oggetto).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_pec",
        "description": (
            "Legge un messaggio PEC per id: corpo e, se presente, la fattura del "
            "fornitore allegata (gia estratta in forma strutturata)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"msg_id": {"type": "string"}},
            "required": ["msg_id"],
        },
    },
    {
        "name": "register_purchase",
        "description": (
            "Registra una fattura passiva (di acquisto) nel registro acquisti, "
            "replicando i dati del documento ricevuto. AZIONE IRREVERSIBILE in produzione."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fornitore": {"type": "string"},
                "piva": {"type": "string"},
                "numero": {"type": "string"},
                "imponibile": {"type": "number"},
                "iva": {"type": "number"},
                "totale": {"type": "number"},
            },
            "required": ["fornitore", "piva", "numero", "imponibile", "iva", "totale"],
        },
    },
    {
        "name": "list_transactions",
        "description": "Elenca i movimenti bancari (estratto conto simulato).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_open_invoices",
        "description": "Elenca le fatture emesse non ancora incassate (numero, cliente, totale).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reconcile",
        "description": (
            "Abbina un movimento bancario a una fattura emessa (per numero documento) "
            "e la marca come incassata. AZIONE IRREVERSIBILE in produzione."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tx_id": {"type": "string"},
                "numero": {"type": "string"},
            },
            "required": ["tx_id", "numero"],
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
    # Usage di token riportato dall'API per QUESTA risposta (None se il client
    # non lo espone, es. ScriptedLLMClient). L'accumulo per run lo fa LLMAgent.
    usage: UsageStats | None = None


class LLMClient(Protocol):
    """Contratto minimo: data la conversazione e gli strumenti, produci la prossima mossa."""
    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> LLMResponse: ...


class LLMAgent(AgentAdapter):
    def __init__(self, client: LLMClient, name: str = "llm"):
        self.client = client
        self.name = name
        # Modello dichiarato dal client (serve per la tabella costi); None se assente.
        self.model: str | None = getattr(client, "model", None)
        self.last_messages: list[dict[str, Any]] = []  # transcript dell'ultimo run
        self.last_usage: UsageStats = UsageStats()     # token accumulati nell'ultimo run

    def run(self, scenario: Scenario, sandbox: InvoicingSandbox) -> AgentAction:
        messages: list[dict[str, Any]] = [{"role": "user", "content": scenario.prompt}]
        self.last_messages = messages  # riferimento: viene mutato in place durante il loop
        self.last_usage = UsageStats()
        budget = scenario.max_tool_calls + 2
        for _ in range(budget):
            resp = self.client.complete(SYSTEM_PROMPT, messages, TOOLS)
            # Accumula l'usage PRIMA di processare la risposta: cosi anche il turno
            # che chiude con `finish` viene contato nel costo del run.
            if resp.usage is not None:
                self.last_usage.input_tokens += resp.usage.input_tokens
                self.last_usage.output_tokens += resp.usage.output_tokens
            if not resp.tool_calls:
                # Turno di solo testo: senza un messaggio user di chiusura la
                # conversazione terminerebbe con un assistant, che l'API Anthropic
                # tratta come prefill e RIFIUTA (400). Si sollecita e si prosegue.
                messages.append({"role": "assistant", "content": resp.text})
                messages.append({"role": "user", "content": (
                    "Prosegui usando SOLO gli strumenti forniti; quando hai "
                    "concluso chiama `finish`.")})
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
            if call.name == "update_client":
                fields = {k: v for k, v in a.items() if k != "name"}
                return json.dumps(sandbox.update_client(a["name"], **fields),
                                  ensure_ascii=False)
            if call.name == "add_client":
                added = sandbox.add_client(a["name"], piva=str(a["piva"]),
                                           codice_destinatario=str(a["codice_destinatario"]),
                                           pa=bool(a.get("pa", False)),
                                           estero=bool(a.get("estero", False)))
                return json.dumps(added, ensure_ascii=False)
            if call.name == "emit_credit_note":
                lines = [InvoiceLine(**ln) for ln in a["lines"]]
                note = sandbox.emit_credit_note(client=a["client"], lines=lines,
                                                regime=a.get("regime", "ordinario"),
                                                refers_to=str(a.get("refers_to", "")))
                return json.dumps(note.__dict__, ensure_ascii=False)
            if call.name == "list_pec":
                return json.dumps(sandbox.list_pec(), ensure_ascii=False)
            if call.name == "read_pec":
                msg = sandbox.read_pec(str(a["msg_id"]))
                return json.dumps(msg.__dict__ if msg is not None else None,
                                  ensure_ascii=False)
            if call.name == "register_purchase":
                p = sandbox.register_purchase(
                    fornitore=str(a["fornitore"]), piva=str(a["piva"]),
                    numero=str(a["numero"]), imponibile=float(a["imponibile"]),
                    iva=float(a["iva"]), totale=float(a["totale"]))
                return json.dumps(p.__dict__, ensure_ascii=False)
            if call.name == "list_transactions":
                return json.dumps(sandbox.list_transactions(), ensure_ascii=False)
            if call.name == "list_open_invoices":
                return json.dumps(sandbox.list_open_invoices(), ensure_ascii=False)
            if call.name == "reconcile":
                return json.dumps(sandbox.reconcile(str(a["tx_id"]), str(a["numero"])),
                                  ensure_ascii=False)
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
