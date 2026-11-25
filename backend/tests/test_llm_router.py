import pytest
from pydantic import BaseModel

from app.llm.router import LLMError, LLMRouter, parse_json
from tests.fakes import fake_router, rate_limit_error


class Person(BaseModel):
    name: str
    age: int


def test_falls_back_on_rate_limit_and_cools_down():
    router, (a, b) = fake_router([rate_limit_error()], ["from b", "again b"])
    assert router.chat([{"role": "user", "content": "hi"}]).content == "from b"
    # provider a is cooling down, so the second call goes straight to b
    res = router.chat([{"role": "user", "content": "hi"}])
    assert res.provider == "p1" and len(a.requests) == 1


def test_all_providers_failing_raises():
    router, _ = fake_router([rate_limit_error()])
    with pytest.raises(LLMError):
        router.chat([{"role": "user", "content": "hi"}])


def test_no_providers():
    with pytest.raises(LLMError):
        LLMRouter(providers=[], record=False).chat([{"role": "user", "content": "x"}])


def test_structured_repairs_invalid_json():
    router, (a,) = fake_router(['{"name": "Ada"}', '```json\n{"name": "Ada", "age": 36}\n```'])
    p = router.structured([{"role": "user", "content": "extract"}], Person, cache=False)
    assert p == Person(name="Ada", age=36)
    assert a.requests[0]["response_format"] == {"type": "json_object"}
    assert "invalid" in a.requests[1]["messages"][-1]["content"]


def test_tool_calls_are_returned_in_openai_format():
    router, _ = fake_router([{"tool_calls": [{"name": "search_jobs", "args": {"query": "ml"}}]}])
    res = router.chat(
        [{"role": "user", "content": "find ml jobs"}],
        tools=[{"type": "function", "function": {"name": "search_jobs"}}],
    )
    assert res.tool_calls[0]["function"]["name"] == "search_jobs"
    assert res.message()["tool_calls"] == res.tool_calls


def test_parse_json_tolerates_prose():
    assert parse_json('Sure! {"a": 1} hope that helps') == {"a": 1}
