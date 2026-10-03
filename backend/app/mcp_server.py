"""The tools MAGI (Hermes Agent) can use. Each one wraps something the dashboard can also do."""

import asyncio
import json
import time

from mcp.server.fastmcp import FastMCP

from . import cognee_sync, db, kb, llm
from .agents import crawler, ideas, knowledge

try:
    from mcp.server.transport_security import TransportSecuritySettings
    _security = {"transport_security": TransportSecuritySettings(enable_dns_rebinding_protection=False)}
except Exception:  # noqa: BLE001 — older SDKs have no such setting
    _security = {}

mcp = FastMCP("marketing-mai", stateless_http=True, json_response=True, streamable_http_path="/", **_security)


def _j(o) -> str:
    return json.dumps(o, default=str, ensure_ascii=False)


SCREENS = ("home", "marketing_map", "marketing", "ideas", "content", "approvals", "crawler")
ui_actions: list[tuple[float, str]] = []      # screens MAGI asked to open; the chat reply carries them to the page


def take_ui_actions(since: float) -> list[str]:
    """The screens opened since a moment in time; older ones are dropped."""
    out = [s for t, s in ui_actions if t >= since]
    ui_actions.clear()
    return out


@mcp.tool()
async def open_screen(screen: str) -> str:
    """Open a screen for the person you are talking to. screen is one of:
    home (your own home screen, the brain), marketing_map (how the marketing department is built: its jobs,
    agents and tools), marketing (the marketing dashboard), ideas, content, approvals, crawler (tabs of the
    marketing dashboard)."""
    s = screen.strip().lower().replace(" ", "_")
    if s not in SCREENS:
        return _j({"opened": False, "reason": f"Unknown screen. Choose one of: {', '.join(SCREENS)}"})
    ui_actions.append((time.time(), s))
    return _j({"opened": s})


@mcp.tool()
async def team_status() -> str:
    """Who is working right now and who is idle: every agent of the marketing department with its state
    and latest work, which departments are connected, and which AI brains are available."""
    from . import magi
    c = await db.fetchrow("""select
        (select count(*) from ideas where status = 'finalising' and type = 'blog') blogs_being_written,
        (select count(*) from creatives where status in ('writing','generating')) creatives_being_made,
        (select count(*) from videos where status in ('writing','lookbook','prompting')) scripts_being_written,
        (select count(*) from videos where status = 'generating') videos_being_made,
        (select count(*) from videos where status = 'script_ready') scripts_waiting_for_approval,
        (select count(*) from ideas where status = 'proposed') ideas_waiting_for_approval,
        (select count(*) from learnings where status = 'held') learnings_waiting_for_the_manager,
        (select status from idea_batches order by id desc limit 1) last_idea_run,
        (select count(*) from pages where kept and not processed) pages_waiting_to_be_learned_from""")
    run = await db.fetchrow("select status, started_at, ended_at, stats from crawl_runs order by id desc limit 1")
    crawling = bool(crawler.state["run_id"])
    work = lambda busy, what: f"working: {what}" if busy else "idle"
    agents = {
        "crawler": "working: reading the web now" if crawling else "idle until 8 PM (it runs every night, 8 PM to 8 AM)",
        "filter": "working with the crawler" if crawling else "idle",
        "knowledge agent": work(crawling or c["pages_waiting_to_be_learned_from"], "turning pages into learnings"),
        "strategist": work(c["last_idea_run"] == "running", "choosing new ideas"),
        "blog writer": work(c["blogs_being_written"], f"{c['blogs_being_written']} blog"),
        "art director": work(c["creatives_being_made"], f"{c['creatives_being_made']} creative"),
        "video team": work(c["scripts_being_written"] or c["videos_being_made"], "a script or a video"),
    }
    try:
        knowledge_map = (await cognee_sync.status()).get("state")
    except Exception:  # noqa: BLE001
        knowledge_map = "not reachable"
    return _j({"agents": agents, "last_crawl": run, "waiting_for_people": {
                   "ideas to approve": c["ideas_waiting_for_approval"], "scripts to approve": c["scripts_waiting_for_approval"],
                   "learnings for the manager": c["learnings_waiting_for_the_manager"]},
               "departments": [{"name": d["name"], "connected": bool(d.get("live"))} for d in magi.departments()],
               "ai_brains_available": [p.provider for p in llm.providers()], "knowledge_map": knowledge_map})


@mcp.tool()
async def system_status() -> str:
    """Current state of the marketing system: knowledge base size, crawler state, pages read, learnings,
    items waiting for the manager's approval."""
    c = await db.fetchrow("""select
        (select count(*) from kb_chunks where active and doc = 'core') company_knowledge_passages,
        (select count(*) from kb_chunks where active and doc = 'learned') learned_passages,
        (select count(*) from sources where status in ('seed','trusted')) trusted_sites,
        (select count(*) from sources where status = 'discovered') discovered_sites,
        (select count(*) from pages) pages_read, (select count(*) from pages where kept) pages_relevant,
        (select count(*) from learnings where status in ('active','approved')) confirmed_learnings,
        (select count(*) from learnings where status = 'pending') waiting_for_second_source,
        (select count(*) from learnings where status = 'held') waiting_for_manager_approval""")
    return _j({**c, "crawler_running_now": bool(crawler.state["run_id"])})


@mcp.tool()
async def overnight_summary() -> str:
    """What the most recent crawl did: pages read, sites found, and the newest things MAI learned."""
    run = await db.fetchrow("select id, trigger, status, started_at, ended_at, stats from crawl_runs "
                            "order by id desc limit 1")
    if not run:
        return "No crawl has run yet."
    learned = await db.fetch(
        "select kind, coalesce(edited_content, content) learning from learnings "
        "where status in ('active','approved') order by created_at desc limit 8")
    sites = await db.fetch("select domain from sources where status = 'discovered' and score > 0.1 "
                           "order by score desc limit 8")
    held = (await db.fetchrow("select count(*) c from learnings where status = 'held'"))["c"]
    return _j({"run": run, "newest_learnings": learned, "best_new_sites": [s["domain"] for s in sites],
               "waiting_for_manager_approval": held})


@mcp.tool()
async def search_company_knowledge(question: str) -> str:
    """Look up everything the company knows: what MAGPPIE is, its story, SILVERSTONE and its features, the
    guarantee, awards, people, ecosystem, markets, campaigns, team-only matters and what was learned from the web.
    Use this before stating any fact about the company. Passages marked "team only" are internal."""
    rows = await kb.search(question, k=7)
    return _j([{"id": r["id"], "from": "team only" if r["doc"] == "internal" else r["doc"], "section": r["section"],
                "text": r["content"][:900]} for r in rows])


@mcp.tool()
async def connected_knowledge(question: str) -> str:
    """Answer questions about how things relate, using the knowledge map (Cognee): which competitors push
    the same trend, what links several learnings, how a trend connects to our products. Slower than
    search_company_knowledge; use it for "how are these connected" questions, not simple fact lookups."""
    try:
        r = await cognee_sync.search(question)
    except Exception as e:  # noqa: BLE001
        return f"The knowledge map is not available right now ({str(e)[:120]}). Use search_company_knowledge instead."
    return _j({"answer": r.get("answer"), "supporting_passages": (r.get("results") or [])[:5], "note": r.get("note")})


def _brief(i: dict) -> dict:
    return {"id": i["id"], "type": i["type"], "title": i["title"], "summary": i["summary"],
            "why_it_fits": i["angle"], "status": i["status"],
            "inspired_by": [x.get("url") or x.get("learning") for x in (i["inspired_by"] or [])][:3]}


@mcp.tool()
async def current_ideas() -> str:
    """The latest set of content ideas (2 blog, 2 creative, 2 video) already on the dashboard."""
    data = await ideas.latest()
    return _j({"batch_status": (data["batch"] or {}).get("status"), "ideas": [_brief(i) for i in data["ideas"]]})


@mcp.tool()
async def generate_new_ideas() -> str:
    """Make a fresh set of 6 content ideas (same as pressing Crawl on the dashboard). Takes about a minute.
    Ideas shown before are never repeated."""
    batch_id = await ideas.new_batch()
    result = await asyncio.wait_for(ideas.generate_batch(batch_id), timeout=240)
    if result.get("error"):
        return f"Idea generation failed: {result['error']}"
    data = await ideas.latest()
    return _j({"ideas": [_brief(i) for i in data["ideas"]]})


@mcp.tool()
async def produce_content(idea_ids: list[int]) -> str:
    """Turn chosen ideas into finished content (same as pressing Finalise). Blog ideas become full blogs,
    creative ideas become briefs with image prompts. Only call this when the user clearly asks for it."""
    from .main import _produce, spawn
    rows = await db.fetch("select id, title from ideas where id = any(%s) and status in ('proposed','selected')",
                          idea_ids)
    for r in rows:
        await db.execute("update ideas set status = 'finalising' where id = %s", r["id"])
        spawn(_produce(r["id"]))
    return _j({"started": [r["title"] for r in rows],
               "note": "Blogs take a few minutes. They appear on the dashboard when ready."})


@mcp.tool()
async def finished_content() -> str:
    """List finished blogs and creatives, and anything still being produced."""
    blogs = await db.fetch("select id, title, meta_description, created_at from blogs order by id desc limit 6")
    creatives = await db.fetch("select id, brief->>'title' title, brief->>'headline' headline, status "
                               "from creatives order by id desc limit 6")
    busy = await db.fetch("select type, title from ideas where status = 'finalising'")
    return _j({"blogs": blogs, "creatives": creatives, "in_progress": busy})


@mcp.tool()
async def approval_list(limit: int = 8) -> str:
    """Doubtful learnings held for the manager. None of them is used until approved."""
    rows = (await knowledge.held_items())[:limit]
    total = (await db.fetchrow("select count(*) c from learnings where status = 'held'"))["c"]
    return _j({"total_waiting": total, "items": [
        {"id": r["id"], "learning": r["content"], "why_held": r["rule"], "affects": r["affects"],
         "source": (r["source_urls"] or [None])[0], "decision_so_far": r["manager_note"]} for r in rows]})


@mcp.tool()
async def decide_approval(learning_id: int, action: str, edited_text: str = "") -> str:
    """Record the manager's decision on one held learning. action is "approve", "reject" or "edit"
    (with edited_text). Decisions take effect only after finalise_review."""
    await knowledge.decide(learning_id, action, edited_text or None)
    return f"Recorded: {action} for item {learning_id}. Say 'finalise review' to apply all decisions."


@mcp.tool()
async def finalise_review() -> str:
    """Apply all recorded approval decisions: approved items join the knowledge base, rejected ones are
    remembered and never asked again. Only call this when the manager says to finalise."""
    return _j(await knowledge.finalise_review())


@mcp.tool()
async def start_crawl(minutes: int = 0) -> str:
    """Start the crawler now. minutes = how long to run (0 means until 8 AM)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    until = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(minutes=minutes) if minutes else None
    return "Crawler started." if crawler.start_background("manual", until) else "A crawl is already running."


@mcp.tool()
async def stop_crawl() -> str:
    """Stop the crawler."""
    return "Crawler stopping." if crawler.stop() else "No crawl is running."


@mcp.tool()
async def add_inspiration_link(url: str) -> str:
    """Queue a link the user likes (a post, article or video) to be read with top priority."""
    await crawler.enqueue(url, 0, 2.0, "pasted")
    return "Queued. It will be read on the next crawl."


@mcp.tool()
async def add_company_knowledge(text: str) -> str:
    """Add a fact to the company knowledge base on the manager's instruction."""
    await db.execute("insert into manager_rules (kind, content) values ('add_knowledge', %s)", text)
    await kb.add_manager_knowledge(text)
    return "Added to the knowledge base."


@mcp.tool()
async def never_use(text: str) -> str:
    """Record a topic, word or claim MAI must never use in ideas or content."""
    await db.execute("insert into manager_rules (kind, content) values ('never_use', %s)", text)
    return "Noted. It will not be used."
