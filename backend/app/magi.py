"""MAGI — the knowledge brain on the home screen.

Everything the home screen draws is real: each dot is one piece of knowledge from the knowledge base,
each line joins a piece to the pieces closest to it in meaning, and each number is counted live.
The departments around the brain come from inputs/magi.json; only the ones marked live can be opened.
"""

import json
import logging
import time

from fastapi import APIRouter, HTTPException, UploadFile

from . import db, kb
from .agents import filter as flt
from .config import get_settings

log = logging.getLogger("mai.magi")
router = APIRouter(prefix="/api/magi")

MAX_DOTS = 360
DROP_TYPES = (".md", ".txt", ".csv")
DROP_BYTES = 2_000_000

DEPARTMENTS = [          # used when inputs/magi.json is missing
    {"key": "marketing", "name": "Marketing", "live": True, "opens": "/marketing"},
    {"key": "sales", "name": "Sales", "live": False},
    {"key": "presales", "name": "Pre-sales", "live": False},
    {"key": "tech", "name": "Tech", "live": False},
]

TOOLS = {
    "Crawl4AI": "Reads web pages like a person would.",
    "SearXNG": "Private web search, on our own server.",
    "yt-dlp": "Reads YouTube videos and channels.",
    "Apify": "Reads public Instagram and Facebook posts.",
    "fastembed": "Turns text into meaning, on our own server.",
    "pgvector": "Finds the knowledge closest in meaning.",
    "Groq": "Fast brain for the bulk reading at night.",
    "Cognee": "Connects knowledge into one map.",
    "Postgres": "The database everything is kept in.",
    "Token Harbor": "DeepSeek, Qwen and MiMo: brains for ideas, blogs and creatives.",
    "Script engine": "Five agents and their rule gates: evidence, director-writer, editor, lookbook director, video prompt engineer.",
    "OpenRouter": "NVIDIA Nemotron, the brain of the video team's script engine.",
    "Gemini": "Google's brain: quick answers when you talk to MAGI.",
    "Bloom": "The brand's creative direction and templates. Ideas and context only; it makes no images.",
    "Higgsfield": "Makes the images and the videos.",
    "Hermes": "The agent that lets MAGI use its abilities.",
    "Whisper": "Hears what you say.",
    "Kokoro": "MAGI's voice, on our own server.",
}


def departments() -> list[dict]:
    p = get_settings().inputs_dir / "magi.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["departments"] if p.exists() else DEPARTMENTS
    except (ValueError, KeyError):
        log.warning("inputs/magi.json could not be read; using the built-in departments")
        return DEPARTMENTS


_knows: dict = {"at": 0.0, "total": -1, "by_key": {}}


async def _with_knowledge(depts: list[dict], total: int) -> list[dict]:
    """Each department with the parts of the knowledge MAGI already holds for it (looked up, then kept for a while)."""
    if _knows["total"] != total or time.time() - _knows["at"] > 600:
        by_key = {}
        for d in depts:
            rows = await kb.search(d.get("ask") or d["name"], k=6, docs=["core", "internal", "brand", "manager"])
            seen = []
            for r in rows:
                title = (r["section"] or "").split(" > ")[-1]
                if title and title not in seen:
                    seen.append(title)
            by_key[d["key"]] = seen[:4]
        _knows.update(at=time.time(), total=total, by_key=by_key)
    return [{k: v for k, v in d.items() if k != "ask"} | {"knows": _knows["by_key"].get(d["key"], [])} for d in depts]


def _n(x) -> str:
    return f"{int(x or 0):,}"


async def _marketing() -> list[dict]:
    c = await db.fetchrow("""select
        (select count(*) from pages) pages, (select count(*) from pages where kept) kept,
        (select count(*) from sources) sites,
        (select count(*) from learnings where status in ('active','approved')) learned,
        (select count(*) from learnings where status = 'held') held,
        (select count(*) from ideas where status <> 'candidate') ideas,
        (select count(*) from blogs) blogs,
        (select count(*) from creatives where cardinality(image_urls) > 0) creatives,
        (select count(*) from videos where script ? 'final_script') scripts,
        (select count(*) from videos where cardinality(video_urls) > 0) videos""")
    return [
        {"key": "crawler", "name": "Crawler", "job": "Reads similar sites every night",
         "does": "Starts from the seed sites at 8 PM, follows links, finds new sites by itself and stops at 8 AM.",
         "tools": ["Crawl4AI", "SearXNG", "yt-dlp", "Apify"], "stat": f"{_n(c['pages'])} pages",
         "detail": f"{_n(c['pages'])} pages read on {_n(c['sites'])} sites"},
        {"key": "filter", "name": "Filter", "job": "Keeps only what fits the company",
         "does": "Compares every page with MAGI's knowledge and throws away what is off-topic.",
         "tools": ["fastembed", "pgvector"], "stat": f"{_n(c['kept'])} kept",
         "detail": f"{_n(c['kept'])} of {_n(c['pages'])} pages kept as relevant"},
        {"key": "knowledge", "name": "Knowledge", "job": "Learns, and holds doubts for the manager",
         "does": "Pulls learnings out of the kept pages. Sure ones join MAGI. Doubtful ones wait for the manager's 6 PM review.",
         "tools": ["Groq", "Cognee", "Postgres"], "stat": f"{_n(c['learned'])} learned",
         "detail": f"{_n(c['learned'])} learnings in MAGI · {_n(c['held'])} waiting for the manager"},
        {"key": "strategist", "name": "Strategist", "job": "Picks 2 blog, 2 creative, 2 video ideas",
         "does": "Turns what is working elsewhere into ideas shaped to the company, scores them and never repeats one.",
         "tools": ["Token Harbor", "Gemini", "Bloom"], "stat": f"{_n(c['ideas'])} ideas", "detail": f"{_n(c['ideas'])} ideas shown so far"},
        {"key": "blog", "name": "Blog writer", "job": "Writes the full blog with sources",
         "does": "Researches the approved idea and writes the blog from the company's own knowledge.",
         "tools": ["Token Harbor", "SearXNG"], "stat": f"{_n(c['blogs'])} blogs", "detail": f"{_n(c['blogs'])} blogs written"},
        {"key": "creative", "name": "Art director", "job": "Makes the story, poster or post",
         "does": "Takes the approved words and makes the finished image in the house style.",
         "tools": ["Token Harbor", "Bloom", "Higgsfield"], "stat": f"{_n(c['creatives'])} made", "detail": f"{_n(c['creatives'])} creatives made"},
        {"key": "video", "name": "Video team", "job": "Writes the script, then the video",
         "does": "Five agents. Three write the script: evidence, director-writer, editor, with rule gates between them. "
                 "After you approve the script, the lookbook director shows how the film will look. After you approve the "
                 "lookbook, the video prompt engineer writes the prompts and the edit sheet. Then the video is made.",
         "tools": ["Script engine", "OpenRouter", "Higgsfield"], "stat": f"{_n(c['scripts'])} scripts",
         "detail": f"{_n(c['scripts'])} scripts written · {_n(c['videos'])} videos made"},
        {"key": "voice", "name": "MAGI's voice", "job": "Talks, answers and acts for you",
         "does": "Say \"wake up time\" and ask anything, or tell MAGI what to open or do. It can run every job in this department.",
         "tools": ["Hermes", "Gemini", "Whisper", "Kokoro"], "stat": "17 abilities", "detail": "17 abilities, from reading the status to opening screens"},
    ]


@router.get("/map")
async def magi_map():
    dots = await db.fetch("""
        with n as (select id, doc, coalesce(section, '') section, left(content, 240) body, embedding
                   from kb_chunks where active and embedding is not null
                   order by (doc in ('core','brand','manager','internal')) desc, created_at desc limit %s)
        select n.id, n.doc, n.section, n.body,
               (select array_agg(m.id) from (select m.id from n m where m.id <> n.id
                                             order by m.embedding <=> n.embedding limit 2) m) links
        from n""", MAX_DOTS)
    kinds = await db.fetch("select doc, count(*) n from kb_chunks where active group by doc")
    c = await db.fetchrow("""select
        (select count(*) from learnings where status = 'held') held,
        (select count(*) from learnings where status = 'pending') pending,
        (select count(*) from pages) pages, (select count(*) from sources) sites,
        (select max(created_at) from kb_chunks where active) newest""")
    total = sum(k["n"] for k in kinds)
    return {"dots": dots, "kinds": {k["doc"]: k["n"] for k in kinds}, "total": total,
            "waiting": c["held"], "pending": c["pending"], "pages": c["pages"], "sites": c["sites"],
            "newest": c["newest"], "departments": await _with_knowledge(departments(), total),
            "marketing": await _marketing(), "tools": TOOLS}


@router.post("/drop")
async def magi_drop(file: UploadFile):
    """A document dropped on the brain joins the knowledge, as something a person on the team added."""
    name = (file.filename or "document").rsplit("/", 1)[-1][:120]
    if not name.lower().endswith(DROP_TYPES):
        raise HTTPException(400, "MAGI reads .md, .txt and .csv files here.")
    raw = await file.read(DROP_BYTES + 1)
    if len(raw) > DROP_BYTES:
        raise HTTPException(400, "That file is too large to drop here (2 MB at most).")
    text = raw.decode("utf-8", errors="ignore").strip()
    if len(text) < 40:
        raise HTTPException(400, "That file is empty.")
    pairs = [(s or name, ch) for s, ch in kb.chunk_markdown(text)]
    added = await kb._insert("manager", pairs, {"source": "dropped", "file": name})
    await flt.load_profiles()
    return {"added": added, "file": name}
