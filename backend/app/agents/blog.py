"""Agent 08 — Blog writer. Writes a full blog from an approved idea.

Facts about the company come only from the knowledge base. Facts about the wider
world come only from pages it has actually read, and are cited.
"""

import logging
import re

from .. import brand, db, inputs, kb, llm, services

log = logging.getLogger("mai.blog")

SYSTEM = """You are the blog writer for the company described in COMPANY KNOWLEDGE.
Write one complete, publish-ready blog post in Markdown for the IDEA.

Hard rules:
- Company facts (products, materials, numbers, claims, history): use ONLY what is in COMPANY KNOWLEDGE.
  If something is not there, leave it out. Never invent specifications, statistics or certifications.
- Outside facts: use ONLY the numbered RESEARCH SOURCES, and cite them inline as [S1], [S2].
  Do not cite a source for something it does not say.
- No health, safety or environmental claim unless COMPANY KNOWLEDGE states it.
- Follow the BRAND RULES, the BRAND GUIDE voice and the BLOG FORMAT exactly.
- The IDEA text is only a direction. If it contains a claim that COMPANY KNOWLEDGE does not support
  (for example "patented" or "award-winning"), drop that claim.
- Length: at least 1,200 words in body_md.
- Do not mention competitors by name. Do not copy any source's wording.

Reply in exactly this layout, with nothing before it:
TITLE: SEO title under 60 characters
META: meta description under 155 characters
KEYWORD: the focus keyword
RELATED: three to five related keywords, comma separated
SOURCES_USED: numbers of the research sources actually cited, comma separated (or "none")
===
The full post in Markdown, starting with an H1."""


def _parse(reply: str) -> dict:
    """Read the TITLE / META / ... header and the Markdown body out of the model's reply."""
    head, sep, body = reply.partition("\n===")
    if not sep:                                   # no divider: treat everything from the first heading as the body
        m = re.search(r"^# ", reply, re.M)
        head, body = (reply[:m.start()], reply[m.start():]) if m else ("", reply)

    def field(name: str) -> str:
        m = re.search(rf"^\**{name}\**\s*:\s*(.+)$", head, re.M | re.I)
        return m.group(1).strip().strip("*").strip() if m else ""

    return {"title": field("TITLE"), "meta_description": field("META"), "focus_keyword": field("KEYWORD"),
            "related_keywords": [k.strip() for k in field("RELATED").split(",") if k.strip()],
            "sources_used": [int(n) for n in re.findall(r"\d+", field("SOURCES_USED"))],
            "body_md": body.strip().lstrip("=").strip()}


def _usable(d: dict) -> bool:
    """A real blog: has a title line, starts with a heading, has several sections, reads like prose."""
    body = d["body_md"]
    words = body.split()
    if not d["title"] or not body.startswith("#") or len(re.findall(r"^## ", body, re.M)) < 3:
        return False
    if re.search(r"thinking process|analy[sz]e the request|\blet me\b|as an ai\b", body[:1500], re.I):
        return False
    odd = sum(1 for w in words if not re.search(r"[A-Za-z0-9]", w))
    return len(words) >= 300 and odd / len(words) < 0.08


async def _draft(system: str, user: str, temperature: float) -> dict:
    """Ask for the blog; a reply that is not a real blog is thrown away and asked for again."""
    note = ""
    for _ in range(4):
        d = brand.scrub(_parse(await llm.complete(system, user + note, temperature=temperature, long=True)))
        if not _usable(d):
            log.warning("blog reply rejected by the quality check: %r", d["body_md"][:100])
            continue
        broken = brand.violations([d["title"], d["meta_description"], d["body_md"]])
        if not broken:
            return d
        log.warning("blog draft broke brand rules: %s", broken)
        note = ("\n\nYOUR LAST DRAFT BROKE THESE BRAND RULES. Write it again without them:\n- "
                + "\n- ".join(broken))
    raise RuntimeError("The AI brains did not produce a blog that passes the brand rules just now. Try again in a few minutes.")


async def _research(idea: dict, max_sources: int = 4) -> list[dict]:
    """Read a few real pages on the topic so outside facts can be cited."""
    sources = [{"url": i["url"], "title": i.get("title") or i["url"]}
               for i in (idea["inspired_by"] or []) if i.get("url")][:2]
    query = (idea["payload"] or {}).get("focus_keyword") or idea["title"]
    for r in await services.search(query, time_range="year"):
        if len(sources) >= max_sources + 2:
            break
        if r["url"] not in {s["url"] for s in sources}:
            sources.append({"url": r["url"], "title": r["title"]})
    out = []
    for s in sources:
        if len(out) >= max_sources:
            break
        row = await db.fetchrow("select title, content_md from pages where url = %s", s["url"])
        text = (row or {}).get("content_md")
        if not text:
            res = await services.crawl([s["url"]])
            text = res[0].get("markdown") if res and res[0].get("ok") else None
        if text and len(text) > 400:
            out.append({"url": s["url"], "title": s["title"], "text": text[:2500]})
    return out


async def write(idea_id: int) -> int:
    idea = await db.fetchrow("select * from ideas where id = %s", idea_id)
    kb_rows = await kb.search(f"{idea['title']}. {idea['summary']}", k=14,
                              docs=["core", "brand", "manager", "learned"])
    research = await _research(idea)
    blog_format = inputs.section(inputs.output_formats(), "Blog") or \
        "1,200-1,500 words, English, hook intro, 4-6 H2 sections, FAQ with 3-5 questions, conclusion with call to action."
    user = (
        f"IDEA:\nTitle: {idea['title']}\nSummary: {idea['summary']}\nWhy it fits us: {idea['angle']}\n"
        f"Draft notes: {idea['payload']}\n\n"
        f"BLOG FORMAT:\n{blog_format}\n\n{brand.RULES}\n\nBRAND GUIDE:\n{inputs.brand_guide()[:5000]}\n\n"
        f"COMPANY KNOWLEDGE:\n{kb.as_context(kb_rows)}\n\n"
        "RESEARCH SOURCES:\n" + ("\n\n".join(
            f"[S{n + 1}] {s['title']}: {s['url']}\n{s['text']}" for n, s in enumerate(research))
            or "(none available: write from company knowledge only and cite nothing)"))
    data = await _draft(SYSTEM, user, 0.6)
    body = data["body_md"]
    if len(body.split()) < 1100:                     # too short: one expansion pass, same rules
        try:
            more = await _draft(
                SYSTEM, user + "\n\nYOUR DRAFT (too short at %d words):\n%s\n\nExpand it to 1,200-1,500 words by "
                "deepening the existing sections and the FAQ. Add no fact that is not in COMPANY KNOWLEDGE or the "
                "RESEARCH SOURCES. Reply in the same layout." % (len(body.split()), body), 0.5)
            if len(more["body_md"].split()) > len(body.split()):
                data, body = more, more["body_md"]
        except RuntimeError:
            pass                                      # keep the shorter, valid draft
    body = re.sub(r"【\s*(S\d+)\s*】", r"[\1]", body)
    used = [research[n - 1] for n in (data.get("sources_used") or [])
            if isinstance(n, int) and 0 < n <= len(research)]
    sources = [{"n": research.index(s) + 1, "url": s["url"], "title": s["title"]} for s in used]
    if sources:
        body += "\n\n## Sources\n" + "\n".join(f"- [S{s['n']}] [{s['title']}]({s['url']})" for s in sources)
    row = await db.fetchrow(
        """insert into blogs (idea_id, title, meta_description, focus_keyword, body_md, sources)
           values (%s,%s,%s,%s,%s,%s) returning id""",
        idea_id, data.get("title") or idea["title"], data.get("meta_description"),
        data.get("focus_keyword"), body,
        db.Jsonb({"web": sources, "kb": [{"id": r["id"], "section": r["section"]} for r in kb_rows[:8]]}))
    return row["id"]
