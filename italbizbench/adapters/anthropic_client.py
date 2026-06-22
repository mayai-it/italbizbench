"""Client LLM per l'API Anthropic (import pigro: non e' richiesto per i test).

Traduce il log di conversazione generico dell'harness nel formato a content-block
dell'API Messages di Anthropic, e ritorna le tool-call del modello.

Uso:
    from italbizbench.adapters.anthropic_client import AnthropicLLMClient
    client = AnthropicLLMClient(model="claude-sonnet-4-6")  # legge ANTHROPIC_API_KEY
"""
from __future__ import annotations

import os
from typing import Any, cast

from .llm import LLMResponse, ToolCall


def _to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converte i messaggi generici dell'harness nel formato Anthropic."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant" and "tool_calls" in m:
            out.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]}
                for tc in m["tool_calls"]
            ]})
        elif role == "assistant":
            out.append({"role": "assistant", "content": m.get("content", "")})
        elif role == "tool":
            out.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": r["tool_call_id"], "content": r["content"]}
                for r in m["content"]
            ]})
    return out


class AnthropicLLMClient:
    def __init__(self, model: str = "claude-sonnet-4-6", max_tokens: int = 1024,
                 api_key: str | None = None):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Installa il pacchetto: pip install anthropic") from e
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self.max_tokens = max_tokens

    def complete(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]]) -> LLMResponse:
        # I dizionari generici dell'harness sono compatibili a runtime con i TypedDict
        # dell'SDK Anthropic; il cast esplicito tiene mypy --strict felice al confine.
        resp = self._client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system,
            tools=cast(Any, tools), messages=cast(Any, _to_anthropic(messages)),
        )
        calls: list[ToolCall] = []
        text = ""
        for block in resp.content:
            if block.type == "tool_use":
                args: dict[str, Any] = dict(block.input) if block.input else {}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=args))
            elif block.type == "text":
                text += block.text
        return LLMResponse(tool_calls=calls, text=text)
