"""The reference library: MAGPPIE's own finishes, kitchens, vanities, wardrobes, clips and logo.

Read from the shared Google Drive folder named in inputs/reference-library.json, copied into MAGI's storage
(/media/references), described by Gemini, and searchable by meaning. Lookbooks and videos take their kitchens,
finishes and starting pictures from here, so what is shown is what MAGPPIE really makes.

The Drive stays read-only: nothing is ever written back to it.
"""

import asyncio
import html
import json
import logging
import re
import subprocess
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db, embed, vision
from .config import get_settings
from .media import media_dir

log = logging.getLogger("mai.references")
router = APIRouter(prefix="/api/references")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEOS = {".mp4", ".mov", ".webm", ".m4v"}
KINDS = ("finish", "kitchen", "vanity", "wardrobe", "video", "logo", "frame", "other")
LAYOUTS = ("L-shape", "U-shape", "island", "parallel", "straight", "peninsula", "other")
BATCH = 4                                         # pictures per question to Gemini
ENTRY = re.compile(r'<div class="flip-entry" id="entry-([^"]+)".*?<a href="([^"]+)".*?flip-entry-title">([^<]*)<', re.S)

state = {"running": False, "step": "", "done": 0, "total": 0, "error": None, "last": None}
_task: asyncio.Task | None = None


# ---------------- reading the rules and the Drive (pure parts are tested) ----------------

def config() -> dict:
    p = get_settings().inputs_dir / "reference-library.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"inputs/reference-library.json could not be read: {e}")


def parse_folder(page: str) -> list[tuple[str, str, bool]]:
    """(id, name, is_folder) for every entry of a public Drive folder's listing page."""
    return [(fid, html.unescape(name).strip(), "/folders/" in href) for fid, href, name in ENTRY.findall(page)]


def finish_name(filename: str) -> str:
    """'MAGPPIE  EARTH GREY .jpg' → 'MAGPPIE EARTH GREY'."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return re.sub(r"\s+", " ", stem.replace("_", " ")).strip().upper()


def classify(path: str, name: str, cfg: dict) -> dict | None:
    """How a Drive file enters the library, or None when it is skipped."""
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    folder = path.strip("/").lower()
    if ext in {e.lower() for e in cfg.get("skip_extensions", [])}:
        return None
    if any(folder == s.lower().strip("/") or folder.startswith(s.lower().strip("/") + "/") for s in cfg.get("skip_folders", [])):
        return None
    media_type = "image" if ext in IMAGES else "video" if ext in VIDEOS else None
    if not media_type:
        return None
    rule = next((r for r in cfg.get("rules", []) if r["match"].lower() in folder), {})
    kind = rule.get("kind") or ("video" if media_type == "video" else "other")
    if media_type == "video":
        kind = "video"
    out = {"kind": kind if kind in KINDS else "other", "source": rule.get("source"), "media_type": media_type,
           "finish": None, "finish_from": None}
    if rule.get("finish_from_name"):
        out.update(finish=finish_name(name), finish_from="file")
    return out


async def _list(client: httpx.AsyncClient, folder_id: str, path: str = "") -> list[dict]:
    r = await client.get(f"https://drive.google.com/embeddedfolderview?id={folder_id}")
    r.raise_for_status()
    found = []
    for fid, name, is_folder in parse_folder(r.text):
        if is_folder:
            found += await _list(client, fid, f"{path}/{name}")
        else:
            found.append({"drive_id": fid, "name": name, "path": path})
    return found


# ---------------- copying files in ----------------

def _rel(p: Path) -> str:
    return "/media/" + p.relative_to(media_dir()).as_posix()


async def _download(client: httpx.AsyncClient, drive_id: str, dest: Path) -> int:
    """Streams a shared Drive file to disk; large files skip Google's virus-scan page with confirm=t."""
    url = f"https://drive.usercontent.google.com/download?id={drive_id}&export=download&confirm=t"
    part = dest.with_suffix(dest.suffix + ".part")
    async with client.stream("GET", url) as r:
        r.raise_for_status()
        if "text/html" in r.headers.get("content-type", ""):
            raise RuntimeError("Drive returned a web page instead of the file (is the folder still shared?)")
        size = 0
        with part.open("wb") as f:
            async for chunk in r.aiter_bytes(1 << 16):
                f.write(chunk)
                size += len(chunk)
    part.replace(dest)
    return size


def _picture_facts(src: Path, thumb: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(src) as im:
        w, h = im.size
        im = im.convert("RGB")
        im.thumbnail((512, 512))
        im.save(thumb, "JPEG", quality=82)
    return w, h


def _video_stills(src: Path, folder: Path, key: str) -> list[Path]:
    """Three stills (at 20, 50 and 80 percent) for describing a clip; the middle one is its thumbnail."""
    try:
        length = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                                      capture_output=True, text=True, timeout=60).stdout.strip() or 0)
    except (ValueError, subprocess.SubprocessError):
        length = 0
    stills = []
    for n, at in enumerate((.2, .5, .8), 1):
        out = folder / f"{key}-{n}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0, length * at):.2f}", "-i", str(src), "-frames:v", "1",
                        "-vf", "scale='min(1024,iw)':-2", str(out)], capture_output=True, timeout=120)
        if out.exists():
            stills.append(out)
    return stills


async def _bring_in(client: httpx.AsyncClient, f: dict, how: dict) -> None:
    base = media_dir() / "references"
    for sub in ("files", "thumbs", "stills"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    ext = f["name"].rsplit(".", 1)[-1].lower()
    dest = base / "files" / f"{f['drive_id']}.{ext}"
    size = dest.stat().st_size if dest.exists() else await _download(client, f["drive_id"], dest)
    thumb = base / "thumbs" / f"{f['drive_id']}.jpg"
    width = height = None
    if how["media_type"] == "image":
        width, height = await asyncio.to_thread(_picture_facts, dest, thumb)
    else:
        stills = await asyncio.to_thread(_video_stills, dest, base / "stills", f["drive_id"])
        if stills:
            width, height = await asyncio.to_thread(_picture_facts, stills[len(stills) // 2], thumb)
    await db.execute(
        """insert into ref_assets (drive_id, path, name, kind, source, media_type, finish, finish_from, file_path, thumb_path,
                                   width, height, bytes)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (drive_id) do update set path = excluded.path, name = excluded.name, active = true, updated_at = now()""",
        f["drive_id"], f["path"], f["name"], how["kind"], how["source"], how["media_type"], how["finish"], how["finish_from"],
        _rel(dest), _rel(thumb) if thumb.exists() else None, width, height, size)


async def sync() -> dict:
    """Bring new Drive files in, mark removed ones inactive, then describe what is new."""
    if state["running"]:
        return {"started": False, "reason": "A sync is already running."}
    state.update(running=True, step="Reading the Drive folder", done=0, total=0, error=None)
    added = gone = described = 0
    try:
        cfg = config()
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=20), follow_redirects=True, headers={"User-Agent": UA}) as client:
            listed = await _list(client, cfg["drive_folder_id"])
            wanted = [(f, how) for f in listed if (how := classify(f["path"], f["name"], cfg))]
            have = {r["drive_id"] for r in await db.fetch("select drive_id from ref_assets where drive_id is not null and active")}
            new = [(f, how) for f, how in wanted if f["drive_id"] not in have]
            state.update(step="Copying new files", total=len(new))
            gate = asyncio.Semaphore(4)

            async def one(f, how):
                nonlocal added
                async with gate:
                    try:
                        await _bring_in(client, f, how)
                        added += 1
                    except Exception as e:  # noqa: BLE001 — one bad file must not stop the rest
                        log.warning("reference %s (%s) could not be copied: %s", f["name"], f["drive_id"], e)
                    state["done"] += 1
            await asyncio.gather(*(one(f, how) for f, how in new))
            ids = [f["drive_id"] for f, _ in wanted]
            if ids:
                gone = len(await db.fetch("update ref_assets set active = false, updated_at = now() where drive_id is not null "
                                          "and active and not (drive_id = any(%s)) returning id", ids))
        described = await describe_pending()
        state["last"] = {"listed": len(listed), "kept": len(wanted), "added": added, "removed": gone, "described": described}
        return {"started": True, **state["last"]}
    except Exception as e:  # noqa: BLE001
        state["error"] = str(e)[:300]
        log.exception("reference sync failed")
        return {"started": True, "error": state["error"]}
    finally:
        state.update(running=False, step="")


# ---------------- describing pictures ----------------

PROMPT = """You are cataloguing reference pictures for MAGPPIE, which makes kitchens, wardrobes and vanities entirely from
SILVERSTONE, an engineered stone. These pictures will be searched later to choose the right kitchen, finish and room
for a video. Describe what is visible; do not guess beyond it.

Known finish names (use one only if the surface clearly matches it, otherwise null): %s

The pictures are numbered 1 to %d, in order. For each one return:
{"n": <number>, "source": "real" | "render" (a photograph of a real room, or a computer render),
 "room": "kitchen" | "vanity" | "wardrobe" | "material" | "other",
 "layout": one of %s, or null if not a kitchen,
 "finish_guess": a finish name from the list or null,
 "colours": 2 to 4 plain colour words,
 "description": at most 40 words: what is shown, the camera angle, the light, the mood,
 "tags": 5 to 10 short search words,
 "flags": {"people": true|false, "wood_or_steel_look": true|false, "text_or_logo": true|false}}
Return JSON: {"items": [ ... one object per picture ... ]}"""


def _stills_for(row: dict) -> list[Path]:
    base = media_dir() / "references"
    if row["media_type"] == "video":
        key = Path(row["file_path"]).stem
        return [p for n in (1, 2, 3) if (p := base / "stills" / f"{key}-{n}.jpg").exists()]
    return [media_dir() / row["file_path"].removeprefix("/media/")]


def catalogue_text(row: dict) -> str:
    """What a reference is searched by."""
    parts = [row.get("kind"), row.get("source"), row.get("room"), row.get("layout"),
             f"finish {row['finish']}" if row.get("finish") else None, " ".join(row.get("colours") or []),
             row.get("description"), " ".join(row.get("tags") or [])]
    return ". ".join(p for p in parts if p)


async def describe_pending(limit: int | None = None) -> int:
    rows = await db.fetch(
        "select id, name, kind, media_type, file_path, finish, finish_from, source from ref_assets "
        "where active and described_at is null and kind <> 'logo' and file_path is not null order by id limit %s",
        limit or 10000)
    finishes = [r["finish"] for r in await db.fetch("select distinct finish from ref_assets where kind = 'finish' and finish is not null")]
    done = 0
    state.update(step="Describing pictures", done=0, total=len(rows))
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        pictures, owner = [], []
        for row in batch:                            # a clip contributes its middle still
            stills = _stills_for(row)
            if stills:
                pictures.append(stills[len(stills) // 2].read_bytes())
                owner.append(row)
        if not pictures:
            continue
        try:
            answer = await vision.ask(PROMPT % (", ".join(finishes) or "(none yet)", len(pictures), ", ".join(LAYOUTS)), pictures)
        except vision.Unavailable as e:
            state["error"] = str(e)
            break
        by_n = {int(it.get("n", 0)): it for it in answer.get("items", []) if isinstance(it, dict) and str(it.get("n", "")).isdigit()}
        for n, row in enumerate(owner, 1):
            it = by_n.get(n)
            if not it:
                continue
            finish, finish_from = row["finish"], row["finish_from"]
            if not finish and it.get("finish_guess") in finishes:
                finish, finish_from = it["finish_guess"], "guess"
            layout = it.get("layout") if it.get("layout") in LAYOUTS else None
            colours = [str(c)[:20] for c in (it.get("colours") or [])][:4]
            tags = [str(t)[:30] for t in (it.get("tags") or [])][:10]
            flags = {k: bool((it.get("flags") or {}).get(k)) for k in ("people", "wood_or_steel_look", "text_or_logo")}
            fields = {"kind": row["kind"], "source": row["source"] or (it.get("source") if it.get("source") in ("real", "render") else None),
                      "room": str(it.get("room") or "")[:20] or None, "layout": layout, "finish": finish, "colours": colours,
                      "description": str(it.get("description") or "")[:400], "tags": tags}
            vec = await embed.embed_one(catalogue_text(fields))
            await db.execute(
                """update ref_assets set source = %s, room = %s, layout = %s, finish = %s, finish_from = %s, colours = %s,
                          description = %s, tags = %s, flags = %s, embedding = %s, described_at = now(), updated_at = now()
                   where id = %s""",
                fields["source"], fields["room"], layout, finish, finish_from, colours, fields["description"], tags,
                db.Jsonb(flags), vec, row["id"])
            done += 1
        state["done"] = done
    return done


# ---------------- search and the dashboard ----------------

FIELDS = ("id, drive_id, path, name, kind, source, media_type, finish, finish_from, layout, room, colours, description, tags, "
          "flags, file_path, thumb_path, width, height, reviewed, usable_as, active, described_at")


async def search(query: str, kinds: list[str] | None = None, n: int = 8) -> list[dict]:
    vec = await embed.embed_one(query)
    return await db.fetch("select * from match_refs(%s, %s, %s)", vec, n, kinds)


@router.get("")
async def list_refs(kind: str = "", reviewed: str = "", q: str = "", limit: int = 400):
    where, args = ["active"], []
    if kind:
        where.append("kind = %s"); args.append(kind)
    if reviewed in ("yes", "no"):
        where.append("reviewed = %s"); args.append(reviewed == "yes")
    if q.strip():
        vec = await embed.embed_one(q.strip())
        return await db.fetch(f"select {FIELDS}, (1 - (embedding <=> %s))::real as similarity from ref_assets "
                              f"where {' and '.join(where)} and embedding is not null order by embedding <=> %s limit %s",
                              vec, *args, vec, min(limit, 400))
    return await db.fetch(f"select {FIELDS} from ref_assets where {' and '.join(where)} "
                          f"order by kind, reviewed, finish nulls last, name limit %s", *args, min(limit, 400))


@router.get("/status")
async def status():
    counts = await db.fetch("select kind, count(*) n, count(*) filter (where described_at is not null) described, "
                            "count(*) filter (where reviewed) reviewed from ref_assets where active group by kind order by kind")
    return {"sync": state, "kinds": counts, "vision_calls_left": vision.calls_left()}


@router.get("/finishes")
async def finishes():
    return [r["finish"] for r in await db.fetch("select distinct finish from ref_assets where kind = 'finish' and active "
                                                "and finish is not null order by finish")]


@router.post("/sync")
async def start_sync():
    global _task
    if state["running"]:
        return {"started": False, "reason": "A sync is already running."}
    _task = asyncio.create_task(sync())
    return {"started": True}


class Edit(BaseModel):
    kind: str | None = None
    finish: str | None = None
    layout: str | None = None
    tags: list[str] | None = None
    reviewed: bool | None = None
    usable_as: str | None = None
    active: bool | None = None


@router.post("/{ref_id}")
async def edit(ref_id: int, body: Edit):
    row = await db.fetchrow(f"select {FIELDS} from ref_assets where id = %s", ref_id)
    if not row:
        raise HTTPException(404, "No such reference.")
    if body.kind is not None and body.kind not in KINDS:
        raise HTTPException(400, "Unknown kind.")
    if body.usable_as is not None and body.usable_as not in ("exact", "style"):
        raise HTTPException(400, "Use is 'exact' or 'style'.")
    if body.layout not in (None, "") and body.layout not in LAYOUTS:
        raise HTTPException(400, "Unknown layout.")
    row = dict(row)
    if body.finish is not None:
        row.update(finish=body.finish.strip().upper() or None, finish_from="person" if body.finish.strip() else None)
    for k in ("kind", "reviewed", "usable_as", "active"):
        if getattr(body, k) is not None:
            row[k] = getattr(body, k)
    if body.layout is not None:
        row["layout"] = body.layout or None
    if body.tags is not None:
        row["tags"] = [t.strip()[:30] for t in body.tags if t.strip()][:12]
    vec = await embed.embed_one(catalogue_text(row)) if row.get("described_at") else None
    await db.execute("""update ref_assets set kind = %s, finish = %s, finish_from = %s, layout = %s, tags = %s, reviewed = %s,
                            usable_as = %s, active = %s, embedding = coalesce(%s, embedding), updated_at = now() where id = %s""",
                     row["kind"], row["finish"], row["finish_from"], row["layout"], row["tags"], row["reviewed"],
                     row["usable_as"], row["active"], vec, ref_id)
    return {"ok": True}
