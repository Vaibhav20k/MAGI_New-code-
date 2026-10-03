"""Agent 05 — Knowledge. Turns relevant pages into learnings and files them correctly.

Buckets (from inputs/crawler-rules.md):
  auto  → safe. Observations about one source are saved at once; general claims
          (trends, hooks, formats …) wait as 'pending' until a second source confirms them.
  hold  → doubtful. Goes to the holding area; no agent may use it until the manager approves.
  never → discarded, not stored.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .. import db, inputs, kb, llm
from ..embed import embed

log = logging.getLogger("mai.knowledge")

OBSERVATION_KINDS = {"engagement", "competitor_post", "new_source"}
KINDS = ["trend", "hook", "format", "keyword", "pain_point", "competitor_post", "industry_fact",
         "engagement", "new_source", "other"]
SAME = 0.88          # cosine similarity above which two learnings are the same point
PAGES_PER_CALL = 3

SYSTEM = """You are the Knowledge agent of a marketing intelligence system for the company described below.
You read pages collected from the web and extract short, standalone learnings that help the marketing team:
what topics, hooks and formats are working, what customers ask or worry about, what competitors posted.

Classify every learning with the company's approval rules. When unsure, choose "hold".
Ignore the "found on only one source" rule: the system counts sources itself and keeps single-source
items aside until a second source confirms them. Use "hold" only for what the learning is ABOUT
(the company itself, prices and numbers, competitor specs or claims, health, safety, legal, named people).
Never copy sentences word for word; state the point in your own words. Skip anything in the NEVER SAVE list.

Return JSON: {"learnings": [{"page": <page number>, "content": "<one or two sentences>",
"kind": "<one of: %s>", "bucket": "auto|hold|never", "rule": "<the rule that applies, short>",
"affects": "<what in our knowledge base it touches or contradicts, or empty>"}]}
Return at most 5 learnings per page; return none for a page with nothing useful.""" % ", ".join(KINDS)


async def _setting(key: str, default):
    row = await db.fetchrow("select value from settings where key = %s", key)
    return row["value"] if row else default


async def _file(run_id: int | None, item: dict, url: str) -> str:
    """Store one learning. Returns what happened: active|pending|held|merged|skipped."""
    content = (item.get("content") or "").strip()
    bucket = item.get("bucket")
    kind = item.get("kind") if item.get("kind") in KINDS else "other"
    if len(content) < 20 or bucket not in ("auto", "hold"):
        return "skipped"
    [vec] = await embed([content])
    similar = await db.fetch("select * from similar_learnings(%s, 3)", vec)
    for s in similar:
        if s["similarity"] < SAME:
            continue
        if s["status"] in ("rejected", "discarded"):
            return "skipped"                      # the manager already said no to this
        row = await db.fetchrow("select * from learnings where id = %s", s["id"])
        if url in row["source_urls"] or inputs.domain_of(url) in {inputs.domain_of(u) for u in row["source_urls"]}:
            return "merged"
        await db.execute("update learnings set source_urls = array_append(source_urls, %s), "
                         "source_count = source_count + 1, confidence = least(confidence + 0.15, 0.95) "
                         "where id = %s", url, row["id"])
        if row["status"] == "pending":
            await _activate(row["id"])
            return "active"
        return "merged"

    trend_days = int(await _setting("trend_expiry_days", 60))
    expires = datetime.now(timezone.utc) + timedelta(days=trend_days) if kind in ("trend", "hook", "format",
                                                                                 "engagement") else None
    if bucket == "hold":
        status = "held"
    elif kind in OBSERVATION_KINDS:
        status = "active"
    else:
        status = "pending"
    row = await db.fetchrow(
        """insert into learnings (run_id, content, kind, bucket, status, rule, affects, source_urls, confidence,
                                  embedding, expires_at)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
        run_id, content, kind, bucket, status, item.get("rule"), item.get("affects") or None, [url],
        0.6 if status == "active" else 0.4, vec, expires)
    if status == "active":
        await kb.add_learned(content, {"learning_id": row["id"], "kind": kind, "sources": [url]})
    return status


async def _activate(learning_id: int):
    row = await db.fetchrow("update learnings set status = 'active' where id = %s returning *", learning_id)
    await kb.add_learned(row["edited_content"] or row["content"],
                         {"learning_id": row["id"], "kind": row["kind"], "sources": row["source_urls"]})


async def process_pages(run_id: int | None, max_pages: int = 30) -> dict:
    """Read the most relevant unread pages and file what they teach us."""
    pages = await db.fetch(
        "select id, url, title, content_md, meta from pages where kept and not processed "
        "order by relevance desc nulls last limit %s", max_pages)
    stats = {"pages": 0, "active": 0, "pending": 0, "held": 0, "merged": 0, "skipped": 0}
    if not pages:
        return stats
    company = "\n".join(r["content"][:600] for r in await db.fetch(
        "select content from kb_chunks where active and doc in ('brand','core') order by id limit 4"))
    system = SYSTEM + f"\n\nCOMPANY:\n{company}\n\nAPPROVAL RULES:\n{inputs.approval_rules()[:5000]}"
    for i in range(0, len(pages), PAGES_PER_CALL):
        group = pages[i:i + PAGES_PER_CALL]
        user = "\n\n".join(
            f"=== PAGE {n + 1} ===\nURL: {p['url']}\nTITLE: {p['title']}\nDETAILS: {p['meta']}\n"
            f"{(p['content_md'] or '')[:3500]}" for n, p in enumerate(group))
        try:
            data = await llm.chat_json(system, user, fast=True, temperature=0.2)
        except Exception as e:  # noqa: BLE001
            log.warning("knowledge extraction failed: %s", e)
            break
        for item in (data.get("learnings") or []):
            try:
                n = int(item.get("page", 1)) - 1
                url = group[n]["url"] if 0 <= n < len(group) else group[0]["url"]
                stats[await _file(run_id, item, url)] += 1
            except Exception as e:  # noqa: BLE001
                log.warning("could not file learning: %s", e)
        await db.execute("update pages set processed = true where id = any(%s)", [p["id"] for p in group])
        stats["pages"] += len(group)
    return stats


async def loop(run_id: int, should_stop) -> dict:
    """Runs beside the crawler all night, within the daily AI budget."""
    budget_pages = int((await _setting("knowledge_budget", {"pages_per_night": 240})).get("pages_per_night", 240))
    total = {"pages": 0, "active": 0, "pending": 0, "held": 0, "merged": 0, "skipped": 0}
    while total["pages"] < budget_pages:
        s = await process_pages(run_id, max_pages=12)
        for k in total:
            total[k] += s[k]
        if should_stop() and s["pages"] == 0:
            break
        await asyncio.sleep(20 if s["pages"] else 60)
    return total


# ---------------- Manager review ----------------

async def held_items() -> list[dict]:
    return await db.fetch(
        "select id, content, kind, rule, affects, source_urls, source_count, created_at, edited_content, "
        "manager_note, status from learnings where status = 'held' order by created_at desc")


async def decide(learning_id: int, action: str, content: str | None = None, note: str | None = None):
    """Record the manager's choice. Nothing reaches the KB until finalise_review()."""
    if action not in ("approve", "reject", "edit"):
        raise ValueError("action must be approve, reject or edit")
    await db.execute(
        "update learnings set manager_note = %s, edited_content = %s, reviewed_at = now() where id = %s",
        f"{action}{': ' + note if note else ''}", content if action == "edit" else None, learning_id)


async def finalise_review() -> dict:
    rows = await db.fetch("select * from learnings where status = 'held' and manager_note is not null")
    out = {"approved": 0, "rejected": 0, "edited": 0, "added": 0}
    for r in rows:
        action = r["manager_note"].split(":")[0]
        if action == "reject":
            await db.execute("update learnings set status = 'rejected' where id = %s", r["id"])
            out["rejected"] += 1
            continue
        text = r["edited_content"] or r["content"]
        if r["edited_content"]:
            [vec] = await embed([text])
            await db.execute("update learnings set embedding = %s where id = %s", vec, r["id"])
            out["edited"] += 1
        else:
            out["approved"] += 1
        await db.execute("update learnings set status = 'approved' where id = %s", r["id"])
        await kb.add_learned(text, {"learning_id": r["id"], "kind": r["kind"], "sources": r["source_urls"],
                                    "approved_by_manager": True})
    out["added"] = (await db.fetchrow(
        "select count(*) c from manager_rules where created_at > coalesce("
        "(select max(finalised_at) from review_sessions), '-infinity')"))["c"]
    await db.execute("insert into review_sessions (approved, rejected, edited, added) values (%s,%s,%s,%s)",
                     out["approved"], out["rejected"], out["edited"], out["added"])
    return out


async def housekeeping() -> dict:
    """Daily: retire stale trends, auto-reject held items nobody reviewed."""
    days = int(await _setting("hold_auto_reject_days", 14))
    expired = await db.fetch("update learnings set status = 'expired' where status in ('active','pending') "
                             "and expires_at < now() returning id")
    if expired:
        await db.execute("update kb_chunks set active = false where doc = 'learned' "
                         "and (meta->>'learning_id')::bigint = any(%s)", [e["id"] for e in expired])
    rejected = await db.fetch("update learnings set status = 'rejected', manager_note = 'auto: not reviewed' "
                              "where status = 'held' and created_at < now() - make_interval(days => %s) "
                              "returning id", days)
    return {"expired": len(expired), "auto_rejected": len(rejected)}
