import asyncio
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from bot import llm as llm_module
from bot.config import Config
from bot.llm import LLM, LLMUnavailable


def config() -> Config:
    return Config("tg", "key", "http://llm", "big", ("mid", "small"), "router", "low", None, None, "Europe/Kyiv")


def limited(wait: float) -> RateLimitError:
    request = httpx.Request("POST", "http://llm")
    response = httpx.Response(429, headers={"retry-after": str(wait)}, request=request)
    return RateLimitError("rate limit", response=response, body=None)


def ok(content: str = '{"answer": "так"}'):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeCompletions:
    """For each model, a queue of outcomes: an exception or a ready answer."""

    def __init__(self, script: dict[str, list]):
        self.script = script
        self.calls: list[str] = []

    async def create(self, model: str, **kwargs):
        self.calls.append(model)
        result = self.script[model].pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_llm(script: dict[str, list], monkeypatch) -> tuple[LLM, FakeCompletions]:
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(llm_module.asyncio, "sleep", no_sleep)
    llm = LLM(config())
    fake = FakeCompletions(script)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return llm, fake


def test_model_chains(monkeypatch):
    llm, _ = make_llm({}, monkeypatch)
    assert llm.models == ["big", "mid", "small"]
    # The understanding step does not spend the main model's limit before the fallback models.
    assert llm.router_models == ["router", "small", "mid", "big"]


def test_short_limit_on_main_model_is_waited_out(monkeypatch):
    llm, fake = make_llm({"big": [limited(3), ok()]}, monkeypatch)
    assert asyncio.run(llm.json("s", "u")) == {"answer": "так"}
    assert fake.calls == ["big", "big"]


def test_long_limit_falls_back_to_next_model(monkeypatch):
    llm, fake = make_llm({"big": [limited(40)], "mid": [ok()]}, monkeypatch)
    assert asyncio.run(llm.json("s", "u")) == {"answer": "так"}
    assert fake.calls == ["big", "mid"]


def test_when_all_models_are_limited_waits_for_the_soonest(monkeypatch):
    script = {"big": [limited(25)], "mid": [limited(20)], "small": [limited(28), ok()]}
    script["mid"].append(ok('{"answer": "mid"}'))
    llm, fake = make_llm(script, monkeypatch)
    assert asyncio.run(llm.json("s", "u")) == {"answer": "mid"}
    assert fake.calls == ["big", "mid", "small", "mid"]


def test_gives_up_when_limits_are_too_long(monkeypatch):
    llm, _ = make_llm({"big": [limited(50)], "mid": [limited(45)], "small": [limited(60)]}, monkeypatch)
    with pytest.raises(LLMUnavailable):
        asyncio.run(llm.json("s", "u"))


def test_model_with_long_limit_is_skipped_until_it_resets(monkeypatch):
    llm, fake = make_llm({"big": [limited(1800)], "mid": [ok(), ok()]}, monkeypatch)
    asyncio.run(llm.json("s", "u"))
    asyncio.run(llm.json("s", "u"))
    assert fake.calls == ["big", "mid", "mid"]
