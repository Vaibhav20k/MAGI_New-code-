"""Clients for the self-hosted tools: Crawl4AI (reader), SearXNG (search), yt-dlp (YouTube)."""

import asyncio
import logging
from typing import Any

import httpx

from .config import get_settings

log = logging.getLogger("mai.services")

_http: httpx.AsyncClient | None = None


def http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15), follow_redirects=True)
    return _http


# ---------------- Crawl4AI ----------------

def _markdown_of(r: dict) -> str:
    md = r.get("markdown")
    if isinstance(md, dict):
        return md.get("fit_markdown") or md.get("raw_markdown") or ""
    return md or ""


async def crawl(urls: list[str]) -> list[dict]:
    """Read pages. Returns [{url, ok, title, markdown, internal, external, meta}]."""
    s = get_settings()
    body = {
        "urls": urls,
        "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
        "crawler_config": {"type": "CrawlerRunConfig", "params": {
            "cache_mode": "bypass", "stream": False, "page_timeout": 45000,
            "excluded_tags": ["nav", "footer", "header", "aside", "form"],
            "remove_overlay_elements": True, "check_robots_txt": True}},
    }
    try:
        resp = await http().post(f"{s.crawl4ai_url}/crawl", json=body,
                                 headers={"Authorization": f"Bearer {s.crawl4ai_api_token}"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        log.warning("crawl4ai failed for %s: %s", urls, e)
        return [{"url": u, "ok": False, "error": str(e)} for u in urls]
    out = []
    for r in data.get("results", []):
        links = r.get("links") or {}
        meta = r.get("metadata") or {}
        out.append({
            "url": r.get("url"),
            "ok": bool(r.get("success")),
            "title": meta.get("title") or meta.get("og:title") or "",
            "markdown": _markdown_of(r),
            "internal": [l.get("href") for l in links.get("internal", []) if l.get("href")],
            "external": [l.get("href") for l in links.get("external", []) if l.get("href")],
            "meta": {k: meta.get(k) for k in ("description", "og:description", "article:published_time",
                                              "og:type", "keywords") if meta.get(k)},
            "error": r.get("error_message"),
        })
    return out


# ---------------- SearXNG ----------------

async def search(query: str, *, time_range: str | None = "month", pages: int = 1) -> list[dict]:
    s = get_settings()
    results: list[dict] = []
    for pageno in range(1, pages + 1):
        params: dict[str, Any] = {"q": query, "format": "json", "pageno": pageno, "safesearch": 1}
        if time_range:
            params["time_range"] = time_range
        try:
            r = await http().get(f"{s.searxng_url}/search", params=params)
            r.raise_for_status()
            results += r.json().get("results", [])
        except Exception as e:  # noqa: BLE001
            log.warning("searxng failed for %r: %s", query, e)
            break
    return [{"url": x.get("url"), "title": x.get("title"), "snippet": x.get("content"),
             "published": x.get("publishedDate")} for x in results if x.get("url")]


# ---------------- YouTube (yt-dlp, no API key) ----------------

def _ydl(opts: dict):
    from yt_dlp import YoutubeDL
    return YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, **opts})


def _channel_videos_sync(url: str, limit: int) -> list[dict]:
    base = url.rstrip("/")
    out = []
    for tab in ("/shorts", "/videos"):
        try:
            with _ydl({"extract_flat": True, "playlistend": limit}) as y:
                info = y.extract_info(base + tab, download=False)
            for e in (info or {}).get("entries") or []:
                vid = e.get("id")
                if vid:
                    out.append({"url": f"https://www.youtube.com/{'shorts/' if tab == '/shorts' else 'watch?v='}{vid}",
                                "title": e.get("title"), "views": e.get("view_count")})
        except Exception as ex:  # noqa: BLE001
            log.info("yt-dlp %s%s: %s", base, tab, ex)
    return out


def _video_sync(url: str) -> dict:
    with _ydl({}) as y:
        info = y.extract_info(url, download=False)
    transcript = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        fetched = YouTubeTranscriptApi().fetch(info["id"], languages=["en", "hi", "en-IN"])
        transcript = " ".join(sn.text for sn in fetched)
    except Exception:  # noqa: BLE001 — many videos have no transcript
        pass
    return {
        "url": url, "title": info.get("title"), "description": info.get("description") or "",
        "channel": info.get("channel"), "views": info.get("view_count"), "likes": info.get("like_count"),
        "comments": info.get("comment_count"), "duration": info.get("duration"),
        "upload_date": info.get("upload_date"), "tags": info.get("tags") or [], "transcript": transcript,
    }


async def youtube_channel_videos(url: str, limit: int = 15) -> list[dict]:
    return await asyncio.to_thread(_channel_videos_sync, url, limit)


async def youtube_video(url: str) -> dict:
    return await asyncio.to_thread(_video_sync, url)
