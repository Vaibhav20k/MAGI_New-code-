"""Agents 06 (Adapt) and 07 (Strategist): what the Crawl button runs.

Adapt      — takes what is working on similar sites and channels and rewrites it as
             Magppie ideas, grounded in the company KB.
Strategist — scores the candidates and picks the best 2 blog + 2 creative + 2 video ideas,
             never repeating an idea that was shown before.
"""

import json
import logging
import re

from .. import bloom, brand, db, inputs, kb, llm, video_types
from ..embed import embed
from . import creative

log = logging.getLogger("mai.ideas")

TYPES = ("blog", "creative", "video")
REPEAT = 0.86      # an idea this close to an earlier one counts as a repeat
PER_TYPE = 2

ADAPT_SYSTEM = """You are the Adapt agent of a marketing intelligence system.
You receive SIGNALS: things similar brands, publications and creators recently published, with links,
plus LEARNINGS the system has confirmed. Turn them into content ideas for OUR company.

Rules:
- Every idea must be inspired by at least one signal or learning (give its number) and must be
  rewritten around OUR company: our products, story, values and customer, taken ONLY from the
  COMPANY KNOWLEDGE excerpts. Quote the KB ids you relied on.
- Never copy a competitor's idea as is. Borrow the topic, hook style or format; make the substance ours.
- State no product fact, number or claim that is not in COMPANY KNOWLEDGE. This applies to every field,
  including "angle" and "summary": do not add words like "patented", "award-winning" or "certified",
  and do not stretch a claim beyond what the knowledge says.
- An idea may propose something new for the company to do (a collaboration, a series, a format). Word it as
  a proposal ("We could...", "A series on..."). Never say or imply the company already does, sells, owns or
  partners with something unless COMPANY KNOWLEDGE says so.
- Follow the brand guide and the BRAND RULES in the message exactly. An idea that breaks one is thrown away.
- Avoid anything on the "previously shown" list or close to it.

Return JSON: {"ideas": [{"type": "blog|creative|video", "title": "...", "summary": "2-3 sentences",
"angle": "why this fits our company, in one sentence", "signals": [numbers], "kb_ids": [numbers],
"draft": {...}}]}
"draft" by type:
  blog     → {"focus_keyword": "...", "outline": ["H2 ...", ...], "reader_takeaway": "..."}
  creative → {"format": "one of the CREATIVE KINDS below", "headline": "the big words on the image",
              "highlight": "1 to 3 consecutive words copied from the headline, shown in colour",
              "supporting_line": "the small line under the headline, max 12 words",
              "visual": "the one photograph on the image, in a sentence"}
              The headline is printed on the image, so it must be true to COMPANY KNOWLEDGE and need no context.
              Use a different kind for each creative idea where you can.
CREATIVE KINDS:
%s
Headlines the company has used before (style reference, do not repeat):
%s
  video    → {"video_type": "one key from VIDEO TYPES below", "type_reason": "one sentence: why this type suits
              this topic and will travel furthest on Instagram", "platform": "...", "length_seconds": 30,
              "hook": "first 3 seconds", "beats": ["...", ...], "cta": "..."}
              Choose the type for the topic: the one most likely to stop the scroll and be watched, saved or shared.
              Use a different type for each video idea where you can.
VIDEO TYPES:
%s
Write %d ideas of each type."""

PICK_SYSTEM = """You are the Strategist of a marketing team. Score each candidate idea from 1 to 10 on:
fit (true to our company and brand guide), trend (rides something that is working now),
novelty (fresh versus what we already showed), feasibility (can be produced well as that format).
Also check each candidate against COMPANY KNOWLEDGE: set "invents" to true if it states or implies a company
fact that is not there (a product, material, feature, number, partnership or claim presented as existing).
Proposals worded as something the company could do are fine.
Then pick the best %d of each type (blog, creative, video). Never pick a candidate with "invents": true.
Prefer variety of topics across the picks.

Return JSON: {"scores": [{"n": <candidate number>, "fit": 0, "trend": 0, "novelty": 0, "feasibility": 0,
"invents": false, "why": "one sentence"}], "picks": {"blog": [n, n], "creative": [n, n], "video": [n, n]}}"""


async def _signals(limit: int = 14) -> list[dict]:
    """Recent relevant pages not yet used for an idea, strongest first."""
    rows = await db.fetch(
        """select p.id, p.url, p.title, left(p.content_md, 700) as snippet, p.meta, p.relevance, s.domain
           from pages p left join sources s on s.id = p.source_id
           where p.kept and p.fetched_at > now() - interval '21 days'
             and not exists (select 1 from ideas i where i.inspired_by @> jsonb_build_array(
                                   jsonb_build_object('url', p.url)))
           order by coalesce((p.meta->>'views')::bigint, 0) > 50000 desc, p.relevance desc nulls last
           limit %s""", limit * 3)
    seen, out = {}, []
    for r in rows:                                    # at most 3 per site, for variety
        if seen.get(r["domain"], 0) >= 3:
            continue
        seen[r["domain"]] = seen.get(r["domain"], 0) + 1
        out.append(r)
        if len(out) >= limit:
            break
    return out


async def _learnings(limit: int = 12) -> list[dict]:
    return await db.fetch(
        "select id, coalesce(edited_content, content) as content, kind, source_urls from learnings "
        "where status in ('active','approved') order by created_at desc limit %s", limit)


async def generate_batch(batch_id: int) -> dict:
    try:
        signals, learnings = await _signals(), await _learnings()
        topic_text = " ".join((s["title"] or "") for s in signals) + " " + \
                     " ".join(l["content"] for l in learnings[:6])
        kb_rows = await kb.search(topic_text or "our products, story and customers", k=14,
                                  docs=["core", "brand", "manager", "learned"])
        scripts = await kb.search(topic_text or "script idea", k=5, docs=["script_bank"])
        shown = await db.fetch("select title from ideas where status <> 'candidate' "
                               "order by created_at desc limit 60")
        never = await db.fetch("select content from manager_rules where kind = 'never_use'")

        numbered = [f"[{n + 1}] {s['title']} — {s['url']}\n    {s['meta'] or ''}\n    "
                    f"{(s['snippet'] or '').replace(chr(10), ' ')[:500]}" for n, s in enumerate(signals)]
        base = len(signals)
        numbered += [f"[{base + n + 1}] (confirmed learning, {l['kind']}) {l['content']}"
                     for n, l in enumerate(learnings)]
        user = (
            f"SIGNALS AND LEARNINGS:\n{chr(10).join(numbered) or '(none yet — the crawler has not run; use the company knowledge and script bank only, and leave signals empty)'}\n\n"
            f"COMPANY KNOWLEDGE:\n{kb.as_context(kb_rows)}\n\n"
            f"{brand.RULES}\n\nBRAND GUIDE:\n{inputs.brand_guide()[:5000]}\n\n"
            f"OUR PAST SCRIPT IDEAS (style reference, do not repeat):\n"
            f"{chr(10).join('- ' + s['content'][:300] for s in scripts)}\n\n"
            f"NEVER USE:\n{chr(10).join('- ' + n['content'] for n in never) or '(nothing listed)'}\n\n"
            f"PREVIOUSLY SHOWN (do not repeat):\n{chr(10).join('- ' + s['title'] for s in shown) or '(none)'}")
        st = creative.styles()
        kinds = "\n".join(f"  {k}: {f['use']} Headline: {f['headline_hint']}." for k, f in st["formats"].items())
        used = "\n".join("  - " + h for h in st.get("headline_examples", []))
        direction = await bloom.context(3500)
        if direction:
            user += ("\n\nCREATIVE DIRECTION AND TEMPLATES (from our brand's Bloom skill; use it to shape the creative and "
                     f"video ideas, never to add facts):\n{direction}")
        data = await llm.chat_json(ADAPT_SYSTEM % (kinds, used, video_types.menu(), 5), user, temperature=0.9)
        cands = []
        for c in brand.scrub(data.get("ideas", [])):
            if c.get("type") not in TYPES or not c.get("title"):
                continue
            broken = brand.violations({k: c.get(k) for k in ("title", "summary", "angle", "draft")})
            if broken:
                log.info("idea dropped for breaking a brand rule: %s (%s)", c["title"], broken[0])
                continue
            cands.append(c)
        if not cands:
            raise RuntimeError("The Adapt agent returned no ideas.")

        # drop repeats of anything shown before, and of each other
        vecs = await embed([f"{c['title']}. {c.get('summary', '')}" for c in cands])
        fresh = []
        for c, v in zip(cands, vecs):
            prior = await db.fetch("select * from similar_ideas(%s, 1)", v)
            if prior and prior[0]["similarity"] >= REPEAT and prior[0]["status"] != "candidate":
                continue
            if any(float(v @ f["_vec"]) / ((v @ v) ** .5 * (f["_vec"] @ f["_vec"]) ** .5) >= REPEAT for f in fresh):
                continue
            c["_vec"] = v
            fresh.append(c)

        listing = "\n".join(f"[{n + 1}] ({c['type']}) {c['title']} — {c.get('summary', '')} "
                            f"| fit: {c.get('angle', '')}" for n, c in enumerate(fresh))
        pick = await llm.chat_json(
            PICK_SYSTEM % PER_TYPE,
            f"COMPANY KNOWLEDGE:\n{kb.as_context(kb_rows)[:6000]}\n\n"
            f"{brand.RULES}\n\nBRAND GUIDE:\n{inputs.brand_guide()[:4000]}\n\nPREVIOUSLY SHOWN:\n"
            f"{chr(10).join('- ' + s['title'] for s in shown[:30]) or '(none)'}\n\nCANDIDATES:\n{listing}",
            temperature=0.2)
        scores = {int(s["n"]): s for s in pick.get("scores", []) if str(s.get("n", "")).isdigit()}
        picks: set[int] = set()
        for t in TYPES:
            chosen = [int(n) for n in (pick.get("picks", {}).get(t) or []) if str(n).isdigit()
                      and 0 < int(n) <= len(fresh) and fresh[int(n) - 1]["type"] == t
                      and not scores.get(int(n), {}).get("invents")][:PER_TYPE]
            if len(chosen) < PER_TYPE:               # strategist under-picked: fill by score
                rest = sorted((n + 1 for n, c in enumerate(fresh) if c["type"] == t and n + 1 not in chosen
                               and not scores.get(n + 1, {}).get("invents")),
                              key=lambda n: -sum(scores.get(n, {}).get(k, 0) for k in
                                                 ("fit", "trend", "novelty", "feasibility")))
                chosen += rest[:PER_TYPE - len(chosen)]
            picks.update(chosen)

        # the picked creatives each get a different kind (story, poster, post)
        taken: set[str] = set()
        for n in sorted(picks):
            c = fresh[n - 1]
            if c["type"] != "creative":
                continue
            draft = c["draft"] = c.get("draft") if isinstance(c.get("draft"), dict) else {}
            if draft.get("format") not in st["formats"] or draft["format"] in taken:
                draft["format"] = next((k for k in st["formats"] if k not in taken), "post")
            taken.add(draft["format"])
            draft["bottom_line"] = st["formats"][draft["format"]]["bottom_line"]

        # the picked videos each get a type MAGI can make, different from each other where possible
        used: set[str] = set()
        for n in sorted(picks):
            c = fresh[n - 1]
            if c["type"] != "video":
                continue
            draft = c["draft"] = c.get("draft") if isinstance(c.get("draft"), dict) else {}
            draft["video_type"] = video_types.choose(draft.get("video_type"), used)
            used.add(draft["video_type"])

        kb_by_id = {r["id"]: r for r in kb_rows}
        for n, c in enumerate(fresh, start=1):
            sc = scores.get(n, {})
            total = sum(sc.get(k, 0) for k in ("fit", "trend", "novelty", "feasibility")) / 4 or None
            inspired = []
            for i in c.get("signals") or []:
                if isinstance(i, int) and 0 < i <= len(signals):
                    s = signals[i - 1]
                    inspired.append({"url": s["url"], "title": s["title"], "site": s["domain"]})
                elif isinstance(i, int) and base < i <= base + len(learnings):
                    l = learnings[i - base - 1]
                    inspired.append({"learning": l["content"], "url": (l["source_urls"] or [None])[0]})
            ids = [int(m) for i in (c.get("kb_ids") or []) for m in re.findall(r"\d+", str(i))]
            refs = [{"id": i, "section": kb_by_id[i]["section"], "text": kb_by_id[i]["content"][:240]}
                    for i in dict.fromkeys(ids) if i in kb_by_id]
            payload = {**(c.get("draft") or {}), "why_picked": sc.get("why"), "scores": {
                k: sc.get(k) for k in ("fit", "trend", "novelty", "feasibility")}}
            await db.execute(
                """insert into ideas (batch_id, type, title, summary, angle, inspired_by, kb_refs, payload, score,
                                      status, embedding) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                batch_id, c["type"], c["title"], c.get("summary"), c.get("angle"), db.Jsonb(inspired),
                db.Jsonb(refs), db.Jsonb(payload), total, "proposed" if n in picks else "candidate", c["_vec"])
        await db.execute("update idea_batches set status = 'ready' where id = %s", batch_id)
        return {"batch_id": batch_id, "candidates": len(fresh), "picked": len(picks),
                "signals_used": len(signals), "learnings_used": len(learnings)}
    except Exception as e:  # noqa: BLE001
        log.exception("idea batch failed")
        await db.execute("update idea_batches set status = 'failed', error = %s where id = %s", str(e)[:500],
                         batch_id)
        return {"batch_id": batch_id, "error": str(e)}


async def new_batch() -> int:
    """Start a fresh set. Ideas from earlier sets that were not selected are set aside."""
    await db.execute("update ideas set status = 'discarded' where status = 'proposed'")
    row = await db.fetchrow("insert into idea_batches default values returning id")
    return row["id"]


async def latest() -> dict:
    batch = await db.fetchrow("select * from idea_batches order by id desc limit 1")
    if not batch:
        return {"batch": None, "ideas": [], "creative": creative.formats(), "video": video_types.for_cards()}
    ideas = await db.fetch(
        "select id, type, title, summary, angle, inspired_by, kb_refs, payload, score, status, created_at "
        "from ideas where batch_id = %s and status <> 'candidate' order by type, score desc nulls last",
        batch["id"])
    made = {}
    for table, cols in (("creatives", "image_urls media, remote_urls"), ("videos", "video_urls media, remote_urls"),
                        ("blogs", "null::text[] media, null::text[] remote_urls")):
        status = "'ready' status, created_at started_at" if table == "blogs" else "status, started_at"
        for r in await db.fetch(f"select distinct on (idea_id) idea_id, id, {status}, {cols} from {table} "
                                "where idea_id = any(%s) order by idea_id, id desc", [i["id"] for i in ideas]):
            made[r["idea_id"]] = {"id": r["id"], "status": r["status"], "started_at": r["started_at"],
                                  "media": (r["media"] or [None])[0], "remote": (r["remote_urls"] or [None])[0]}
    for i in ideas:
        i["made"] = made.get(i["id"])
    kinds = creative.formats()
    order = list(kinds["formats"])
    n = 0
    for i in ideas:                                   # ideas made before kinds existed get one for the card
        if i["type"] == "creative":
            pay = i["payload"] = dict(i["payload"] or {})
            if pay.get("format") not in kinds["formats"]:
                pay["format"] = order[n % len(order)]
            pay.setdefault("bottom_line", kinds["formats"][pay["format"]]["bottom_line"])
            n += 1
    cards = video_types.for_cards()
    for i in ideas:                                   # ideas made before types existed get the default
        if i["type"] == "video":
            pay = i["payload"] = dict(i["payload"] or {})
            pay.setdefault("video_type", cards["default"])
    return {"batch": batch, "ideas": ideas, "creative": kinds, "video": cards}


def dumps(o) -> str:
    return json.dumps(o, default=str, ensure_ascii=False)
