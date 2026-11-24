"""LLM router.

Every supported provider (Groq, Gemini, Cerebras, OpenRouter, Ollama) speaks the
OpenAI chat-completions protocol, so one client type covers all of them. The router:

- tries providers in the configured order, skipping ones without keys
- puts a provider in cooldown after a rate limit (free tiers hit these often) and
  falls through to the next one
- validates structured output against a Pydantic model and asks once for a repair
- caches deterministic calls (extraction, explanations) in Postgres
- logs every call (provider, model, tokens, latency) for the admin dashboard
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.ingest.text import sha

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False

    def message(self) -> dict:
        """The assistant message in OpenAI format, to append to a conversation."""
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


@dataclass
class Provider:
    name: str
    client: Any
    models: dict[str, str]


class LLMRouter:
    def __init__(self, providers: list[Provider] | None = None, record: bool = True):
        self.providers = providers if providers is not None else self._from_settings()
        self._cooldown: dict[str, float] = {}
        self._lock = threading.Lock()
        self.record = record

    @staticmethod
    def _from_settings() -> list[Provider]:
        s = get_settings()
        keys = {
            "groq": s.groq_api_key,
            "gemini": s.gemini_api_key,
            "cerebras": s.cerebras_api_key,
            "openrouter": s.openrouter_api_key,
        }
        out = []
        for name in s.llm_provider_order:
            models = s.llm_models.get(name)
            if not models:
                continue
            if name == "ollama":
                if not s.ollama_base_url:
                    continue
                client = openai.OpenAI(
                    base_url=s.ollama_base_url,
                    api_key="ollama",
                    timeout=s.llm_timeout_s * 3,
                    max_retries=0,
                )
            elif keys.get(name):
                client = openai.OpenAI(
                    base_url=BASE_URLS[name],
                    api_key=keys[name],
                    timeout=s.llm_timeout_s,
                    max_retries=0,
                )
            else:
                continue
            out.append(Provider(name, client, models))
        return out

    # ------------------------------------------------------------ public API
    @property
    def available(self) -> bool:
        return bool(self.providers)

    def chat(
        self,
        messages: list[dict],
        *,
        tier: str = "fast",
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        json_mode: bool = False,
        purpose: str = "misc",
        cache: bool = False,
    ) -> LLMResult:
        if not self.providers:
            raise LLMError(
                "no LLM provider configured (set GROQ_API_KEY, GEMINI_API_KEY, ... in .env)"
            )
        key = (
            sha(
                tier,
                json.dumps(messages, sort_keys=True),
                json.dumps(tools or [], sort_keys=True),
                str(json_mode),
            )
            if cache
            else None
        )
        if key:
            hit = self._cache_get(key)
            if hit is not None:
                self._log(
                    hit.get("provider", ""),
                    hit.get("model", ""),
                    purpose,
                    0,
                    0,
                    0,
                    True,
                    None,
                    cache_hit=True,
                )
                return LLMResult(**{**hit, "cached": True})

        errors = []
        for p in self.providers:
            if self._cooldown.get(p.name, 0) > time.monotonic():
                continue
            model = p.models.get(tier) or p.models.get("fast")
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            started = time.monotonic()
            try:
                resp = p.client.chat.completions.create(**kwargs)
            except openai.RateLimitError as e:
                self._cool(p.name, e)
                errors.append(f"{p.name}: rate limited")
                self._log(p.name, model, purpose, 0, 0, started, False, "rate_limited")
                continue
            except (
                openai.APIConnectionError,
                openai.APITimeoutError,
                openai.InternalServerError,
            ) as e:
                self._cooldown[p.name] = time.monotonic() + 20
                errors.append(f"{p.name}: {type(e).__name__}")
                self._log(p.name, model, purpose, 0, 0, started, False, type(e).__name__)
                continue
            except openai.APIStatusError as e:  # bad request, auth, unsupported feature...
                errors.append(f"{p.name}: HTTP {e.status_code}")
                self._log(
                    p.name,
                    model,
                    purpose,
                    0,
                    0,
                    started,
                    False,
                    f"HTTP {e.status_code}: {str(e)[:200]}",
                )
                if e.status_code in (401, 403):
                    self._cooldown[p.name] = time.monotonic() + 3600
                continue
            choice = resp.choices[0].message
            calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in (choice.tool_calls or [])
            ]
            usage = resp.usage
            result = LLMResult(
                content=choice.content or "",
                tool_calls=calls,
                provider=p.name,
                model=model,
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
            self._log(
                p.name,
                model,
                purpose,
                result.prompt_tokens,
                result.completion_tokens,
                started,
                True,
                None,
            )
            if key and not calls:
                self._cache_put(key, result)
            return result
        raise LLMError("all LLM providers failed: " + "; ".join(errors or ["all in cooldown"]))

    def structured(
        self,
        messages: list[dict],
        schema: type[T],
        *,
        tier: str = "fast",
        purpose: str = "extract",
        cache: bool = True,
        max_tokens: int = 1500,
    ) -> T:
        """Get a response validated against ``schema``; one repair round on failure."""
        system = (
            "Respond with a single JSON object only, no prose, matching this JSON schema:\n"
            + json.dumps(schema.model_json_schema())
        )
        msgs = [{"role": "system", "content": system}, *messages]
        res = self.chat(
            msgs,
            tier=tier,
            json_mode=True,
            purpose=purpose,
            cache=cache,
            temperature=0,
            max_tokens=max_tokens,
        )
        try:
            return schema.model_validate(parse_json(res.content))
        except (ValidationError, ValueError) as e:
            repair = msgs + [
                {"role": "assistant", "content": res.content},
                {
                    "role": "user",
                    "content": f"That was invalid: {str(e)[:800]}. Return corrected JSON only.",
                },
            ]
            res = self.chat(
                repair,
                tier=tier,
                json_mode=True,
                purpose=purpose,
                temperature=0,
                max_tokens=max_tokens,
            )
            return schema.model_validate(parse_json(res.content))

    # ------------------------------------------------------------ internals
    def _cool(self, name: str, err: Exception) -> None:
        wait = 60.0
        resp = getattr(err, "response", None)
        if resp is not None:
            ra = resp.headers.get("retry-after")
            with contextlib.suppress(ValueError):
                wait = max(5.0, min(float(ra), 3600.0)) if ra else wait
        self._cooldown[name] = time.monotonic() + wait
        log.info("provider %s rate limited, cooling down %.0fs", name, wait)

    def _log(self, provider, model, purpose, pt, ct, started, ok, error, cache_hit=False) -> None:
        if not self.record:
            return
        try:
            from app.db import session_scope
            from app.models import LLMCall

            with session_scope() as s:
                s.add(
                    LLMCall(
                        provider=provider,
                        model=model or "",
                        purpose=purpose,
                        prompt_tokens=pt,
                        completion_tokens=ct,
                        latency_ms=int((time.monotonic() - started) * 1000) if started else 0,
                        ok=ok,
                        error=error,
                        cache_hit=cache_hit,
                    )
                )
        except Exception:  # noqa: BLE001 - logging must never break a request
            log.debug("could not record llm call", exc_info=True)

    def _cache_get(self, key: str) -> dict | None:
        if not self.record:
            return None
        try:
            from app.db import session_scope
            from app.models import LLMCache

            with session_scope() as s:
                row = s.get(LLMCache, key)
                return dict(row.response) if row else None
        except Exception:  # noqa: BLE001
            return None

    def _cache_put(self, key: str, res: LLMResult) -> None:
        if not self.record:
            return
        try:
            from sqlalchemy.dialects.postgresql import insert

            from app.db import session_scope
            from app.models import LLMCache

            payload = {"content": res.content, "provider": res.provider, "model": res.model}
            with session_scope() as s:
                s.execute(
                    insert(LLMCache).values(key=key, response=payload).on_conflict_do_nothing()
                )
        except Exception:  # noqa: BLE001
            log.debug("could not write llm cache", exc_info=True)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating code fences and leading prose."""
    t = _FENCE.sub("", text.strip())
    try:
        return json.loads(t)
    except ValueError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise


_router: LLMRouter | None = None


def get_llm() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def set_llm(router: LLMRouter | None) -> None:
    """Swap the router (tests use a scripted fake)."""
    global _router
    _router = router
