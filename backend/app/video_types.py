"""The kinds of video MAGI makes (inputs/video-types.json): the Strategist's menu, the idea card's dropdown, and
the template the video agents follow."""

import json
from functools import lru_cache

from .config import get_settings


@lru_cache(maxsize=1)
def _load(mtime: float) -> dict:
    p = get_settings().inputs_dir / "video-types.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["by_key"] = {t["key"]: t for t in data["types"]}
    return data


def library() -> dict:
    p = get_settings().inputs_dir / "video-types.json"
    return _load(p.stat().st_mtime)               # edits to the file are picked up without a restart


def get(key: str | None) -> dict:
    """The type for a key, or the default type when the key is missing, unknown or needs real footage."""
    lib = library()
    t = lib["by_key"].get(key or "")
    return t if t and t.get("generate") else lib["by_key"][lib["default"]]


def menu() -> str:
    """The generated types, one per line, for the Strategist's prompt."""
    return "\n".join(f"  {t['key']}: {t['label']}. Best for: {t['best_for']} Reach: {t['reach']}."
                     for t in library()["types"] if t.get("generate"))


def for_cards() -> dict:
    """What the idea card's dropdown needs."""
    lib = library()
    return {"default": lib["default"],
            "types": [{k: t.get(k) for k in ("key", "label", "generate", "best_for", "reach", "length_seconds")}
                      for t in lib["types"]]}


def brief(t: dict) -> str:
    """The template as the video agents read it."""
    beats = "\n".join(f"  {b}" for b in t.get("beats") or [])
    return (f"VIDEO TYPE: {t['label']} ({t['key']}). {t['best_for']}\n"
            f"Hook: {t['hook']} Preferred opening forms: {', '.join(t.get('opening_forms') or [])}.\n"
            f"Beats of each 30-second scene (keep these timings):\n{beats}\n"
            f"Camera: {t['camera']}\nOn-screen text: {t['on_screen_text']}\nVoice: {t['voice']}\n"
            f"People: {t['people']}\nCautions: {t['cautions']}")


def choose(suggested: str | None, taken: set[str]) -> str:
    """The Strategist's suggestion when it is a type MAGI can make, else the first one not already used in this set."""
    lib = library()
    if suggested in lib["by_key"] and lib["by_key"][suggested].get("generate") and suggested not in taken:
        return suggested
    makeable = [t["key"] for t in lib["types"] if t.get("generate")]
    if suggested in makeable:
        return suggested
    return next((k for k in makeable if k not in taken), lib["default"])
