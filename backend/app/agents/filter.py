"""Agent 04 — Filter. Keeps pages about Magppie's world, drops the rest.

Relevance = how close a page is to the company KB, minus how close it is to
clearly off-topic material. Subtracting the off-topic score cancels the high
baseline similarity small embedding models give to any text.
"""

import numpy as np

from .. import db
from ..embed import embed, embed_sync

OFF_TOPIC = [
    "cricket match score and IPL team news", "stock market tips and share prices today",
    "election results and political party news", "celebrity gossip and Bollywood rumours",
    "cryptocurrency price prediction", "football transfer news", "online casino and betting",
    "job openings and careers apply now", "privacy policy terms and conditions cookies",
    "login sign in create account password",
]

_state: dict = {}


async def load_profiles() -> None:
    """Build the 'about us' profile from the KB and the off-topic profile."""
    rows = await db.fetch(
        "select embedding from kb_chunks where active and doc in ('core','brand','script_bank','learned','manager') "
        "and embedding is not null order by random() limit 400")
    if rows:
        kb = np.stack([db.vec(r["embedding"]) for r in rows])
    else:
        kb = np.zeros((1, 384), dtype=np.float32)
    kb /= np.linalg.norm(kb, axis=1, keepdims=True) + 1e-9
    off = np.stack(embed_sync(OFF_TOPIC))
    off /= np.linalg.norm(off, axis=1, keepdims=True) + 1e-9
    _state["kb"], _state["off"] = kb, off


def _text_for(title: str, markdown: str) -> str:
    return f"{title}\n{markdown[:2000]}"


async def score(items: list[tuple[str, str]]) -> list[tuple[float, np.ndarray]]:
    """items = [(title, markdown)] → [(relevance, embedding)]"""
    if "kb" not in _state:
        await load_profiles()
    vecs = await embed([_text_for(t, m) for t, m in items])
    out = []
    for v in vecs:
        u = v / (np.linalg.norm(v) + 1e-9)
        kb_sims = _state["kb"] @ u
        top = np.sort(kb_sims)[-5:].mean()           # close to several KB passages
        off = float((_state["off"] @ u).max())
        out.append((float(top - off), v))
    return out


async def threshold() -> float:
    row = await db.fetchrow("select value from settings where key = 'crawl_limits'")
    return float((row or {}).get("value", {}).get("relevance_threshold", 0.05))
