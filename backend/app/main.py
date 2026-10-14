"""Marketing MAI backend: API for the dashboard, the schedule, and the agents."""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import httpx

from . import db, inputs, kb, llm
from .agents import blog, crawler, creative, ideas, knowledge, video
from .agents import filter as flt
from .config import get_settings
from .mcp_server import mcp as mai_tools
from .voice import router as voice_router
from . import auth, bloom, brand, cognee_sync, higgsfield, keys, media, quick, script_engine
from .higgsfield import router as higgsfield_router
from .magi import router as magi_router
from . import references

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mai")
settings = get_settings()
TZ = ZoneInfo(settings.timezone)
scheduler = AsyncIOScheduler(timezone=TZ)
_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


async def notify(kind: str, title: str, body: str = "") -> None:
    await db.execute("insert into notifications (kind, title, body) values (%s,%s,%s)", kind, title, body)


async def night_crawl():
    result = await crawler.run("schedule")
    k = result.get("knowledge") or {}
    await notify("crawl", "Overnight crawl finished",
                 f"{result.get('pages_seen', 0)} pages read, {result.get('pages_kept', 0)} kept, "
                 f"{k.get('active', 0)} new learnings, {k.get('held', 0)} waiting for approval, "
                 f"{result.get('new_sources', 0)} new sites found.")


async def review_reminder():
    n = (await db.fetchrow("select count(*) c from learnings where status = 'held'"))["c"]
    if n:
        await notify("review", f"{n} learnings are waiting for approval",
                     f"{settings.manager_name or 'Manager'}: review them and press Finalise review.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.open_pool()
    keys.load()
    try:
        # anything a restart interrupted is marked as such, so the dashboard does not wait forever
        await db.execute("update idea_batches set status = 'failed', error = 'Interrupted by a restart.' "
                         "where status = 'running'")
        await db.execute("update crawl_runs set status = 'stopped', ended_at = now() where status = 'running'")
        await db.execute("update ideas set status = 'proposed' where status = 'finalising'")
        await db.execute("update videos set status = 'failed', error = 'Interrupted by a restart.' "
                         "where status in ('writing','generating')")
        # a lookbook or a set of video prompts that was being made: back one step, to be asked for again
        await db.execute("update videos set status = 'script_ready', script = script - 'stage', "
                         "error = 'Interrupted by a restart. Approve the script again.' where status = 'lookbook'")
        await db.execute("update videos set status = 'lookbook_ready', script = script - 'stage', "
                         "error = 'Interrupted by a restart. Approve the lookbook again.' where status = 'prompting'")
        await db.execute("update creatives set status = 'failed', error = 'Interrupted by a restart.' "
                         "where status in ('writing','generating')")
        if not (await db.fetchrow("select count(*) c from kb_chunks where doc = 'core'"))["c"]:
            await kb.load_inputs()
        await inputs.sync_seed_sources()
    except Exception:  # noqa: BLE001
        log.exception("startup load failed")
    scheduler.add_job(night_crawl, "cron", hour=20, minute=0, id="night_crawl")
    scheduler.add_job(review_reminder, "cron", hour=18, minute=0, id="review_reminder")
    scheduler.add_job(knowledge.housekeeping, "cron", hour=8, minute=5, id="housekeeping")
    scheduler.add_job(cognee_sync.sync, "cron", hour=8, minute=10, id="cognee_sync")
    scheduler.add_job(references.sync, "cron", hour=7, minute=30, id="reference_sync")   # new Drive pictures, after the crawl
    scheduler.start()
    async with mai_tools.session_manager.run():      # MAI's tools (MCP) live as long as the app
        yield
    scheduler.shutdown(wait=False)
    await db.close_pool()


app = FastAPI(title="Marketing MAI", lifespan=lifespan)
app.include_router(keys.router)
app.add_middleware(auth.Gate)              # visitors from the internet need a login; see app/auth.py
app.include_router(auth.router)
app.include_router(voice_router)
app.include_router(higgsfield_router)
app.include_router(magi_router)
app.include_router(references.router)


# ---------------- Status ----------------

@app.get("/api/status")
async def status():
    counts = await db.fetchrow("""select
        (select count(*) from kb_chunks where active and doc = 'core') kb_core,
        (select count(*) from kb_chunks where active and doc = 'learned') kb_learned,
        (select count(*) from kb_chunks where active and doc = 'script_bank') scripts,
        (select count(*) from sources where status in ('seed','trusted')) seed_sources,
        (select count(*) from sources where status = 'discovered') discovered_sources,
        (select count(*) from pages) pages, (select count(*) from pages where kept) pages_kept,
        (select count(*) from learnings where status in ('active','approved')) learnings,
        (select count(*) from learnings where status = 'pending') pending,
        (select count(*) from learnings where status = 'held') held,
        (select count(*) from crawl_queue) queued""")
    run = await db.fetchrow("select * from crawl_runs order by id desc limit 1")
    return {"counts": counts, "crawl_running": bool(crawler.state["run_id"]), "last_run": run,
            "brains": [p.provider for p in llm.providers()], "manager": settings.manager_name,
            "now": datetime.now(TZ).isoformat()}


@app.post("/api/kb/reload")
async def kb_reload():
    counts = await kb.load_inputs()
    seeds = await inputs.sync_seed_sources()
    await flt.load_profiles()
    return {"loaded": counts, "seed_sources": seeds}


class Ask(BaseModel):
    question: str


@app.post("/api/kb/ask")
async def kb_ask(a: Ask):
    rows = await kb.search(a.question, k=8)
    answer = await llm.complete(
        "Answer from the KNOWLEDGE only. If it is not there, say you don't have that in the knowledge base. "
        "Be brief.", f"KNOWLEDGE:\n{kb.as_context(rows)}\n\nQUESTION: {a.question}", fast=True, temperature=0.2)
    return {"answer": answer, "sources": [{"id": r["id"], "doc": r["doc"], "section": r["section"]} for r in rows]}


# ---------------- Crawler ----------------

class CrawlStart(BaseModel):
    minutes: int | None = None


@app.post("/api/crawl/start")
async def crawl_start(c: CrawlStart):
    until = datetime.now(TZ) + timedelta(minutes=c.minutes) if c.minutes else None
    if not crawler.start_background("manual", until):
        raise HTTPException(409, "A crawl is already running.")
    return {"started": True, "until": until.isoformat() if until else "08:00"}


@app.post("/api/crawl/stop")
async def crawl_stop():
    return {"stopping": crawler.stop()}


@app.get("/api/crawl/runs")
async def crawl_runs():
    return await db.fetch("select * from crawl_runs order by id desc limit 14")


@app.get("/api/sources")
async def sources():
    return await db.fetch("select id, url, domain, kind, status, round(score::numeric, 3) score, last_crawled_at "
                          "from sources order by status = 'seed' desc, score desc limit 300")


class SourceStatus(BaseModel):
    status: str


@app.post("/api/sources/{source_id}")
async def source_set(source_id: int, s: SourceStatus):
    if s.status not in ("trusted", "blocked", "discovered"):
        raise HTTPException(400, "status must be trusted, blocked or discovered")
    await db.execute("update sources set status = %s where id = %s", s.status, source_id)
    return {"ok": True}


class Link(BaseModel):
    url: str


@app.post("/api/inspiration")
async def inspiration(l: Link):
    """Paste a link you like; it is read on the next crawl with top priority."""
    await crawler.enqueue(l.url, 0, 2.0, "pasted")
    return {"queued": True}


@app.get("/api/learnings")
async def learnings(status: str = "active", limit: int = 100):
    wanted = ["active", "approved"] if status == "active" else [status]
    return await db.fetch(
        "select id, coalesce(edited_content, content) content, kind, status, source_urls, source_count, "
        "created_at from learnings where status = any(%s) order by created_at desc limit %s", wanted, limit)


# ---------------- Manager review ----------------

@app.get("/api/review")
async def review_list():
    return await knowledge.held_items()


class Decision(BaseModel):
    action: str
    content: str | None = None
    note: str | None = None


@app.post("/api/review/item/{learning_id}")
async def review_decide(learning_id: int, d: Decision):
    try:
        await knowledge.decide(learning_id, d.action, d.content, d.note)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


class Rule(BaseModel):
    kind: str
    content: str


@app.post("/api/review/rule")
async def review_rule(r: Rule):
    if r.kind not in ("add_knowledge", "never_use", "block_site", "trust_site"):
        raise HTTPException(400, "unknown rule kind")
    await db.execute("insert into manager_rules (kind, content) values (%s,%s)", r.kind, r.content)
    if r.kind == "add_knowledge":
        await kb.add_manager_knowledge(r.content)
    elif r.kind in ("block_site", "trust_site"):
        dom = inputs.domain_of(r.content) or r.content.strip().lower()
        await db.execute("update sources set status = %s where domain = %s",
                         "blocked" if r.kind == "block_site" else "trusted", dom)
    return {"ok": True}


@app.post("/api/review/finalise")
async def review_finalise():
    out = await knowledge.finalise_review()
    await flt.load_profiles()
    return out


# ---------------- Ideas (the Crawl button) ----------------

@app.post("/api/ideas/generate")
async def ideas_generate():
    batch_id = await ideas.new_batch()
    spawn(ideas.generate_batch(batch_id))
    return {"batch_id": batch_id}


@app.get("/api/ideas/latest")
async def ideas_latest():
    return await ideas.latest()


class Finalise(BaseModel):
    idea_ids: list[int]


async def _hf_connected() -> bool:
    return bool(higgsfield._load().get("access_token"))


async def _make_image(creative_id: int):
    """Render a creative and tell the dashboard when it is done."""
    ok = await creative.generate(creative_id)
    c = await db.fetchrow("select brief->>'title' title, error from creatives where id = %s", creative_id)
    if ok:
        await notify("done", "Creative ready", f"\"{c['title']}\" is on the Content tab.")
    else:
        await notify("error", f"Could not make the image for \"{c['title']}\"", (c["error"] or "")[:300])


async def _make_video(video_id: int):
    ok = await video.generate(video_id)
    v = await db.fetchrow("select script->'final_script'->>'title' title, error from videos where id = %s", video_id)
    if ok:
        await notify("done", "Video ready", f"\"{v['title']}\" is on the Content tab.")
    else:
        await notify("error", f"Could not make the video \"{v['title']}\"", (v["error"] or "")[:300])


async def _produce(idea_id: int):
    """What an approved idea turns into.
    blog     → the full blog
    creative → the finished image in the approved kind (story, poster, post), if Higgsfield is connected
    video    → the script from the team's script tool; the video itself needs a second approval
    """
    idea = await db.fetchrow("select id, type, title from ideas where id = %s", idea_id)
    try:
        if idea["type"] == "blog":
            await blog.write(idea_id)
            await notify("done", "Blog ready", f"\"{idea['title']}\" is on the Content tab.")
        elif idea["type"] == "creative":
            creative_id = await creative.write(idea_id)
            await db.execute("update ideas set status = 'finalised' where id = %s", idea_id)
            if await _hf_connected():
                await _make_image(creative_id)
        else:
            await video.write_script(idea_id)
            await notify("done", "Script ready for your approval", f"\"{idea['title']}\" is on the Content tab.")
        await db.execute("update ideas set status = 'finalised' where id = %s", idea_id)
    except Exception as e:  # noqa: BLE001
        log.exception("producing idea %s failed", idea_id)
        await db.execute("update ideas set status = 'selected' where id = %s", idea_id)
        await notify("error", f"Could not produce \"{idea['title']}\"", str(e)[:300])


async def _start(idea_ids: list[int]) -> list[int]:
    rows = await db.fetch("select id from ideas where id = any(%s) and status in ('proposed','selected')",
                          idea_ids)
    for r in rows:
        await db.execute("update ideas set status = 'finalising' where id = %s", r["id"])
        spawn(_produce(r["id"]))
    return [r["id"] for r in rows]


class Words(BaseModel):
    brief: dict | None = None        # the words and kind of a creative, as edited on the card


@app.post("/api/ideas/{idea_id}/approve")
async def idea_approve(idea_id: int, w: Words | None = None):
    """Approve one idea: MAI starts making it. A creative is made with the words as edited on its card."""
    if w and w.brief:
        fields = creative.clean(w.brief)
        if not fields.get("headline", "x"):
            raise HTTPException(400, "The headline cannot be empty.")
        await db.execute("update ideas set payload = coalesce(payload, '{}'::jsonb) || %s where id = %s "
                         "and type = 'creative' and status in ('proposed','selected')", db.Jsonb(fields), idea_id)
    started = await _start([idea_id])
    if not started:
        raise HTTPException(400, "This idea was already approved or set aside.")
    return {"started": started}


@app.post("/api/ideas/{idea_id}/reject")
async def idea_reject(idea_id: int):
    await db.execute("update ideas set status = 'rejected' where id = %s and status in ('proposed','selected')",
                     idea_id)
    return {"ok": True}


@app.post("/api/finalise")
async def finalise(f: Finalise):
    started = await _start(f.idea_ids)
    if not started:
        raise HTTPException(400, "No ideas to finalise.")
    return {"started": started}


@app.post("/api/creatives/{creative_id}/generate")
async def creative_generate(creative_id: int, w: Words | None = None):
    """Make (or remake) the image for a creative, with changed words if given. Spends Higgsfield credits."""
    if not await _hf_connected():
        raise HTTPException(409, "Connect Higgsfield first.")
    c = await db.fetchrow("select status from creatives where id = %s", creative_id)
    if not c or c["status"] in ("writing", "generating"):
        raise HTTPException(409, "This creative is still being made.")
    if w and w.brief:
        if not creative.clean(w.brief).get("headline", "x"):
            raise HTTPException(400, "The headline cannot be empty.")
        await creative.reword(creative_id, w.brief)
    await db.execute("update creatives set status = 'generating', error = null, started_at = now() where id = %s",
                     creative_id)
    spawn(_make_image(creative_id))
    return {"started": True}


VIDEO_OPTIONS = [(8, "720p"), (15, "480p"), (30, "480p")]     # the lengths and qualities the team has used


class VideoChoice(BaseModel):
    duration: int | None = None
    resolution: str | None = None


def _engine_video(video_id: int, v: dict | None, status: str) -> str:
    """The engine run behind a video that stands at this step; anything else is refused in plain words."""
    run_id = ((v or {}).get("script") or {}).get("engine", {}).get("run_id")
    if not v or v["status"] != status or not run_id:
        raise HTTPException(400, "This video is not at that step.")
    return run_id


def _package_first(script: dict) -> None:
    """A script from the engine reaches Higgsfield only as a complete production package."""
    if (script.get("engine") or {}).get("run_id") and not script.get("higgsfield"):
        raise HTTPException(400, "Approve the script and the lookbook first: the video prompt comes after them.")


async def _video_step(job, video_id: int, done: str, failed: str):
    ok = await job
    v = await db.fetchrow("select script->'final_script'->>'title' title, error from videos where id = %s", video_id)
    if ok:
        await notify("done", done, f"\"{v['title']}\" is on the Content tab.")
    else:
        await notify("error", f"{failed} \"{v['title']}\"", (v["error"] or "")[:300])


class Changes(BaseModel):
    feedback: str = ""


class Decision(BaseModel):
    decision: str
    feedback: str = ""


@app.post("/api/videos/{video_id}/script-changes")
async def video_script_changes(video_id: int, c: Changes):
    """Ask the script engine to change the script once. Spends nothing on Higgsfield."""
    v = await db.fetchrow("select script, status from videos where id = %s", video_id)
    _engine_video(video_id, v, "script_ready")
    if len(c.feedback.strip()) < 8:
        raise HTTPException(400, "Say what should change, in a sentence.")
    if not v["script"]["engine"].get("revisions_left", 1):
        raise HTTPException(400, "This script has already been rewritten once. Approve it, or approve the idea again for a new one.")
    await db.execute("update videos set status = 'writing', error = null, started_at = now() where id = %s", video_id)
    spawn(_video_step(video.revise_script(video_id, c.feedback.strip()), video_id,
                      "Script rewritten for your approval", "Could not change the script of"))
    return {"started": True}


@app.post("/api/videos/{video_id}/approve-script")
async def video_approve_script(video_id: int):
    """Approve the script: it is locked and the lookbook is drawn up. Spends nothing on Higgsfield."""
    v = await db.fetchrow("select script, status from videos where id = %s", video_id)
    _engine_video(video_id, v, "script_ready")
    await db.execute("update videos set status = 'lookbook', error = null, started_at = now() where id = %s", video_id)
    spawn(_video_step(video.make_lookbook(video_id), video_id,
                      "Lookbook ready for your approval", "Could not make the lookbook for"))
    return {"started": True}


@app.post("/api/videos/{video_id}/lookbook/decision")
async def video_lookbook_decision(video_id: int, d: Decision):
    """Approve the lookbook (the video prompts follow) or ask for changes to it. Spends nothing on Higgsfield."""
    v = await db.fetchrow("select script, status from videos where id = %s", video_id)
    _engine_video(video_id, v, "lookbook_ready")
    if d.decision not in ("APPROVE", "REQUEST_CHANGES"):
        raise HTTPException(400, "The decision is APPROVE or REQUEST_CHANGES.")
    book = v["script"].get("lookbook") or {}
    if d.decision == "REQUEST_CHANGES":
        if len(d.feedback.strip()) < 8:
            raise HTTPException(400, "Say what should change, in a sentence.")
        if book.get("status") == "APPROVED" or not book.get("changes_left", 1):
            raise HTTPException(400, "This lookbook cannot be changed again. Approve it to go on.")
    approve = d.decision == "APPROVE"
    await db.execute("update videos set status = %s, error = null, started_at = now() where id = %s",
                     "prompting" if approve else "lookbook", video_id)
    spawn(_video_step(video.decide_lookbook(video_id, d.decision, d.feedback.strip()), video_id,
                      "Production package complete" if approve else "Lookbook redrawn for your approval",
                      "Could not write the video prompts for" if approve else "Could not change the lookbook of"))
    return {"started": True}


@app.get("/api/videos/{video_id}/files/{name}")
async def video_file(video_id: int, name: str):
    """The engine's own production files for a video: the lookbook page, the video prompts, the Edit Sheet."""
    v = await db.fetchrow("select script from videos where id = %s", video_id)
    run_id = ((v or {}).get("script") or {}).get("engine", {}).get("run_id")
    path = script_engine.artifact(run_id, name) if run_id else None
    if not path:
        raise HTTPException(404, "That file does not exist for this video.")
    return FileResponse(path, media_type=script_engine.FILES[name], headers={"Cache-Control": "no-store"},
                        filename=None if name.endswith(".html") else f"video-{video_id}-{name}")


@app.post("/api/videos/{video_id}/quote")
async def video_quote(video_id: int):
    """The Higgsfield prompt for this script and what each length would cost. Generates nothing."""
    if not await _hf_connected():
        raise HTTPException(409, "Connect Higgsfield first.")
    v = await db.fetchrow("select script, status from videos where id = %s", video_id)
    if not v or not (v["script"] or {}).get("final_script"):
        raise HTTPException(400, "The script is not ready yet.")
    _package_first(v["script"])
    plan = v["script"].get("higgsfield") or await video.direct(video_id)
    options = []
    for duration, resolution in VIDEO_OPTIONS:
        price = await media.cost("video", {**plan, "duration": duration, "resolution": resolution})
        options.append({"duration": duration, "resolution": resolution,
                        "credits": (price.get("cost") or {}).get("credits"),
                        "suggested": duration == plan["duration"] and resolution == plan["resolution"]})
    balance = await higgsfield.call("balance")
    return {"plan": plan, "options": options, "balance": balance.get("credits")}


@app.post("/api/videos/{video_id}/generate")
async def video_generate(video_id: int, choice: VideoChoice | None = None):
    """Approve a script: Higgsfield renders the video. Spends Higgsfield credits."""
    if not await _hf_connected():
        raise HTTPException(409, "Connect Higgsfield first.")
    v = await db.fetchrow("select script, status from videos where id = %s", video_id)
    if not v or v["status"] not in ("script_ready", "package_ready", "failed", "ready") \
            or not (v["script"] or {}).get("final_script"):
        raise HTTPException(400, "The script is not ready yet.")
    _package_first(v["script"])
    plan = v["script"].get("higgsfield") or await video.direct(video_id)
    if choice and choice.duration and choice.resolution:
        if (choice.duration, choice.resolution) not in VIDEO_OPTIONS:
            raise HTTPException(400, "Choose one of the offered lengths.")
        plan = {**plan, "duration": choice.duration, "resolution": choice.resolution}
        await db.execute("update videos set script = script || %s where id = %s",
                         db.Jsonb({"higgsfield": plan}), video_id)
    await db.execute("update videos set status = 'generating', error = null, started_at = now() where id = %s",
                     video_id)
    spawn(_make_video(video_id))
    return {"started": True, "plan": {k: plan[k] for k in ("duration", "resolution", "aspect_ratio")}}


class Plan(BaseModel):
    kind: str
    plan: dict


@app.post("/api/higgsfield/cost")
async def higgsfield_cost(p: Plan):
    """What a generation would cost in Higgsfield credits. Generates nothing."""
    if p.kind not in ("image", "video"):
        raise HTTPException(400, "kind must be image or video")
    return await media.cost(p.kind, p.plan)


@app.post("/api/videos/{video_id}/plan")
async def video_plan(video_id: int):
    """Preview the Higgsfield prompt and settings before spending credits."""
    return await video.direct(video_id)


@app.get("/api/content")
async def content():
    return {
        "blogs": await db.fetch("select b.*, i.title idea_title from blogs b left join ideas i on i.id = b.idea_id "
                                "order by b.id desc limit 30"),
        "creatives": await db.fetch("select c.*, i.title idea_title from creatives c left join ideas i "
                                    "on i.id = c.idea_id order by c.id desc limit 30"),
        "videos": await db.fetch("select v.*, i.title idea_title from videos v left join ideas i "
                                 "on i.id = v.idea_id order by v.id desc limit 30"),
        "in_progress": await db.fetch("select id, type, title from ideas where status = 'finalising'"),
    }


# ---------------- Bloom (creative direction, context only) ----------------

@app.get("/api/bloom/status")
async def bloom_status():
    return await bloom.status()


@app.post("/api/bloom/refresh")
async def bloom_refresh():
    """Read the Brand Skill from Bloom again (no image is made, no Bloom credit is spent)."""
    if not bloom.ready():
        raise HTTPException(409, "Add the Bloom key first.")
    try:
        s = await bloom.skill(force=True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Bloom is not reachable: {str(e)[:200]}") from e
    return {"brand": s and s["brand"], "files": s and [f["path"] for f in s["files"]]}


# ---------------- Cognee (connected knowledge) ----------------

@app.get("/api/cognee/status")
async def cognee_status():
    return await cognee_sync.status()


@app.post("/api/cognee/sync")
async def cognee_run():
    """Hand new knowledge to Cognee now instead of waiting for 8 AM."""
    try:
        return await cognee_sync.sync()
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Cognee is not reachable: {e}") from e


# ---------------- Notifications ----------------

@app.get("/api/notifications")
async def notifications(unread: bool = False):
    q = "select * from notifications " + ("where not read " if unread else "") + "order by id desc limit 40"
    return await db.fetch(q)


@app.post("/api/notifications/read")
async def notifications_read():
    await db.execute("update notifications set read = true where not read")
    return {"ok": True}


app.mount("/media", StaticFiles(directory=media.media_dir()), name="media")

STATIC = Path(__file__).resolve().parent.parent / "static"

# ---------------- MAI (Hermes Agent) ----------------

_mcp_app = mai_tools.streamable_http_app()


async def _guarded_mcp(scope, receive, send):
    """Only MAI, holding the internal token, may call the tools."""
    if scope["type"] == "http":
        auth = dict(scope["headers"]).get(b"authorization", b"").decode()
        if not settings.mcp_token or auth != f"Bearer {settings.mcp_token}":
            await send({"type": "http.response.start", "status": 401, "headers": []})
            await send({"type": "http.response.body", "body": b"unauthorized"})
            return
    await _mcp_app(scope, receive, send)


app.mount("/mcp", _guarded_mcp)


class Chat(BaseModel):
    message: str
    session: str = "dashboard"


@app.post("/api/mai/chat")
async def mai_chat(c: Chat):
    from .mcp_server import take_ui_actions
    began = time.time()
    fast = await quick.answer(c.message, c.session)      # a plain question is answered in one quick step
    if fast:
        return fast
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(
                f"{settings.hermes_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.hermes_api_key}",
                         "X-Hermes-Session-Id": c.session},
                json={"model": "hermes-agent", "messages": [{"role": "user", "content": c.message}]})
        if r.status_code != 200:
            raise HTTPException(502, f"MAI could not answer ({r.status_code}): {r.text[:300]}")
        reply = brand.clean(r.json()["choices"][0]["message"]["content"] or "") or "Done."
        quick.remember(c.session, c.message, reply)
        return {"reply": reply, "actions": take_ui_actions(began), "lane": "agent"}
    except httpx.HTTPError as e:
        raise HTTPException(502, f"MAI is not reachable: {e}") from e


@app.get("/mai")
async def mai_page():
    """The talking moved to the home screen: MAGI itself is the one you talk to."""
    return RedirectResponse("/")


# ---------------- Dashboard ----------------

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def home():
    """MAGI, the knowledge brain: the home screen every department hangs from."""
    return FileResponse(STATIC / "magi.html", headers={"Cache-Control": "no-store"})


@app.get("/marketing")
async def marketing():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})
