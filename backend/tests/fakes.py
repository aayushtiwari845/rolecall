"""Test doubles for the OpenAI-compatible client used by the LLM router."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import openai

from app.llm.router import LLMRouter, Provider


def _resp(content: str = "", tool_calls: list[dict] | None = None):
    calls = [
        SimpleNamespace(id=tc.get("id", f"call_{i}"), function=SimpleNamespace(name=tc["name"], arguments=json.dumps(tc.get("args", {}))))
        for i, tc in enumerate(tool_calls or [])
    ]
    msg = SimpleNamespace(content=content, tool_calls=calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))


class ScriptedClient:
    """Returns scripted responses in order. An Exception instance in the script is raised."""

    def __init__(self, script: list):
        self.script = list(script)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.script:
            raise AssertionError("scripted client ran out of responses")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return _resp(item.get("content", ""), item.get("tool_calls"))
        return _resp(item)


def rate_limit_error() -> openai.RateLimitError:
    req = httpx.Request("POST", "https://x/chat/completions")
    return openai.RateLimitError("rate limited", response=httpx.Response(429, request=req, headers={"retry-after": "30"}), body=None)


def fake_router(*scripts: list) -> tuple[LLMRouter, list[ScriptedClient]]:
    clients = [ScriptedClient(s) for s in scripts]
    providers = [Provider(f"p{i}", c, {"fast": f"m{i}", "smart": f"m{i}-smart"}) for i, c in enumerate(clients)]
    return LLMRouter(providers=providers, record=False), clients
