"""Image and video generation through Higgsfield, saved on the server for the dashboard.

generate() submits a job, waits for it, downloads the result into data/media and returns the
local paths (/media/...), so the dashboard shows the file itself, plus the job ids and the
addresses of the files on Higgsfield (for the "Open on Higgsfield" button).
"""

import asyncio
import logging
import re
import time

import httpx

from . import higgsfield
from .config import get_settings

log = logging.getLogger("mai.media")
ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
MEDIA_URL = re.compile(r"^https?://\S+\.(?:png|jpe?g|webp|mp4|mov|webm)(?:\?\S*)?$", re.I)
DONE = {"completed", "complete", "succeeded", "success", "done", "ready"}
FAILED = {"failed", "error", "canceled", "cancelled", "nsfw", "rejected"}


class Rejected(RuntimeError):
    """Higgsfield did not accept the request. No job was started and nothing was spent."""

    def __init__(self, message: str, account: bool = False):
        super().__init__(message)
        self.account = account          # True when the account itself is the reason (a limit or the plan), not the request


def _refusal(reply) -> "Rejected":
    """Higgsfield's own reason for refusing, in plain words."""
    reasons = [v for k, v in _walk(reply) if k in ("error", "message", "detail") and isinstance(v, str) and len(v) > 8]
    why = reasons[0] if reasons else str(reply)[:300]
    if re.search(r"daily generation limit|grace period", why, re.I):
        return Rejected("Higgsfield has stopped generations on your account for today. Its message: \"" + why + "\" "
                        "Nothing was spent. Check the plan and billing on higgsfield.ai, or try again after the limit resets.", True)
    if re.search(r"limit|plan|credit|subscription|payment|quota", why, re.I):
        return Rejected("Higgsfield refused because of the account: \"" + why + "\" Nothing was spent.", True)
    return Rejected("Higgsfield did not accept the request: " + why[:400])


def media_dir():
    d = get_settings().data_dir / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def _job_ids(result) -> list[str]:
    ids = []
    for k, v in _walk(result):
        if isinstance(v, str) and ID.match(v) and str(k).lower() in ("id", "job_id", "jobid", "generation_id"):
            ids.append(v)
        elif isinstance(v, list) and str(k).lower() in ("job_ids", "ids", "jobs") and all(isinstance(x, str) for x in v):
            ids += [x for x in v if ID.match(x)]
    return list(dict.fromkeys(ids))


def _urls(result) -> list[str]:
    raw = [v for k, v in _walk(result) if k == "rawUrl" and isinstance(v, str)]
    if raw:
        return list(dict.fromkeys(raw))
    found = [v for _, v in _walk(result) if isinstance(v, str) and MEDIA_URL.match(v) and "_min." not in v]
    return list(dict.fromkeys(found))


def _statuses(result) -> list[str]:
    return [str(v).lower() for k, v in _walk(result) if k == "status" and isinstance(v, str)]


async def _download(url: str, name: str) -> str:
    ext = re.search(r"\.(png|jpe?g|webp|mp4|mov|webm)(?:\?|$)", url, re.I)
    fname = f"{name}.{ext.group(1).lower() if ext else 'bin'}"
    async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        (media_dir() / fname).write_bytes(r.content)
    return f"/media/{fname}"


async def cost(kind: str, plan: dict) -> dict:
    """Ask Higgsfield what this would cost. Nothing is generated and no credits are spent."""
    args = {"params": {**{k: v for k, v in plan.items() if v is not None}, "get_cost": True}}
    return await higgsfield.call(f"generate_{kind}", args, timeout=120)


async def generate(kind: str, plan: dict, wait_seconds: int = 1800) -> tuple[list[str], list[str], list[str]]:
    """kind is 'image' or 'video'. plan holds model, prompt and the model's settings. Spends credits."""
    params = {k: v for k, v in plan.items() if v is not None}
    submitted = await higgsfield.call(f"generate_{kind}_batch", {"requests": [{"index": 0, "params": params}]},
                                      timeout=180)
    log.info("higgsfield %s submitted: %s", kind, str(submitted)[:500])
    ids = _job_ids(submitted)
    if not ids:
        raise _refusal(submitted)
    jobs = [{"index": i, "job_id": j} for i, j in enumerate(ids)]
    deadline = time.time() + wait_seconds
    while True:
        state = await higgsfield.call("jobs_wait", {"jobs": jobs, "timeout_seconds": 15}, timeout=120)
        st = _statuses(state)
        if any(x in FAILED for x in st):
            raise RuntimeError(f"Higgsfield could not make this {kind}: {str(state)[:400]}")
        if state.get("all_terminal") or (st and all(x in DONE for x in st)):
            urls = _urls(state)
            if not urls:
                raise RuntimeError(f"Higgsfield finished but returned no file: {str(state)[:400]}")
            break
        if time.time() > deadline:
            raise RuntimeError("Higgsfield took too long. The job may still finish; check the Higgsfield library.")
        await asyncio.sleep(max(3, min(int(state.get("poll_after_seconds") or 5), 20)))
    saved = [await _download(u, f"{kind}_{ids[min(i, len(ids) - 1)]}") for i, u in enumerate(urls)]
    return saved, ids, urls
