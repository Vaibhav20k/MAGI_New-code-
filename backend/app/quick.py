"""MAGI's quick lane: one look at the knowledge, one fast answer.

The full agent (Hermes) makes several AI calls per turn, which is right when MAGI has to do
something but slow for a plain question. Here a question gets the matching knowledge passages and a
live snapshot of the system, and one fast model answers as MAGI. The quick lane can open a screen;
it cannot change anything. When the person asks MAGI to act, or the answer needs more than is on
the page, it hands the turn to the full agent.
"""

import asyncio
import json
import logging
import re
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import AsyncOpenAI

from . import brand, db, kb, magi
from .agents import crawler
from .config import get_settings

log = logging.getLogger("mai.quick")
SCREENS = ("home", "marketing_map", "marketing", "ideas", "content", "approvals", "crawler")
# If the person plainly asks for a screen and the model forgets to open it, it is opened anyway.
ASKS_TO_OPEN = re.compile(r"\b(?:open|show|see|pull up|bring up|go to|take me to|check|look at)\b", re.I)
SCREEN_WORDS = [("approvals", r"approval|approve|\bheld\b"), ("ideas", r"\bideas?\b"), ("content", r"\bcontent\b|\bblogs?\b|creatives?|\bvideos?\b|scripts?"),
                ("crawler", r"crawl"), ("marketing_map", r"(?:how|map).*(?:marketing|built)|\bagents\b"), ("marketing", r"marketing|dashboard"),
                ("home", r"\bhome\b|main screen|round table")]


def _asked_screen(message: str) -> str | None:
    if not ASKS_TO_OPEN.search(message) or len(message.split()) > 12:
        return None
    return next((name for name, words in SCREEN_WORDS if re.search(words, message, re.I)), None)
_history: dict[str, deque] = {}             # session → the last few turns, so follow-up questions make sense
_clients: list[tuple[str, str, AsyncOpenAI, dict]] | None = None

SYSTEM = """You are MAGI (said "Maggie"), the second brain of Magppie Kitchens: a woman's voice, calm, sure and warm,
like a trusted second CEO. You work for Vinod Jain, Founder and CEO of MAGPPIE, and his team. Your reply is spoken aloud.

Answer from KNOWLEDGE and SNAPSHOT only. Never describe the company from memory. If the answer is not there, say you do
not have it yet.

Only when asked who you are, or simply greeted, say exactly: "Hi, I am MAGI, the second brain of Magppie Kitchens. You
can ask me anything about us. I am always here for you." Otherwise never introduce yourself: answer at once.

Rules you never break:
- No em dashes or en dashes.
- MAGPPIE kitchens and wardrobes are built entirely from SILVERSTONE engineered stone infused with silver and copper.
  Zero wood. Never steel.
- No health claims: say only what the material physically does and does not contain. Never "cures", "kills",
  "prevents disease", "antibacterial", "cancer-safe".
- Ahimsa: termites and cockroaches find nothing to eat; they are not killed.
- Never speak badly of a named competitor.
- Passages marked "team only" (IPO, valuation, revenue, targets, hiring, leads) are internal: share them when asked and say
  they are internal.
- If a figure is an estimate or still to be confirmed, say so.
- Marketing is the only connected department. Sales, Pre-sales, Design, Factory, Clients, Finance, HR, Admin and Tech are
  not connected yet: say so plainly, then share what you know that helps.

How you speak: lead with the answer. Short declarative sentences. One to four sentences, or a very short list. No tables,
no headings. Say numbers the way a person would. Never offer a document, guide or feature that is not in KNOWLEDGE or
SNAPSHOT.

YOUR SCREENS (you can open exactly these seven):
- home: your own home screen, the round table with your brain.
- marketing_map: how the marketing department is built (its jobs, agents and tools).
- marketing: the marketing dashboard.
- ideas: the blog, creative and video ideas waiting for approval.
- content: the finished blogs, creatives and videos.
- approvals: the learnings held for the manager's review.
- crawler: the night crawler, its runs and the sites it found.

Reply with JSON only: {"reply": "...", "screen": null, "handoff": false}
- "screen": set it to one of YOUR SCREENS when the person asks to open, show, see, pull up, check or go to it. Open it and
  say in a sentence what is there, from SNAPSHOT (for example how many learnings wait for the manager, or which ideas are
  on the dashboard). Otherwise null. Opening a screen never needs a handoff.
- "handoff": true, with "reply" empty, ONLY when the person asks you to DO something that changes the system (get new
  ideas, approve or make content, start or stop the crawler, decide an approval, finalise the review, add knowledge, add
  a link, never use something), or when the person asks you to read out details that are not in KNOWLEDGE or SNAPSHOT
  (for example each item on the approval list, or last night's learnings one by one). The full agent then takes the turn."""


def _models() -> list[tuple[str, str, AsyncOpenAI, dict]]:
    """Fast brains in the order they are tried. Each answers in one short call."""
    global _clients
    if _clients is None:
        s, out = get_settings(), []
        if s.gemini_api_key:              # Gemini's light model answers in about a second; Groq is kept busy by the crawler
            g = AsyncOpenAI(api_key=s.gemini_api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                            timeout=8, max_retries=0)
            out += [("gemini", m, g, {}) for m in ("gemini-flash-lite-latest", "gemini-3.1-flash-lite")]
        if s.groq_api_key:
            out.append(("groq", s.groq_model, AsyncOpenAI(api_key=s.groq_api_key, base_url="https://api.groq.com/openai/v1",
                                                          timeout=8, max_retries=0), {}))
        if s.tokenharbor_api_key:
            t = AsyncOpenAI(api_key=s.tokenharbor_api_key, base_url="https://tokenharbor.ai/v1", timeout=10, max_retries=0)
            out.append(("tokenharbor", "qwen3.8-flash:free", t, {"reasoning_effort": "none"}))
        _clients = out
    return _clients


async def _snapshot() -> str:
    c = await db.fetchrow("""select
        (select count(*) from kb_chunks where active) knowledge_pieces,
        (select count(*) from pages) pages_read, (select count(*) from pages where kept) pages_kept,
        (select count(*) from sources) sites_known,
        (select count(*) from learnings where status in ('active','approved')) learnings_in_use,
        (select count(*) from learnings where status = 'pending') learnings_waiting_for_a_second_source,
        (select count(*) from learnings where status = 'held') learnings_waiting_for_the_manager,
        (select count(*) from ideas where status = 'finalising') ideas_being_made,
        (select count(*) from creatives where status in ('writing','generating')) creatives_being_made,
        (select count(*) from videos where status in ('writing','lookbook','prompting','generating')) videos_being_made,
        (select status from idea_batches order by id desc limit 1) last_idea_run""")
    run = await db.fetchrow("select status, started_at, stats from crawl_runs order by id desc limit 1")
    ideas = await db.fetch("select type, title, status from ideas where batch_id = (select max(id) from idea_batches) "
                           "and status <> 'candidate' order by type")
    blogs = await db.fetch("select title from blogs order by id desc limit 4")
    creatives = await db.fetch("select brief->>'title' title, status from creatives order by id desc limit 4")
    videos = await db.fetch("select script->'final_script'->>'title' title, status from videos order by id desc limit 4")
    crawling = bool(crawler.state["run_id"])
    busy = [n for n, on in (("crawler, filter and knowledge agent", crawling),
                            ("strategist", c["last_idea_run"] == "running"), ("blog writer", c["ideas_being_made"]),
                            ("art director", c["creatives_being_made"]), ("video team", c["videos_being_made"])) if on]
    snap = {
        "time_in_india": datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%A %d %B %Y, %I:%M %p"),
        "counts": dict(c),
        "crawler": {"running_now": crawling, "schedule": "every night 8 PM to 8 AM", "this_run": (run or {}).get("stats")},
        "agents_working_now": busy or "none; everyone is idle",
        "departments": [{"name": d["name"], "connected": bool(d.get("live"))} for d in magi.departments()],
        "ideas_on_the_dashboard": [dict(i) for i in ideas],
        "finished_blogs": [b["title"] for b in blogs],
        "creatives": [dict(x) for x in creatives], "videos": [dict(x) for x in videos],
    }
    return json.dumps(snap, default=str, ensure_ascii=False)


async def answer(message: str, session: str) -> dict | None:
    """A reply from the quick lane, or None when the full agent should take the turn."""
    began = time.time()
    try:
        rows, snap = await asyncio.gather(kb.search(message, k=6), _snapshot())
    except Exception as e:  # noqa: BLE001 — the quick lane is an extra; the full agent still works
        log.warning("quick lane could not read the knowledge: %s", e)
        return None
    passages = "\n\n".join(f"[{'team only' if r['doc'] == 'internal' else r['doc']} · {r['section'] or ''}]\n{r['content'][:900]}"
                           for r in rows)
    past = _history.setdefault(session, deque(maxlen=6))
    messages = [{"role": "system", "content": SYSTEM}, *past,
                {"role": "user", "content": f"KNOWLEDGE:\n{passages}\n\nSNAPSHOT:\n{snap}\n\nTHE PERSON SAYS: {message}"}]
    for provider, model, client, extra in _models():
        try:
            r = await client.chat.completions.create(model=model, messages=messages, temperature=0.4, max_tokens=500,
                                                     response_format={"type": "json_object"}, extra_body=extra or None)
            data = json.loads(r.choices[0].message.content or "{}")
        except Exception as e:  # noqa: BLE001 — busy or limited: the next fast brain gets the question
            log.info("quick lane: %s:%s passed (%s)", provider, model, str(e)[:100])
            continue
        if data.get("handoff"):
            log.info("quick lane hands over to the full agent (%.1fs)", time.time() - began)
            return None
        reply = brand.clean(str(data.get("reply") or "")).strip()
        if not reply:
            continue
        screen = data.get("screen") if data.get("screen") in SCREENS else _asked_screen(message)
        past.append({"role": "user", "content": message})
        past.append({"role": "assistant", "content": json.dumps({"reply": reply, "screen": screen, "handoff": False})})
        log.info("quick lane answered with %s:%s in %.1fs", provider, model, time.time() - began)
        return {"reply": reply, "actions": [screen] if screen else [], "lane": "quick"}
    return None


def remember(session: str, message: str, reply: str) -> None:
    """Keep what the full agent said too, so the quick lane can follow the conversation."""
    past = _history.setdefault(session, deque(maxlen=6))
    past.append({"role": "user", "content": message})
    past.append({"role": "assistant", "content": json.dumps({"reply": reply[:600], "screen": None, "handoff": False})})
