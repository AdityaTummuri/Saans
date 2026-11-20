from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types

from app.config import Settings
from app.services.gemini import GenaiBackend, LLMError
from app.services.tools import TOOL_SPECS

SETTINGS = Settings(gemini_timeout_s=0.2, gemini_max_tool_rounds=2, _env_file=None)  # type: ignore[call-arg]


class FakeModels:
    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return await reply()
        return reply


def backend(replies: list[Any]) -> tuple[GenaiBackend, FakeModels]:
    models = FakeModels(replies)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return GenaiBackend(client, types, SETTINGS), models


def text_reply(text: str) -> Any:
    return SimpleNamespace(text=text, function_calls=None, candidates=[])


def call_reply(name: str, args: dict[str, Any]) -> Any:
    content = types.Content(
        role="model", parts=[types.Part.from_function_call(name=name, args=args)]
    )
    return SimpleNamespace(
        text=None,
        function_calls=[SimpleNamespace(name=name, args=args)],
        candidates=[SimpleNamespace(content=content)],
    )


async def test_generate_json_requests_structured_output() -> None:
    be, models = backend([text_reply('{"ok": true}')])
    out = await be.generate_json(model="m", system="sys", prompt="p", schema={"type": "object"})
    assert out == '{"ok": true}'
    config = models.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == {"type": "object"}
    assert config.system_instruction == "sys" and config.max_output_tokens == 1024


async def test_run_tools_executes_calls_then_returns_the_final_text() -> None:
    be, models = backend([call_reply("get_forecast", {"hour": 13}), text_reply("done {{x}}")])
    seen: list[tuple[str, dict[str, Any]]] = []

    def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        seen.append((name, args))
        return {"peak": {"placeholder": "{{t1.peak}}"}}

    out = await be.run_tools(model="m", system="s", prompt="q", tools=TOOL_SPECS, call=call)
    assert out == "done {{x}}" and seen == [("get_forecast", {"hour": 13})]
    config = models.calls[0]["config"]
    assert config.automatic_function_calling.disable is True
    assert {d.name for d in config.tools[0].function_declarations} == {s.name for s in TOOL_SPECS}
    # the tool result was sent back as a function response
    last_user = models.calls[1]["contents"][-1]
    assert last_user.parts[0].function_response.name == "get_forecast"


async def test_run_tools_stops_looping_after_the_round_limit() -> None:
    be, models = backend(
        [call_reply("get_forecast", {}), call_reply("get_forecast", {}), text_reply("final")]
    )
    out = await be.run_tools(
        model="m", system="s", prompt="q", tools=TOOL_SPECS, call=lambda n, a: {"ok": 1}
    )
    assert out == "final"
    assert models.calls[-1]["config"].tools is None  # final call has no tools


async def test_sdk_errors_become_llm_errors_without_details() -> None:
    be, _ = backend([RuntimeError("secret detail: key=abc")])
    with pytest.raises(LLMError) as err:
        await be.generate_json(model="m", system="s", prompt="p", schema={})
    assert "secret" not in str(err.value) and "abc" not in str(err.value)


async def test_timeouts_become_llm_errors() -> None:
    async def slow() -> Any:
        await asyncio.sleep(1)

    be, _ = backend([slow])
    with pytest.raises(LLMError):
        await be.generate_json(model="m", system="s", prompt="p", schema={})
