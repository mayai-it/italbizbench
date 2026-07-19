"""Client LLM per API OpenAI-compatibili (import pigro).

Un solo client copre due casi, cambiando solo `base_url`:
- **OpenAI** (GPT): `base_url=None` -> usa api.openai.com, chiave da OPENAI_API_KEY.
- **Modello locale**: Ollama / llama.cpp / vLLM espongono la stessa API. Es. Ollama:
  `base_url="http://localhost:11434/v1"`, `api_key="ollama"` (placeholder).

Le funzioni di conversione sono pure e a livello di modulo, quindi testabili senza il
pacchetto `openai` installato e senza rete.
"""
from __future__ import annotations

import json
import os
from typing import Any

from ..models import UsageStats
from .llm import LLMResponse, ToolCall


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converte lo schema strumenti (stile Anthropic `input_schema`) nel formato OpenAI."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converte il log generico dell'harness nel formato chat di OpenAI."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant" and "tool_calls" in m:
            out.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                    }
                    for tc in m["tool_calls"]
                ],
            })
        elif role == "assistant":
            out.append({"role": "assistant", "content": m.get("content", "")})
        elif role == "tool":
            # OpenAI vuole un messaggio per ciascun tool_call_id.
            for r in m["content"]:
                out.append({"role": "tool", "tool_call_id": r["tool_call_id"],
                            "content": r["content"]})
    return out


def usage_from_response(resp: Any) -> UsageStats | None:
    """Estrae l'usage di token da una risposta chat-completions (None se assente).

    L'API OpenAI usa `prompt_tokens` / `completion_tokens`; alcuni server locali
    compatibili omettono del tutto il campo `usage`. Funzione pura e difensiva:
    testabile con un mock, senza SDK ne rete.
    """
    u = getattr(resp, "usage", None)
    if u is None:
        return None
    return UsageStats(
        input_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(u, "completion_tokens", 0) or 0),
    )


class OpenAIClient:
    def __init__(self, model: str = "gpt-4o", base_url: str | None = None,
                 api_key: str | None = None, max_tokens: int = 1024):
        try:
            import openai  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Installa il pacchetto: pip install openai") from e
        import openai
        key = api_key or os.environ.get("OPENAI_API_KEY") or "not-needed-for-local"
        # Tipizzato Any al confine con l'SDK: tiene mypy --strict felice sia con `openai`
        # installato sia in CI dove non lo e' (ignore_missing_imports).
        self._client: Any = openai.OpenAI(api_key=key, base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> LLMResponse:
        full = [{"role": "system", "content": system}, *to_openai_messages(messages)]
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=full,
            tools=to_openai_tools(tools),
        )
        msg = resp.choices[0].message
        calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            args = json.loads(tc.function.arguments or "{}")
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return LLMResponse(tool_calls=calls, text=msg.content or "",
                           usage=usage_from_response(resp))
