"""AI keys entered on the dashboard.

A key in .env needs the Terminal and a restart. When a free key runs out in the middle of the day, the manager
can type a new one on the MAGI screen instead. It is checked with one tiny request, kept in the server's own
data folder (never in the database, never sent back to the browser) and used from the next request on.
"""

import asyncio
import json
import logging
import os

from fastapi import APIRouter, HTTPException
from openai import APIStatusError, AsyncOpenAI
from pydantic import BaseModel

from . import llm, quick
from .config import get_settings

log = logging.getLogger("mai.keys")
router = APIRouter(prefix="/api/keys")
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _file():
    return get_settings().data_dir / "keys.json"


def _saved() -> dict:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _use(value: str) -> None:
    get_settings().gemini_api_key = value
    llm._SLOTS = None                               # the brains are rebuilt with the new key on the next call
    for name in [n for n in llm._cooldown if "gemini" in n]:
        del llm._cooldown[name]
    quick._clients = None


def load() -> None:
    """At start-up: a key saved from the dashboard takes the place of the one in .env."""
    value = _saved().get("gemini")
    if value:
        _use(value)


class Key(BaseModel):
    value: str


@router.get("")
async def status():
    """Whether Gemini has a key and whether it is resting. The key itself is never returned."""
    now = asyncio.get_running_loop().time()
    resting = [n for n, until in llm._cooldown.items() if "gemini" in n and until > now + 120]
    names = {sl.name for sl in llm.slots() if "gemini" in sl.name}
    return {"gemini": {"saved": bool(get_settings().gemini_api_key), "from_dashboard": bool(_saved().get("gemini")),
                       "resting": bool(names) and len(resting) >= len(names)}}


@router.post("/gemini")
async def set_gemini(key: Key):
    value = "".join(key.value.split()).strip("\"'")
    if not 30 <= len(value) <= 200:
        raise HTTPException(400, "That does not look like a Gemini key. Copy it again from aistudio.google.com/apikey.")
    try:                                            # one tiny request: is the key real, and does it still have room
        await AsyncOpenAI(api_key=value, base_url=GEMINI, timeout=20, max_retries=0).chat.completions.create(
            model="gemini-flash-lite-latest", messages=[{"role": "user", "content": "Say ok."}], max_tokens=5)
    except APIStatusError as e:
        if e.status_code == 429:
            raise HTTPException(400, "This key is real, but it has no free requests left today. Use a key that is not used up.")
        raise HTTPException(400, "Google did not accept this key. Copy it again from aistudio.google.com/apikey.")
    except Exception:  # noqa: BLE001
        raise HTTPException(502, "Google could not be reached to check the key. Try again in a minute.")
    path = _file()
    path.write_text(json.dumps({**_saved(), "gemini": value}), encoding="utf-8")
    os.chmod(path, 0o600)
    _use(value)
    log.info("a new Gemini key was saved from the dashboard (%d characters)", len(value))
    return {"saved": True}
