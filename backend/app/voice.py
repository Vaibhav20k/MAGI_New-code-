"""MAI's ears and voice.

Ears  — Groq Whisper: accurate with Indian English, about a fifth of a second per clip.
Voice — Groq Orpheus (natural speech). If it is unavailable the page falls back to the browser's voice.
"""

import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .config import get_settings

log = logging.getLogger("mai.voice")
router = APIRouter(prefix="/api/mai")
GROQ = "https://api.groq.com/openai/v1"

# what Whisper tends to "hear" in silence or noise
PHANTOM = re.compile(r"^\W*(thank you|thanks|thanks for watching|you|bye|okay|ok|yeah|hmm+|uh+|\.+)?\W*$", re.I)


@router.post("/stt")
async def stt(request: Request):
    s = get_settings()
    audio = await request.body()
    if len(audio) < 1500:
        return {"text": ""}
    kind = (request.headers.get("content-type") or "audio/webm").split(";")[0]
    ext = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}.get(kind, "webm")
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(f"{GROQ}/audio/transcriptions",
                             headers={"Authorization": f"Bearer {s.groq_api_key}"},
                             files={"file": (f"speech.{ext}", audio, kind)},
                             data={"model": s.stt_model, "response_format": "verbose_json", "temperature": "0",
                                   "prompt": "Magppie, MAGI, Silverstone, wellness kitchen, wake up time."})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Speech service not reachable: {e}") from e
    if r.status_code != 200:
        raise HTTPException(502, f"Speech service error: {r.text[:200]}")
    data = r.json()
    text = (data.get("text") or "").strip()
    segs = data.get("segments") or []
    if segs and sum(x.get("no_speech_prob", 0) for x in segs) / len(segs) > 0.6:
        text = ""                                   # Whisper itself thinks nobody spoke
    if PHANTOM.match(text):
        text = ""
    return {"text": text}


class Say(BaseModel):
    text: str


@router.post("/tts")
async def tts(say: Say):
    s = get_settings()
    text = re.sub(r"[*_#`>]", "", say.text).strip()[:400]
    # written names, spoken the way the company says them
    for written, spoken in (("MAGI", "Maggie"), ("Magi", "Maggie"), ("MAGPPIE", "Magpie"), ("Magppie", "Magpie"),
                            ("SILVERSTONE", "Silverstone"), ("KBIS", "K biz"), ("NKBA", "N K B A")):
        text = re.sub(rf"\b{written}\b", spoken, text)
    if not text:
        raise HTTPException(400, "Nothing to say.")
    if s.kokoro_url:                                  # our own voice engine first
        try:
            async with httpx.AsyncClient(timeout=40) as c:
                k = await c.post(f"{s.kokoro_url}/v1/audio/speech",
                                 json={"model": "kokoro", "voice": s.kokoro_voice, "input": text,
                                       "response_format": "mp3", "speed": 1.05})
            if k.status_code == 200 and k.content:
                return Response(content=k.content, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
            log.warning("kokoro voice failed: %s", k.text[:200])
        except httpx.HTTPError as e:
            log.warning("kokoro voice not reachable: %s", e)
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            r = await c.post(f"{GROQ}/audio/speech",
                             headers={"Authorization": f"Bearer {s.groq_api_key}"},
                             json={"model": s.tts_model, "voice": s.tts_voice, "input": text,
                                   "response_format": "wav"})
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Voice service not reachable: {e}") from e
    if r.status_code != 200:
        # e.g. the model's terms have not been accepted yet — the page then uses the browser voice
        log.warning("tts unavailable: %s", r.text[:200])
        raise HTTPException(503, r.text[:300])
    return Response(content=r.content, media_type="audio/wav", headers={"Cache-Control": "no-store"})
