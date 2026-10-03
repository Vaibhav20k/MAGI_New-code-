"""The AI brain every agent uses.

All providers speak the OpenAI API format, so one client handles them. Each provider/model
pair is a "slot" with its own free limit. A request walks the slots in order and moves on
when one is rate limited or fails:

  careful work (ideas, blogs, creatives, scripts) →  NVIDIA  →  Token Harbor  →  Gemini models in turn  →  Groq  →  OpenRouter
  fast work (the crawler's bulk reading)          →  Groq  →  NVIDIA's small quick model, and nothing else

The two lists are kept apart on purpose. The crawler makes thousands of requests a night; if it may fall
back onto the content brains it empties their free allowances (Token Harbor's is counted per week, Gemini's
per day). When Groq is at its limit the crawler waits; the content brains stay untouched.
Google's free limits are per model, so several Gemini models give several separate allowances.
MAI chat (Hermes) and Cognee each use a Gemini model that is NOT in these lists, so the three
never compete for the same allowance.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from openai import AsyncOpenAI, APIStatusError, RateLimitError, APIConnectionError

from .config import get_settings

log = logging.getLogger("mai.llm")


@dataclass
class Slot:
    provider: str
    model: str
    client: AsyncOpenAI
    limiter: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))
    json_mode: bool = True          # switched off for a model that rejects response_format

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"


WAIT = 80           # seconds before a silent brain is given up on and the next one is asked
LONG_WAIT = 170     # the same, for long pieces of writing (a whole blog)


def _models(csv: str) -> list[str]:
    return [m.strip() for m in csv.split(",") if m.strip()]


def _build() -> dict[str, list[Slot]]:
    s = get_settings()
    careful: list[Slot] = []
    fast: list[Slot] = []
    if s.gemini_api_key:
        g = AsyncOpenAI(api_key=s.gemini_api_key, timeout=WAIT, max_retries=0,
                        base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
        careful += [Slot("gemini", m, g) for m in _models(s.gemini_models)]
        gemini_fast = [Slot("gemini", m, g) for m in _models(s.gemini_fast_models)]
    else:
        gemini_fast = []
    groq = [Slot("groq", s.groq_model, AsyncOpenAI(api_key=s.groq_api_key, timeout=WAIT, max_retries=0,
                                                   base_url="https://api.groq.com/openai/v1"))] \
        if s.groq_api_key else []
    harbor: list[Slot] = []
    if s.tokenharbor_api_key:
        h = AsyncOpenAI(api_key=s.tokenharbor_api_key, base_url="https://tokenharbor.ai/v1", timeout=WAIT, max_retries=0)
        harbor = [Slot("tokenharbor", m, h) for m in _models(s.tokenharbor_models)]
    nvidia: list[Slot] = []
    nvidia_fast: list[Slot] = []
    if s.nvidia_api_key:
        n = AsyncOpenAI(api_key=s.nvidia_api_key, base_url="https://integrate.api.nvidia.com/v1", timeout=WAIT, max_retries=0)
        nvidia = [Slot("nvidia", m, n) for m in _models(s.nvidia_models)]
        nvidia_fast = [Slot("nvidia", s.nvidia_fast_model, n)] if s.nvidia_fast_model else []
    rest: list[Slot] = []
    if s.cerebras_api_key:
        rest.append(Slot("cerebras", s.cerebras_model,
                         AsyncOpenAI(api_key=s.cerebras_api_key, base_url="https://api.cerebras.ai/v1")))
    if s.openrouter_api_key:
        o = AsyncOpenAI(api_key=s.openrouter_api_key, base_url="https://openrouter.ai/api/v1", timeout=WAIT, max_retries=0)
        rest += [Slot("openrouter", m, o) for m in _models(s.openrouter_model)]
    if s.xai_api_key:
        rest.append(Slot("xai", s.xai_model, AsyncOpenAI(api_key=s.xai_api_key, base_url="https://api.x.ai/v1")))
    return {"careful": nvidia + harbor + careful + groq + rest,
            "fast": groq + nvidia_fast + gemini_fast}


_SLOTS: dict[str, list[Slot]] | None = None
_cooldown: dict[str, float] = {}       # slot name → loop time when it may be tried again


def slots(fast: bool = False) -> list[Slot]:
    global _SLOTS
    if _SLOTS is None:
        _SLOTS = _build()
    return _SLOTS["fast" if fast else "careful"]


def providers() -> list:
    """Distinct providers that have a key (shown on the dashboard)."""
    seen: dict[str, Slot] = {}
    for sl in slots():
        seen.setdefault(sl.provider, sl)
    return list(seen.values())


class NoProviderAvailable(RuntimeError):
    pass


async def chat(messages: list[dict], *, fast: bool = False, json_mode: bool = False,
               temperature: float = 0.7, max_tokens: int | None = None, long: bool = False) -> str:
    order = slots(fast)
    if not order:
        raise NoProviderAvailable("No AI key set. Add a key with scripts/add-keys.sh.")
    loop = asyncio.get_running_loop()
    last_err: Exception | None = None
    for attempt in range(4):
        for sl in order:
            if _cooldown.get(sl.name, 0) > loop.time():
                continue
            kwargs = dict(model=sl.model, messages=messages, temperature=temperature, timeout=LONG_WAIT if long else WAIT)
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            if json_mode and sl.json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                async with sl.limiter:
                    resp = await sl.client.chat.completions.create(**kwargs)
                text = resp.choices[0].message.content or ""
                text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()   # drop a model's private notes
                if text:
                    return text
                last_err = RuntimeError(f"{sl.name} returned an empty reply")
                _cooldown[sl.name] = loop.time() + 20
            except RateLimitError as e:
                # a spent allowance says when to come back (Retry-After); a busy minute clears quickly
                try:
                    wait = float(e.response.headers.get("retry-after") or 0)
                except (AttributeError, ValueError):
                    wait = 0
                if "allowance" in str(e).lower() or "quota" in str(e).lower():
                    wait = max(wait, 1800)
                wait = min(max(wait, 45), 3600)
                log.info("%s is at its limit; resting it for %d s and trying the next brain", sl.name, wait)
                _cooldown[sl.name] = loop.time() + wait
                last_err = e
            except (APIStatusError, APIConnectionError) as e:
                code = getattr(e, "status_code", None)
                if code == 400 and "response_format" in kwargs:
                    sl.json_mode = False        # this model wants plain requests; it is asked again on the next pass
                    log.info("%s does not take JSON mode; it will be asked without it", sl.name)
                    last_err = e
                    continue
                log.warning("%s failed (%s); trying the next brain", sl.name, str(e)[:160])
                # a rejected key or an account with no credit won't recover by itself: rest it for a day.
                # 403 = the account is not allowed yet (e.g. email not confirmed): look again in ten minutes.
                # 413 = this request is too big for that model: skip it for this request only.
                _cooldown[sl.name] = loop.time() + (86400 if code in (401, 402) else 600 if code == 403
                                                    else 2 if code == 413 else 20)
                last_err = e
        await asyncio.sleep(15 * (attempt + 1))
    raise NoProviderAvailable(f"Every AI brain is busy or at its free limit right now. Try again in a minute. ({last_err})")


def _extract_json(text: str):
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
        if start < 0:
            raise
        end = max(text.rfind("}"), text.rfind("]"))
        return json.loads(text[start:end + 1])


async def chat_json(system: str, user: str, *, fast: bool = False, temperature: float = 0.4):
    """Ask for JSON. A reply that is not valid JSON is asked for again, up to three times."""
    last: Exception | None = None
    for attempt in range(3):
        raw = await chat(
            [{"role": "system", "content": system + "\nReply with valid JSON only."},
             {"role": "user", "content": user}],
            fast=fast, json_mode=attempt < 2, temperature=temperature)
        try:
            return _extract_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            last = e
            log.warning("unusable JSON reply (attempt %d): %r", attempt + 1, raw[:120])
    raise RuntimeError(f"The AI did not return usable data after three tries: {last}")


async def complete(system: str, user: str, *, fast: bool = False, temperature: float = 0.7,
                   max_tokens: int | None = None, long: bool = False) -> str:
    return await chat([{"role": "system", "content": system},
                       {"role": "user", "content": user}],
                      fast=fast, temperature=temperature, max_tokens=max_tokens, long=long)
