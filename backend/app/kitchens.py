"""Which real MAGPPIE kitchen, and which finish, a video is set in.

Kitchens come from the reference library (app/references.py). A video idea is offered the kitchens that suit its
topic best, preferring real photographs and pictures a person has reviewed, and leaving out the kitchens and
finishes of the last few videos so that consecutive videos never look the same.
"""

from . import db, embed

RECENT = 4                       # how many recent videos' kitchens and finishes to avoid


async def recent() -> tuple[set[int], set[str]]:
    rows = await db.fetch("select payload->'kitchen' k from ideas where type = 'video' and payload ? 'kitchen' "
                          "and status in ('selected','finalising','finalised') order by id desc limit %s", RECENT)
    kitchens = [r["k"] for r in rows if isinstance(r["k"], dict)]
    return {k.get("ref_id") for k in kitchens}, {k.get("finish") for k in kitchens if k.get("finish")}


def rank(rows: list[dict], used_refs: set, used_finishes: set, n: int) -> list[dict]:
    """Best first: fit to the topic, then real over render, reviewed over not. A kitchen used recently is left out;
    a finish used recently counts against it; the list prefers a different finish on each line."""
    scored = []
    for r in rows:
        if r["id"] in used_refs:
            continue
        score = float(r.get("similarity") or 0) + (.08 if r.get("reviewed") else 0) + (.05 if r.get("source") == "real" else 0)
        if r.get("finish") and r["finish"] in used_finishes:
            score -= .15
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, r in scored:                          # first pass: one line per finish
        if r.get("finish") not in seen or not r.get("finish"):
            out.append(r)
            seen.add(r.get("finish"))
        if len(out) == n:
            return out
    out += [r for _, r in scored if r not in out][:n - len(out)]
    return out


async def options(text: str, n: int = 6) -> list[dict]:
    """The kitchens that suit this video, best first, each with its finish swatch."""
    rows = await db.fetch(
        "select id, name, finish, layout, source, reviewed, thumb_path, file_path, description, "
        "(1 - (embedding <=> %s))::real similarity from ref_assets "
        "where active and kind = 'kitchen' and usable_as = 'exact' and embedding is not null",
        await embed.embed_one(text))
    used_refs, used_finishes = await recent()
    picked = rank(rows, used_refs, used_finishes, n)
    swatches = {r["finish"]: r for r in await db.fetch(
        "select id, finish, thumb_path from ref_assets where active and kind = 'finish' and finish = any(%s)",
        [p["finish"] for p in picked if p.get("finish")])}
    return [{"ref_id": p["id"], "name": p["name"], "finish": p.get("finish"), "layout": p.get("layout"),
             "source": p.get("source"), "reviewed": p.get("reviewed"), "thumb": p.get("thumb_path"),
             "file": p.get("file_path"), "description": p.get("description"),
             "finish_ref": (swatches.get(p.get("finish")) or {}).get("id"),
             "finish_thumb": (swatches.get(p.get("finish")) or {}).get("thumb_path")} for p in picked]


async def describe(ref_id: int) -> dict | None:
    """One kitchen as stored on an idea, or None if it is not a usable kitchen."""
    r = await db.fetchrow("select id, name, finish, layout, source, reviewed, thumb_path, file_path, description "
                          "from ref_assets where id = %s and active and kind = 'kitchen'", ref_id)
    if not r:
        return None
    swatch = await db.fetchrow("select id, thumb_path from ref_assets where active and kind = 'finish' and finish = %s "
                               "limit 1", r["finish"]) if r["finish"] else None
    return {"ref_id": r["id"], "name": r["name"], "finish": r["finish"], "layout": r["layout"], "source": r["source"],
            "reviewed": r["reviewed"], "thumb": r["thumb_path"], "file": r["file_path"], "description": r["description"],
            "finish_ref": swatch["id"] if swatch else None, "finish_thumb": swatch["thumb_path"] if swatch else None}


def as_brief(k: dict) -> str:
    """The kitchen as the video agents read it (Rule 8). The finish name is for the pictures, never for the voice."""
    return (f"THE KITCHEN (a real MAGPPIE kitchen: set every scene in it, identical from scene to scene). "
            f"Layout: {k.get('layout') or 'as in the reference photo'}. "
            f"Finish: {k.get('finish') or 'as in the reference photo'} (an internal name: never say it, or any colour "
            f"of the stone, in the voice-over). Every cabinet, door, drawer and surface is this SILVERSTONE finish. "
            f"The reference photo shows: {k.get('description') or 'a MAGPPIE kitchen'}")


async def record(video_id: int, k: dict) -> None:
    """After the lookbook is approved: this video used this kitchen and finish."""
    for ref, role in ((k.get("ref_id"), "kitchen"), (k.get("finish_ref"), "finish")):
        if ref:
            await db.execute("insert into ref_uses (ref_id, video_id, role) values (%s, %s, %s)", ref, video_id, role)
