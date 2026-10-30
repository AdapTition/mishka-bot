"""LLM client (OpenAI-compatible API: Groq by default, Ollama via LLM_BASE_URL)."""

import asyncio
import json
import logging
import time

from openai import APIError, AsyncOpenAI, RateLimitError

from .config import Config

log = logging.getLogger(__name__)

# How long to wait on the first model's rate limit before switching to a fallback. Groq limits are tokens per minute,
# so they often free up within seconds, while the fallback model answers worse.
MAX_WAIT = 12.0
# How long to wait when every model is rate-limited.
MAX_LAST_WAIT = 30.0


class LLMUnavailable(Exception):
    pass


def retry_after(exc: RateLimitError) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after", ""))
    except ValueError:
        return None


class LLM:
    def __init__(self, cfg: Config):
        # Retries on rate limits are done here: the SDK would wait retry-after up to 60 s instead of moving to a fallback model.
        self.client = AsyncOpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url, max_retries=0, timeout=60)
        self.models = list(dict.fromkeys(m for m in (cfg.llm_model, *cfg.llm_fallback_models) if m))
        # The understanding step runs on a separate (lighter) model: Groq counts limits per model.
        # Its fallbacks go in reverse order so the main model's limit, needed for the answer, is not spent.
        self.router_models = list(dict.fromkeys(m for m in (cfg.llm_router_model, *reversed(self.models)) if m))
        self.extra = {"reasoning_effort": cfg.llm_reasoning_effort} if cfg.llm_reasoning_effort else {}
        # Model -> when to try it again. Groq's daily limit frees up in tens of minutes, and knocking
        # on such a model for every question only adds delay.
        self.resting: dict[str, float] = {}

    async def json(self, system: str, user: str, max_tokens: int = 2000, router: bool = False,
                   effort: str | None = None) -> dict:
        """A request returning a JSON object. On a rate limit or failure, moves to a fallback model."""
        extra = {**self.extra, "reasoning_effort": effort} if effort and self.extra else self.extra
        request = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "extra_body": extra,
        }
        waits: dict[str, float] = {}
        now = time.monotonic()
        models = [m for m in (self.router_models if router else self.models) if self.resting.get(m, 0) <= now]
        for i, model in enumerate(models):
            try:
                return await self._ask(model, request, wait_limit=MAX_WAIT if i == 0 else 0)
            except RateLimitError as exc:
                if (wait := retry_after(exc)) is not None:
                    waits[model] = wait
                    if wait > MAX_LAST_WAIT:
                        self.resting[model] = now + wait
                log.warning("Rate limit for model %s (retry-after %s), trying the next one", model, wait)
            except (APIError, json.JSONDecodeError) as exc:
                log.warning("Model %s error: %s", model, exc)
        # All models are rate-limited: better to wait a little for the first one to free up than not to answer at all.
        if waits and (model := min(waits, key=waits.get)) and waits[model] <= MAX_LAST_WAIT:
            try:
                return await self._ask(model, request, wait_limit=MAX_LAST_WAIT)
            except (APIError, json.JSONDecodeError) as exc:
                log.warning("Model %s unavailable even after waiting: %s", model, exc)
        raise LLMUnavailable()

    async def _ask(self, model: str, request: dict, wait_limit: float) -> dict:
        """One request; if the limit frees up within wait_limit seconds, waits and retries once."""
        try:
            response = await self.client.chat.completions.create(model=model, **request)
        except RateLimitError as exc:
            wait = retry_after(exc)
            if wait is None or wait > wait_limit:
                raise
            log.info("Model %s rate-limited, waiting %.1f s", model, wait)
            await asyncio.sleep(wait + 0.5)
            response = await self.client.chat.completions.create(model=model, **request)
        return json.loads(response.choices[0].message.content or "")
