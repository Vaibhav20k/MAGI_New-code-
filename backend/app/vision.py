"""Looking at pictures, on Gemini's free plan.

Kept apart from llm.py on purpose: the text brains there switch off JSON mode for good when a model rejects a
request, and a picture sent to a text-only model would do exactly that. This client talks only to Gemini models
that see images, uses models no other part of MAGI uses (so it never eats the chat's or the crawler's allowance),
and stops for the day at a cap.
"""

import base64
import io
import json
import logging
import time
from datetime import date

from openai import AsyncOpenAI

from .config import get_settings

log = logging.getLogger("mai.vision")
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"

_client: AsyncOpenAI | None = None
_rest: dict[str, float] = {}                    # model -> time it may be asked again
_day = {"date": None, "calls": 0}


class Unavailable(RuntimeError):
    """No key, the day's cap is reached, or every vision model is resting."""


def reset() -> None:
    """Called when a new Gemini key is saved."""
    global _client
    _client = None
    _rest.clear()


def _c() -> AsyncOpenAI:
    global _client
    if _client is None:
        key = get_settings().gemini_api_key
        if not key:
            raise Unavailable("No Gemini key is saved, so MAGI cannot look at pictures yet.")
        _client = AsyncOpenAI(api_key=key, base_url=GEMINI, timeout=90, max_retries=0)
    return _client


def shrink(data: bytes, longest: int = 1024) -> bytes:
    """A smaller JPEG of the picture: enough to describe it, a fraction of the tokens."""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGB")
    im.thumbnail((longest, longest))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


def calls_left() -> int:
    today = date.today().isoformat()
    if _day["date"] != today:
        _day.update(date=today, calls=0)
    return max(0, get_settings().vision_daily_cap - _day["calls"])


async def ask(prompt: str, images: list[bytes]) -> dict:
    """Send a prompt and some pictures; return the JSON answer. Tries each vision model in turn."""
    if calls_left() <= 0:
        raise Unavailable("Today's free allowance for looking at pictures is used up. It continues tomorrow.")
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(shrink(b)).decode()}}
        for b in images]
    models = [m.strip() for m in get_settings().gemini_vision_models.split(",") if m.strip()]
    last = "no vision model is configured"
    for model in models:
        if _rest.get(model, 0) > time.monotonic():
            continue
        try:
            r = await _c().chat.completions.create(model=model, messages=[{"role": "user", "content": content}],
                                                   response_format={"type": "json_object"}, temperature=0.2)
            _day["calls"] += 1
            return json.loads(r.choices[0].message.content or "{}")
        except Unavailable:
            raise
        except Exception as e:  # noqa: BLE001 — a rate limit or a bad answer: rest this model, try the next
            code = getattr(e, "status_code", None)
            _rest[model] = time.monotonic() + (3600 if code == 429 else 600)
            last = f"{model}: {str(e)[:200]}"
            log.info("vision model %s failed: %s", model, last)
    raise Unavailable("Gemini could not look at the pictures right now (" + last + ").")
