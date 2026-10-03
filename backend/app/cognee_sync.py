"""Cognee: the connected-knowledge map.

Every morning after the crawl, new confirmed learnings and company KB passages are handed to
Cognee, which links the things they mention (competitors, products, materials, trends) into a
graph. MAI can then answer questions about how things relate, not only look facts up.

Cognee needs about two AI calls per passage, so each run handles a limited number and a large
KB is mapped over several mornings.
"""

import hashlib
import logging

import httpx

from . import db
from .config import get_settings

log = logging.getLogger("mai.cognee")
DATASET = "learnings"          # one dataset for learnings and company knowledge, so the graph links them


def _url(path: str) -> str:
    return get_settings().cognee_url.rstrip("/") + path


async def _post(path: str, body: dict, timeout: float = 600) -> dict:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(_url(path), json=body)
    r.raise_for_status()
    return r.json()


async def status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            job = (await c.get(_url("/cognify/status"))).json()
    except httpx.HTTPError as e:
        return {"available": False, "reason": str(e)[:200]}
    counts = await db.fetchrow("""select
        (select count(*) from learnings where cognee_synced_at is not null) learnings_mapped,
        (select count(*) from learnings where status in ('active','approved') and cognee_synced_at is null) learnings_waiting,
        (select count(*) from kb_chunks where cognee_synced_at is not null) kb_mapped,
        (select count(*) from kb_chunks where active and doc in ('core','brand','manager') and cognee_synced_at is null) kb_waiting""")
    return {"available": True, "state": job.get("state"), "last_error": job.get("last_error"),
            "last_run_seconds": job.get("duration_s"), "last_run_ai_calls": job.get("llm_calls"), **counts}


async def sync() -> dict:
    """Hand new knowledge to Cognee, drop what was retired, then rebuild the map."""
    row = await db.fetchrow("select value from settings where key = 'cognee_budget'")
    budget = {"kb_passages_per_run": 150, "learnings_per_run": 300, **((row or {}).get("value") or {})}
    out = {"learnings": 0, "kb_passages": 0, "forgotten": 0}

    gone = await db.fetch("select id from learnings where cognee_synced_at is not null "
                          "and status in ('expired','rejected','discarded')")
    for g in gone:
        try:
            await _post("/forget", {"id": f"learning-{g['id']}", "dataset": DATASET}, timeout=120)
            await db.execute("update learnings set cognee_synced_at = null where id = %s", g["id"])
            out["forgotten"] += 1
        except httpx.HTTPError as e:           # cognify running, or service busy: try again next run
            log.info("could not forget learning %s yet: %s", g["id"], e)

    learned = await db.fetch(
        "select id, coalesce(edited_content, content) text, kind, source_urls from learnings "
        "where status in ('active','approved') and cognee_synced_at is null order by id limit %s",
        budget["learnings_per_run"])
    if learned:
        await _post("/add", {"dataset": DATASET, "items": [
            {"id": f"learning-{l['id']}", "text": l["text"],
             "meta": {"kind": l["kind"], "sources": l["source_urls"][:3]}} for l in learned]})
        await db.execute("update learnings set cognee_synced_at = now() where id = any(%s)",
                         [l["id"] for l in learned])
        out["learnings"] = len(learned)

    passages = await db.fetch(
        "select id, doc, section, content from kb_chunks where active and doc in ('core','brand','manager') "
        "and cognee_synced_at is null order by id limit %s", budget["kb_passages_per_run"])
    if passages:
        # id from the text itself, so reloading the KB does not create duplicates
        await _post("/add", {"dataset": DATASET, "items": [
            {"id": "kb-" + hashlib.sha1(p["content"].encode()).hexdigest()[:16],
             "text": (f"{p['section']}\n" if p["section"] else "") + p["content"],
             "meta": {"kind": "company_knowledge", "doc": p["doc"], "section": p["section"]}} for p in passages]})
        await db.execute("update kb_chunks set cognee_synced_at = now() where id = any(%s)",
                         [p["id"] for p in passages])
        out["kb_passages"] = len(passages)

    if out["learnings"] or out["kb_passages"] or out["forgotten"]:
        job = await _post("/cognify", {"dataset": DATASET}, timeout=60)
        out["map_build"] = "started" if job.get("started") else "queued behind a running build"
    else:
        out["map_build"] = "nothing new"
    log.info("cognee sync: %s", out)
    return out


async def search(question: str, top_k: int = 8) -> dict:
    return await _post("/search", {"query": question, "dataset": DATASET, "top_k": top_k, "mode": "graph"},
                       timeout=150)
