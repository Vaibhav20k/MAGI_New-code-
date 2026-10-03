"""Instagram and Facebook reading through Apify (public posts only: caption, likes, comments, views).

Apify's free plan gives a small monthly credit, so reading is kept light: a few recent posts per
account, each account at most once a day, and nothing at all once most of the month's credit is used.
LinkedIn is not read: it does not allow it without logging in.
"""

import logging

import httpx

from .config import get_settings

log = logging.getLogger("mai.social")
API = "https://api.apify.com/v2"
BUDGET_USD = 4.0                     # stop before the free $5 runs out
PER_ACCOUNT = 6


async def _headers() -> dict | None:
    t = get_settings().apify_api_token
    return {"Authorization": f"Bearer {t}"} if t else None


async def budget_left() -> bool:
    h = await _headers()
    if not h:
        return False
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            d = (await c.get(f"{API}/users/me/limits", headers=h)).json().get("data", {})
        used = float((d.get("current") or {}).get("monthlyUsageUsd") or 0)
        return used < BUDGET_USD
    except (httpx.HTTPError, ValueError) as e:
        log.info("apify budget check failed: %s", e)
        return False


async def _run(actor: str, payload: dict) -> list[dict]:
    h = await _headers()
    if not h:
        return []
    async with httpx.AsyncClient(timeout=320) as c:
        r = await c.post(f"{API}/acts/{actor}/run-sync-get-dataset-items", headers=h, params={"timeout": 280},
                         json=payload)
    if r.status_code >= 300:
        log.warning("apify %s failed (%s): %s", actor, r.status_code, r.text[:200])
        return []
    data = r.json()
    return data if isinstance(data, list) else []


def _num(x) -> int:
    try:
        return max(0, int(x or 0))
    except (TypeError, ValueError):
        return 0


async def instagram(profile_urls: list[str], per_account: int = PER_ACCOUNT) -> list[dict]:
    items = await _run("apify~instagram-scraper", {"directUrls": profile_urls, "resultsType": "posts",
                                                   "resultsLimit": per_account, "addParentData": False})
    out = []
    for i in items:
        if not i.get("url") or i.get("error"):
            continue
        out.append({"platform": "instagram", "url": i["url"], "account": i.get("ownerUsername") or "",
                    "source_url": i.get("inputUrl") or "", "text": (i.get("caption") or "").strip(),
                    "likes": _num(i.get("likesCount")), "comments": _num(i.get("commentsCount")),
                    "views": _num(i.get("videoPlayCount") or i.get("videoViewCount")),
                    "format": {"Video": "reel", "Sidecar": "carousel", "Image": "image"}.get(i.get("type"), "post"),
                    "posted": (i.get("timestamp") or "")[:10]})
    return out


async def facebook(page_urls: list[str], per_account: int = 4) -> list[dict]:
    items = await _run("apify~facebook-posts-scraper", {"startUrls": [{"url": u} for u in page_urls],
                                                        "resultsLimit": per_account})
    out = []
    for i in items:
        if not i.get("url") or i.get("error"):
            continue
        out.append({"platform": "facebook", "url": i["url"], "account": i.get("pageName") or (i.get("user") or {}).get("name") or "",
                    "source_url": i.get("facebookUrl") or i.get("inputUrl") or "", "text": (i.get("text") or "").strip(),
                    "likes": _num(i.get("likes")), "comments": _num(i.get("comments")), "views": _num(i.get("viewsCount")),
                    "format": "video" if i.get("isVideo") else "post", "posted": (i.get("time") or "")[:10]})
    return out


def as_page(p: dict) -> tuple[str, str, dict]:
    """A post as (title, text, details) the way the crawler stores a page."""
    name = p["platform"].capitalize()
    title = f"{p['account']} on {name}: {p['text'][:70]}".strip()
    stats = f"Likes: {p['likes']}. Comments: {p['comments']}." + (f" Views: {p['views']}." if p["views"] else "")
    md = f"# {title}\n{name} {p['format']} by {p['account']}, posted {p['posted'] or 'recently'}. {stats}\n\n{p['text'][:4000]}"
    meta = {"platform": p["platform"], "channel": p["account"], "likes": p["likes"], "comments": p["comments"],
            "views": p["views"], "format": p["format"], "upload_date": p["posted"]}
    return title, md, meta
