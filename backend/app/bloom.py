"""Bloom (trybloom.ai): the brand's creative direction, used as context and ideas only.

MAGI reads the Brand Skill that Bloom holds for the company: colours, type, layout patterns and the
written creative direction. Reading it runs no model and costs no Bloom credits. The strategist and
the art director get it as extra context. MAGI never asks Bloom to make an image: every image and
video is made on Higgsfield.
"""

import json
import logging
import time

import httpx

from .config import get_settings

log = logging.getLogger("mai.bloom")
API = "https://www.trybloom.ai/api/v1"
REFRESH_SECONDS = 12 * 3600
_cache: dict = {"at": 0.0, "skill": None}


def ready() -> bool:
    return bool(get_settings().bloom_api_key)


def _store():
    return get_settings().data_dir / "bloom_skill.json"


async def _get(path: str, **params) -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(f"{API}{path}", headers={"x-api-key": get_settings().bloom_api_key}, params=params or None)
    if r.status_code >= 300:
        raise RuntimeError(f"Bloom said {r.status_code}: {r.text[:200]}")
    return r.json()


def _items(reply) -> list:
    data = reply.get("data", reply) if isinstance(reply, dict) else reply
    if isinstance(data, dict):
        data = data.get("brands") or data.get("items") or data.get("data") or []
    return data if isinstance(data, list) else []


async def brands() -> list[dict]:
    return [{"id": b.get("id"), "name": b.get("name"), "status": b.get("status")} for b in _items(await _get("/brands"))]


async def skill(force: bool = False) -> dict | None:
    """The company's Brand Skill from Bloom, kept for half a day; None when Bloom is not set up."""
    if not ready():
        return None
    if _cache["skill"] and not force and time.time() - _cache["at"] < REFRESH_SECONDS:
        return _cache["skill"]
    if not force and not _cache["skill"] and _store().exists():
        saved = json.loads(_store().read_text())
        if time.time() - saved.get("read_at", 0) < REFRESH_SECONDS:
            _cache.update(at=saved["read_at"], skill=saved)
            return saved
    s = get_settings()
    found = await brands()
    usable = [b for b in found if b["status"] in ("ready", None)]
    pick = next((b for b in usable if s.bloom_brand_id and b["id"] == s.bloom_brand_id), None) \
        or next((b for b in usable if "magppie" in (b["name"] or "").lower()), None) \
        or (usable[0] if len(usable) == 1 else None)
    if not pick:
        log.warning("Bloom has no ready brand to read (found: %s)", [(b["name"], b["status"]) for b in found])
        return None
    d = (await _get(f"/brands/{pick['id']}/skill")).get("data") or {}
    profile = d.get("profile") or {}
    type_ = profile.get("typography") or {}
    out = {"read_at": time.time(), "brand_id": pick["id"], "brand": profile.get("name") or pick["name"],
           "skill_id": d.get("skillId"),
           "colours": [c.get("hex") for c in profile.get("colors") or [] if c.get("hex")],
           "fonts": {k: (type_.get(k) or {}).get("family") for k in ("heading", "body") if type_.get(k)},
           "files": [{"path": f.get("path") or f.get("name") or "", "text": f.get("content") or f.get("contents") or ""}
                     for f in d.get("files") or [] if isinstance(f, dict)]}
    _store().write_text(json.dumps(out, ensure_ascii=False))
    _cache.update(at=out["read_at"], skill=out)
    return out


async def context(max_chars: int = 5000) -> str:
    """The creative direction as text for a prompt; empty when Bloom is not set up or not reachable."""
    try:
        s = await skill()
    except Exception as e:  # noqa: BLE001 — Bloom is an extra; the agents work without it
        log.info("Bloom not reachable: %s", str(e)[:160])
        return ""
    if not s:
        return ""
    head = f"Brand in Bloom: {s['brand']}. Colours: {', '.join(s['colours']) or 'not set'}. " \
           f"Fonts: {', '.join(f'{k} {v}' for k, v in s['fonts'].items() if v) or 'not set'}."
    files = sorted(s["files"], key=lambda f: (not f["path"].upper().endswith("SKILL.MD"), f["path"]))
    body, left = [], max_chars - len(head)
    for f in files:
        if left < 200 or not f["text"].strip():
            continue
        piece = f"\n--- {f['path']}\n{f['text'].strip()}"[:left]
        body.append(piece)
        left -= len(piece)
    return head + "".join(body)


async def status() -> dict:
    if not ready():
        return {"connected": False}
    try:
        s = await skill()
        return {"connected": True, "brand": s and s["brand"], "has_skill": bool(s), "colours": s and s["colours"],
                "files": s and [f["path"] for f in s["files"]]}
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "error": str(e)[:200]}
