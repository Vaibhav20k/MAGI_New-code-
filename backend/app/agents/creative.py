"""Agent 09 — Creative. Turns an approved creative idea into a finished ad image.

The words on the image (headline, coloured words, small line, bottom line) and the kind of creative
(story, poster, post) come from the idea card, where the user can edit them before approving, and are
used exactly as approved. The agent adds the photograph description and the caption, grounded in the
company knowledge. The layout comes from the house styles in inputs/creative-styles.json, which were
taken from the company's own posters. Higgsfield renders the image with the text on it.
"""

import json
import logging
import re

from .. import bloom, brand, db, kb, llm, media
from ..config import get_settings

log = logging.getLogger("mai.creative")

FIELDS = ("format", "headline", "highlight", "supporting_line", "visual", "bottom_line")
LIMITS = {"headline": 160, "highlight": 80, "supporting_line": 160, "visual": 600, "bottom_line": 160}


def styles() -> dict:
    p = get_settings().inputs_dir / "creative-styles.json"
    return json.loads(p.read_text(encoding="utf-8"))


def formats() -> dict:
    """The kinds of creative on offer and what one image costs, for the idea cards."""
    st = styles()
    return {"credits_each": st["image"].get("credits_each"),
            "formats": {k: {"label": f["label"], "use": f["use"], "bottom_line": f["bottom_line"],
                            "aspect_ratio": f["aspect_ratio"]} for k, f in st["formats"].items()}}


def clean(fields: dict) -> dict:
    """Only the brief fields a person may edit, trimmed to sensible lengths."""
    out = {}
    for k in FIELDS:
        v = fields.get(k)
        if isinstance(v, str):
            v = re.sub(r"\s+", " ", brand.clean(v)).strip()
            out[k] = v[:LIMITS.get(k, 40)]
    if "format" in out and out["format"] not in styles()["formats"]:
        del out["format"]
    return out


def _q(text: str) -> str:
    """Text that will sit inside double quotes in the prompt."""
    return (text or "").replace('"', "'").strip()


def build_prompt(brief: dict) -> str:
    st = styles()
    f = st["formats"][brief["format"]]
    headline, highlight = _q(brief.get("headline")), _q(brief.get("highlight"))
    sub, bottom = _q(brief.get("supporting_line")), _q(brief.get("bottom_line")) or f["bottom_line"]
    parts = [f["layout"]]
    if st.get("logo_media"):
        parts.append(st["logo_note"])
    if f.get("reference_job"):
        parts.append(f["reference_note"])
    colour = f["highlight_style"].replace("{highlight}", highlight) if highlight and highlight.lower() in headline.lower() \
        else "All headline words are the same colour."
    parts.append(f'HEADLINE, reading exactly: "{headline}". {f["headline_style"]} {colour}')
    if sub:
        parts.append(f'SMALL LINE, reading exactly: "{sub}". {f["sub_style"]}')
    photo = str(brief.get("photo") or brief.get("visual_description") or "").strip().rstrip(".")
    parts.append(f'PHOTOGRAPH: {photo}. {f["photo_style"]}')
    parts.append("FOOTER: " + f["footer"].replace("{bottom_line}", bottom))
    parts.append("RULES: " + st["rules"])
    return "\n\n".join(parts)


SYSTEM = """You are the art director for the company described in COMPANY KNOWLEDGE.
The words on this ad are already approved; do not change or repeat them. Your job:
1. "photo": describe the one photograph for the ad in 40 to 70 words: subject, setting, composition, camera
   angle, lighting, materials, mood. It must show what PICTURE IDEA asks for and suit the FORMAT.
   Only show products and materials the company really has, per COMPANY KNOWLEDGE. No text, logos, brand names
   or people's faces in the photograph.
2. "caption": a ready-to-post caption, 2 to 4 sentences, in the brand's voice. Every fact from COMPANY KNOWLEDGE
   only; invent no numbers, awards, certifications or claims. Follow the BRAND RULES exactly.
3. "hashtags": 5 to 8.
4. "why_it_fits": one line grounded in COMPANY KNOWLEDGE.

Return JSON: {"photo": "...", "caption": "...", "hashtags": ["#..."], "why_it_fits": "..."}"""


async def write(idea_id: int) -> int:
    idea = await db.fetchrow("select * from ideas where id = %s", idea_id)
    p, st = idea["payload"] or {}, styles()
    fmt = p.get("format") if p.get("format") in st["formats"] else "post"
    f = st["formats"][fmt]
    brief = {"title": idea["title"], "format": fmt, "format_label": f["label"], "aspect_ratio": f["aspect_ratio"],
             "headline": p.get("headline") or idea["title"], "highlight": p.get("highlight") or "",
             "supporting_line": p.get("supporting_line") or "", "bottom_line": p.get("bottom_line") or f["bottom_line"],
             "visual_description": p.get("visual") or idea["summary"], "inspired_by": idea["inspired_by"]}
    row = await db.fetchrow("insert into creatives (idea_id, brief, status, started_at) values (%s,%s,'writing',now()) "
                            "returning id", idea_id, db.Jsonb(brief))
    creative_id = row["id"]
    try:
        kb_rows = await kb.search(f"{idea['title']}. {idea['summary']}. {brief['headline']}", k=10,
                                  docs=["core", "brand", "manager", "learned"])
        user = (f"FORMAT: {f['label']} — {f['use']}\nAPPROVED WORDS ON THE AD: headline \"{brief['headline']}\"; "
                f"small line \"{brief['supporting_line']}\"\nPICTURE IDEA: {brief['visual_description']}\n"
                f"IDEA: {idea['title']} — {idea['summary']}\nWhy it fits us: {idea['angle']}\n\n"
                f"{brand.RULES}\n\nCOMPANY KNOWLEDGE:\n{kb.as_context(kb_rows)}")
        direction = await bloom.context(3000)
        if direction:
            user += ("\n\nVISUAL DIRECTION AND TEMPLATES (from our brand's Bloom skill; follow it for the look of the "
                     f"photograph, never for facts):\n{direction}")
        data = {}
        for _ in range(3):
            data = brand.scrub(await llm.chat_json(SYSTEM, user, temperature=0.7))
            broken = brand.violations([data.get("photo"), data.get("caption")])
            if len(str(data.get("caption") or "")) < 60:            # some brains leave a field out
                broken.append("the caption is missing: write the 2 to 4 sentence caption")
            if len(str(data.get("photo") or "")) < 40:
                broken.append("the photo description is missing")
            if not broken:
                break
            log.warning("creative text broke brand rules: %s", broken)
            user += "\n\nYour last answer had these problems; write the whole answer again without them:\n- " + "\n- ".join(broken)
        else:
            raise RuntimeError("The creative text could not be written properly: " + "; ".join(broken))
        if len(str(data.get("photo") or "")) < 40:
            raise RuntimeError("The creative agent did not describe the photograph.")
        brief.update(photo=str(data["photo"])[:900], caption=data.get("caption") or "",
                     hashtags=data.get("hashtags") or [], why_it_fits=data.get("why_it_fits") or "")
        brief["image_prompts"] = [{"label": f["label"], "prompt": build_prompt(brief)}]
        await db.execute("update creatives set brief = %s, status = 'brief_ready' where id = %s",
                         db.Jsonb(brief), creative_id)
    except Exception:
        await db.execute("delete from creatives where id = %s", creative_id)   # the idea goes back to the list
        raise
    return creative_id


async def reword(creative_id: int, fields: dict) -> None:
    """Change the words on an existing creative; the next image uses them."""
    c = await db.fetchrow("select brief from creatives where id = %s", creative_id)
    brief = {**c["brief"], **{k: v for k, v in clean(fields).items() if k != "visual"}}
    st = styles()
    if brief.get("format") not in st["formats"]:
        brief["format"] = "post"
    f = st["formats"][brief["format"]]
    brief.update(format_label=f["label"], aspect_ratio=f["aspect_ratio"])
    brief["image_prompts"] = [{"label": f["label"], "prompt": build_prompt(brief)}]
    await db.execute("update creatives set brief = %s where id = %s", db.Jsonb(brief), creative_id)


async def generate(creative_id: int) -> bool:
    """Render the creative on Higgsfield and save it for the dashboard. Spends credits."""
    try:
        await db.execute("update creatives set status = 'generating', error = null, started_at = now() "
                         "where id = %s", creative_id)
        st = styles()
        c = await db.fetchrow("select brief from creatives where id = %s", creative_id)
        if c["brief"].get("format") not in st["formats"]:      # a creative from before the house styles
            await reword(creative_id, {})
            c = await db.fetchrow("select brief from creatives where id = %s", creative_id)
        brief = c["brief"]
        f = st["formats"][brief["format"]]
        plan = {"model": st["image"]["model"], "prompt": brief["image_prompts"][0]["prompt"],
                "aspect_ratio": f["aspect_ratio"],
                "quality": st["image"]["quality"], "resolution": st["image"]["resolution"]}
        # the logo and the layout reference go along as pictures; if Higgsfield refuses one, try with fewer
        logo, ref = st.get("logo_media"), f.get("reference_job")
        tries = [[m for m in (logo, ref) if m]] + ([[logo]] if logo and ref else []) + ([[]] if logo or ref else [])
        for n, pics in enumerate(tries):
            try:
                saved, job_ids, remote = await media.generate(
                    "image", {**plan, "medias": [{"value": m, "role": "image_references"} for m in pics]} if pics else plan)
                break
            except media.Rejected as refused:
                if refused.account or n == len(tries) - 1:        # a limit on the account: fewer pictures would not help
                    raise
                log.warning("creative %s: Higgsfield refused a reference picture; trying with fewer", creative_id)
        await db.execute(
            "update creatives set image_urls = %s::text[] || image_urls, remote_urls = %s::text[] || remote_urls, "
            "job_ids = %s::text[] || job_ids, "
            "status = 'ready' where id = %s", saved, remote, job_ids, creative_id)
        return True
    except Exception as e:  # noqa: BLE001
        log.exception("creative %s failed", creative_id)
        await db.execute("update creatives set status = 'failed', error = %s where id = %s", str(e)[:600],
                         creative_id)
        return False
