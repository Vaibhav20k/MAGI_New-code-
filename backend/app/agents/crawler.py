"""Agents 02 (Discovery) and 03 (Crawler): the night cycle that finds and reads pages.

Breadth-first crawl we drive ourselves (the Crawl4AI server has no deep-crawl mode):
read a page → Filter scores it → if relevant, queue its links (same site and new sites).
Discovery tops up the queue with SearXNG searches on KB topics.
"""

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urldefrag, urlparse, urlencode, parse_qsl, urlunparse
from zoneinfo import ZoneInfo

from .. import db, inputs, llm, services
from ..config import get_settings
from . import filter as flt
from . import knowledge

log = logging.getLogger("mai.crawler")

SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|mp4|mp3|zip|rar|docx?|xlsx?|pptx?|css|js|xml|ico)(\?|$)", re.I)
SKIP_PATH = re.compile(r"/(login|signin|sign-in|signup|register|cart|checkout|account|privacy|terms|cookie|"
                       r"careers?|jobs?|wp-admin|wp-login|feed|tag|author|search|share|intent)(/|$|\?)", re.I)
SOCIAL = ("facebook.com", "twitter.com", "x.com", "whatsapp.com", "t.me", "linkedin.com/share",
          "pinterest.com/pin/create", "mailto:", "tel:")
TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "ref"}

state = {"run_id": None, "stop": False, "task": None}


def normalize(url: str) -> str | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    url, _ = urldefrag(url)
    p = urlparse(url)
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if k.lower() not in TRACKING])
    url = urlunparse((p.scheme, p.netloc.lower(), p.path or "/", "", q, ""))
    if SKIP_EXT.search(url) or SKIP_PATH.search(p.path) or any(s in url for s in SOCIAL):
        return None
    return url


async def _limits() -> dict:
    row = await db.fetchrow("select value from settings where key = 'crawl_limits'")
    return {"max_depth": 3, "per_domain_delay_s": 3, "max_pages_per_run": 30000,
            **((row or {}).get("value") or {})}


async def enqueue(url: str, depth: int, priority: float, reason: str, source_id: int | None = None):
    u = normalize(url)
    if not u:
        return
    await db.execute(
        """insert into crawl_queue (url, depth, priority, source_id, reason) values (%s,%s,%s,%s,%s)
           on conflict (url) do update set priority = greatest(crawl_queue.priority, excluded.priority)""",
        u, depth, priority, source_id, reason)


async def discovery_round(run_id: int, n_queries: int = 8) -> int:
    """Agent 02: turn KB topics + crawler rules into searches, queue what SearXNG finds."""
    rules = inputs.section(inputs.crawler_rules(), "1. What we are looking for")
    kb_sample = await db.fetch(
        "select content from kb_chunks where active and doc in ('core','learned','manager') order by random() limit 6")
    done = await db.fetch("select distinct reason from crawl_queue where reason like 'search:%%' limit 200")
    try:
        data = await llm.chat_json(
            "You plan web searches for a marketing research crawler. Return JSON {\"queries\": [..]}.",
            f"Company context:\n{chr(10).join(r['content'][:500] for r in kb_sample)}\n\n"
            f"What we look for:\n{rules}\n\nAlready searched: {[d['reason'] for d in done][:40]}\n\n"
            f"Write {n_queries} new, specific search queries that would find recent articles, blogs, "
            "videos and campaigns on these topics from competitors, industry publications and creators. "
            "Mix English and India-specific queries.", fast=True)
        queries = [q for q in data.get("queries", []) if isinstance(q, str)][:n_queries]
    except Exception as e:  # noqa: BLE001
        log.warning("discovery planning failed: %s", e)
        queries = []
    blocked = await inputs.blocked_domains()
    added = 0
    for q in queries:
        for r in await services.search(q, time_range="month"):
            if inputs.domain_of(r["url"]) in blocked:
                continue
            await enqueue(r["url"], 1, 0.6, f"search:{q}")
            added += 1
    log.info("discovery: %d queries → %d urls", len(queries), added)
    return added


async def _store_page(run_id: int, url: str, title: str, md: str, meta: dict, source_id: int | None,
                      rel: float, kept: bool, vec) -> bool:
    h = hashlib.sha256(md.encode()).hexdigest() if md else None
    if h and await db.fetchrow("select 1 from pages where content_hash = %s", h):
        return False
    await db.execute(
        """insert into pages (url, source_id, run_id, title, content_md, content_hash, relevance, kept, meta)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (url) do nothing""",
        url, source_id, run_id, title, md[:60000], h, rel, kept, db.Jsonb(meta))
    return True


async def _source_for(url: str, discovered_from: int | None) -> int:
    dom = inputs.domain_of(url)
    row = await db.fetchrow("select id from sources where domain = %s order by status = 'seed' desc limit 1", dom)
    if row:
        return row["id"]
    p = urlparse(url)
    row = await db.fetchrow(
        """insert into sources (url, domain, kind, status, discovered_from) values (%s,%s,%s,'discovered',%s)
           on conflict (url) do update set url = excluded.url returning id""",
        f"{p.scheme}://{p.netloc}/", dom, inputs.kind_for(url), discovered_from)
    return row["id"]


async def _youtube_sources(run_id: int, stats: dict):
    """YouTube channels and videos from seed-sources.md: titles, views, transcripts."""
    rows = await db.fetch("select id, url, kind from sources where kind in ('youtube_channel','youtube_video') "
                          "and status in ('seed','trusted')")
    details = True                 # YouTube sometimes refuses video details to servers; titles and views still come
    for r in rows:
        if state["stop"]:
            return
        try:
            videos = [{"url": r["url"]}] if r["kind"] == "youtube_video" else \
                await services.youtube_channel_videos(r["url"], limit=12)
        except Exception as e:  # noqa: BLE001
            log.info("youtube channel %s: %s", r["url"], str(e)[:120])
            continue
        channel = r["url"].rstrip("/").rsplit("/", 1)[-1].lstrip("@")
        for v in videos:
            if state["stop"] or await db.fetchrow("select 1 from pages where url = %s", v["url"]):
                continue
            info = None
            if details:
                try:
                    info = await services.youtube_video(v["url"])
                except Exception as e:  # noqa: BLE001
                    log.info("youtube %s: %s", v["url"], str(e)[:120])
                    details = "Sign in to confirm" not in str(e)
            if not info:
                if not v.get("title"):
                    continue
                info = {"title": v["title"], "channel": channel, "views": v.get("views") or 0, "likes": None,
                        "comments": None, "duration": None, "upload_date": None, "tags": [], "description": "",
                        "transcript": ""}
            md = f"# {info['title']}\nChannel: {info['channel']} · Views: {info['views']} · Likes: {info['likes']}\n\n" \
                 f"{info['description'][:3000]}\n\nTranscript:\n{info['transcript'][:8000]}"
            [(rel, vec)] = await flt.score([(info["title"] or "", md)])
            kept = rel >= await flt.threshold()
            meta = {k: info[k] for k in ("views", "likes", "comments", "duration", "upload_date", "channel", "tags")}
            meta["platform"] = "youtube"
            if await _store_page(run_id, v["url"], info["title"] or "", md, meta, r["id"], rel, kept, vec):
                stats["pages_seen"] += 1
                stats["pages_kept"] += int(kept)
            await asyncio.sleep(2)


async def _social_sources(run_id: int, stats: dict):
    """Instagram and Facebook accounts from seed-sources.md: recent posts with likes, comments and views.
    Each account is read at most once a day, and only while the month's free Apify credit lasts."""
    from .. import social
    rows = await db.fetch("select id, url, kind from sources where kind in ('instagram','facebook') "
                          "and status in ('seed','trusted') and (last_crawled_at is null or "
                          "last_crawled_at < now() - interval '20 hours')")
    if not rows or not await social.budget_left():
        return
    thr = await flt.threshold()
    for kind, read in (("instagram", social.instagram), ("facebook", social.facebook)):
        mine = [r for r in rows if r["kind"] == kind]
        if not mine or state["stop"]:
            continue
        try:
            posts = await read([r["url"] for r in mine])
        except Exception as e:  # noqa: BLE001
            log.warning("%s reading failed: %s", kind, e)
            continue
        by_handle = {r["url"].rstrip("/").rsplit("/", 1)[-1].lower(): r["id"] for r in mine}
        fresh = [p for p in posts if len(p["text"]) >= 40
                 and not await db.fetchrow("select 1 from pages where url = %s", p["url"])]
        if fresh:
            pages = [social.as_page(p) for p in fresh]
            scores = await flt.score([(t, md) for t, md, _ in pages])
            for p, (title, md, meta), (rel, vec) in zip(fresh, pages, scores):
                src = by_handle.get(p["account"].lower()) or by_handle.get(p["source_url"].rstrip("/").rsplit("/", 1)[-1].lower())
                kept = rel >= thr
                if await _store_page(run_id, p["url"], title, md, meta, src, rel, kept, vec):
                    stats["pages_seen"] += 1
                    stats["pages_kept"] += int(kept)
        await db.execute("update sources set last_crawled_at = now() where id = any(%s)", [r["id"] for r in mine])
        log.info("%s: %d posts read, %d new", kind, len(posts), len(fresh))


async def run(trigger: str = "schedule", until: datetime | None = None) -> dict:
    """The night cycle. Runs until `until`, a stop request, or the page limit."""
    if state["run_id"]:
        return {"status": "already_running", "run_id": state["run_id"]}
    s = get_settings()
    tz = ZoneInfo(s.timezone)
    until = until or (datetime.now(tz).replace(hour=8, minute=0, second=0, microsecond=0)
                      + (timedelta(days=1) if datetime.now(tz).hour >= 8 else timedelta()))
    row = await db.fetchrow("insert into crawl_runs (trigger) values (%s) returning id", trigger)
    run_id = row["id"]
    state.update(run_id=run_id, stop=False)
    stats = {"pages_seen": 0, "pages_kept": 0, "new_sources": 0, "searches": 0, "errors": 0}
    lim = await _limits()
    try:
        await inputs.sync_seed_sources()
        await flt.load_profiles()
        blocked = await inputs.blocked_domains()
        for src in await db.fetch("select id, url from sources where kind = 'website' "
                                  "and status in ('seed','trusted')"):
            await enqueue(src["url"], 0, 1.0, "seed", src["id"])
        for src in await db.fetch("select id, url from sources where kind = 'website' and status = 'discovered' "
                                  "and score > 0 order by score desc limit 50"):
            await enqueue(src["url"], 1, 0.5 + min(src.get("score", 0), 0.4), "revisit", src["id"])

        knowledge_task = asyncio.create_task(knowledge.loop(run_id, lambda: state["stop"] or
                                                            datetime.now(tz) >= until))
        yt_task = asyncio.create_task(_youtube_sources(run_id, stats))
        social_task = asyncio.create_task(_social_sources(run_id, stats))

        last_hit: dict[str, float] = {}
        empty_rounds = 0
        thr = await flt.threshold()
        while not state["stop"] and datetime.now(tz) < until and stats["pages_seen"] < lim["max_pages_per_run"]:
            candidates = await db.fetch("select * from crawl_queue order by priority desc, added_at limit 60")
            if not candidates:
                if empty_rounds >= 5:
                    break
                empty_rounds += 1
                stats["searches"] += await discovery_round(run_id)
                continue
            now = time.monotonic()
            batch, domains = [], set()
            for c in candidates:
                d = inputs.domain_of(c["url"])
                if d in blocked:
                    await db.execute("delete from crawl_queue where url = %s", c["url"])
                    continue
                if d in domains or now - last_hit.get(d, 0) < lim["per_domain_delay_s"]:
                    continue
                batch.append(c)
                domains.add(d)
                if len(batch) >= 4:
                    break
            if not batch:
                await asyncio.sleep(1)
                continue
            for c in batch:
                await db.execute("delete from crawl_queue where url = %s", c["url"])
                last_hit[inputs.domain_of(c["url"])] = time.monotonic()
            batch = [c for c in batch if not await db.fetchrow("select 1 from pages where url = %s", c["url"])]
            if not batch:
                continue
            results = await services.crawl([c["url"] for c in batch])
            by_url = {c["url"]: c for c in batch}
            good = [r for r in results if r.get("ok") and len(r.get("markdown") or "") > 300]
            stats["errors"] += len(results) - len(good)
            if not good:
                continue
            scores = await flt.score([(r["title"], r["markdown"]) for r in good])
            for r, (rel, vec) in zip(good, scores):
                c = by_url.get(r["url"]) or {"depth": 0, "source_id": None}
                kept = rel >= thr
                src_id = c.get("source_id") or await _source_for(r["url"], None)
                if not await _store_page(run_id, r["url"], r["title"], r["markdown"], r["meta"], src_id, rel, kept, vec):
                    continue
                stats["pages_seen"] += 1
                await db.execute("update sources set score = score * 0.8 + %s * 0.2, last_crawled_at = now() "
                                 "where id = %s", max(rel, 0), src_id)
                if not kept:
                    continue
                stats["pages_kept"] += 1
                if c["depth"] < lim["max_depth"]:
                    for href in r["internal"][:40]:
                        await enqueue(href, c["depth"] + 1, rel, "link", src_id)
                    for href in r["external"][:20]:
                        d = inputs.domain_of(href)
                        if not d or d in blocked:
                            continue
                        if not await db.fetchrow("select 1 from sources where domain = %s", d):
                            new_id = await _source_for(href, src_id)
                            stats["new_sources"] += 1
                            await enqueue(href, c["depth"] + 1, rel * 0.8, "new_site", new_id)
            await db.execute("update crawl_runs set stats = %s where id = %s", db.Jsonb(stats), run_id)

        state["stop"] = True
        await asyncio.gather(yt_task, social_task, return_exceptions=True)
        stats["knowledge"] = await knowledge_task
        status = "finished"
    except Exception as e:  # noqa: BLE001
        log.exception("crawl run failed")
        stats["error"] = str(e)
        status = "failed"
    finally:
        await db.execute("update crawl_runs set status = %s, ended_at = now(), stats = %s where id = %s",
                         status if not state.get("stopped_by_user") else "stopped", db.Jsonb(stats), run_id)
        state.update(run_id=None, stop=False, stopped_by_user=False)
    return {"run_id": run_id, "status": status, **stats}


def start_background(trigger: str = "manual", until: datetime | None = None) -> bool:
    if state["run_id"] or (state["task"] and not state["task"].done()):
        return False
    state["task"] = asyncio.create_task(run(trigger, until))
    return True


def stop() -> bool:
    if not state["run_id"]:
        return False
    state["stop"] = True
    state["stopped_by_user"] = True
    return True
