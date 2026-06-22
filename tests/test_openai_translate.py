"""Test delle conversioni di formato OpenAI (funzioni pure, niente rete ne SDK)."""
import json

from italbizbench.adapters.openai_client import to_openai_messages, to_openai_tools


def test_tools_conversion_shape():
    tools = [{
        "name": "validate_piva",
        "description": "Valida una P.IVA.",
        "input_schema": {"type": "object", "properties": {"piva": {"type": "string"}}},
    }]
    out = to_openai_tools(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "validate_piva"
    # lo schema Anthropic `input_schema` diventa `parameters` di OpenAI
    assert out[0]["function"]["parameters"]["properties"]["piva"]["type"] == "string"


def test_messages_conversion():
    generic = [
        {"role": "user", "content": "emetti fattura"},
        {"role": "assistant", "tool_calls": [
            {"id": "c1", "name": "emit_invoice", "arguments": {"client": "X"}},
        ]},
        {"role": "tool", "content": [{"tool_call_id": "c1", "content": "{\"ok\": true}"}]},
    ]
    out = to_openai_messages(generic)
    assert out[0] == {"role": "user", "content": "emetti fattura"}
    # le tool call dell'assistant: arguments serializzati come stringa JSON
    tc = out[1]["tool_calls"][0]
    assert tc["id"] == "c1" and tc["type"] == "function"
    assert json.loads(tc["function"]["arguments"]) == {"client": "X"}
    # un messaggio tool per ciascun tool_call_id
    assert out[2] == {"role": "tool", "tool_call_id": "c1", "content": "{\"ok\": true}"}
