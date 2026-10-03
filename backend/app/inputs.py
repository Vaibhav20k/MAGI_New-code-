"""Reads the user's instruction files in inputs/ (crawler rules, seed sources, brand guide, formats)."""

import re
from urllib.parse import urlparse

from . import db
from .config import get_settings

URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def _read(name: str) -> str:
    p = get_settings().inputs_dir / name
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


def crawler_rules() -> str:
    return _read("crawler-rules.md")


def approval_rules() -> str:
    """Section 5 onward of crawler-rules.md — the auto-save / hold / never-save buckets."""
    text = crawler_rules()
    m = re.search(r"^##\s*5\..*", text, re.M)
    return text[m.start():] if m else text


def brand_guide() -> str:
    return _filled(_read("brand-guide.md"))


def output_formats() -> str:
    return _read("output-formats.md")


def section(md: str, heading: str) -> str:
    """Body of the '## <heading>' section of a markdown file."""
    m = re.search(rf"^##\s*{re.escape(heading)}.*?$(.*?)(?=^##\s|\Z)", md, re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def kind_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube_video" if ("/watch" in url or "/shorts/" in url or "youtu.be" in host) else "youtube_channel"
    for k in ("instagram", "linkedin", "pinterest", "facebook"):
        if k in host:
            return k
    return "website"


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _own_and_others() -> tuple[str, str]:
    """seed-sources.md split into the company's own links and everybody else's."""
    text = _read("seed-sources.md")
    m = re.search(r"^##\s*Our own.*?$(.*?)(?=^##\s|\Z)", text, re.M | re.S | re.I)
    return (m.group(1), text[:m.start()] + text[m.end():]) if m else ("", text)


def own_urls() -> list[str]:
    """The company's own website and channels: read into the knowledge, never crawled as outside inspiration."""
    return list(dict.fromkeys(u.rstrip(".,;") for u in URL_RE.findall(_own_and_others()[0])))


def seed_urls() -> list[str]:
    """Real links only: unfilled template placeholders like [https://...] are ignored."""
    text = _own_and_others()[1]
    urls = []
    for raw in URL_RE.findall(text):
        if "..." in raw or "[" in raw:
            continue
        u = raw.rstrip(".,;")
        p = urlparse(u)
        if "." not in p.netloc:
            continue
        if kind_for(u) != "website" and len(p.path.strip("/@")) < 2:
            continue                     # a bare platform address with no handle
        urls.append(u)
    return list(dict.fromkeys(urls))


def _filled(md: str) -> str:
    """A template with its unfilled [placeholder] lines removed."""
    keep = []
    for line in md.splitlines():
        body = line.split(":", 1)[-1].strip() if ":" in line else line.strip().lstrip("-").strip()
        if re.fullmatch(r"\[[^\]]*\]", body) or "[...]" in line:
            continue
        keep.append(line)
    text = "\n".join(keep)
    first = re.search(r"^## ", text, re.M)          # skip the instructions above the first section
    text = text[first.start():] if first else text
    answered = [l for l in text.splitlines() if l.strip() and not l.startswith("#") and len(l.strip()) >= 15]
    return text if answered else ""


async def sync_seed_sources() -> int:
    """Put every link from seed-sources.md into the sources table as a seed."""
    n = 0
    for u in seed_urls():
        await db.execute(
            """insert into sources (url, domain, kind, status) values (%s,%s,%s,'seed')
               on conflict (url) do update set status = case when sources.status = 'blocked'
                                                         then 'blocked' else 'seed' end""",
            u, domain_of(u), kind_for(u))
        n += 1
    return n


async def blocked_domains() -> set[str]:
    rows = await db.fetch("select domain from sources where status = 'blocked'")
    rules = await db.fetch("select content from manager_rules where kind = 'block_site'")
    return {r["domain"] for r in rows} | {domain_of(r["content"]) or r["content"] for r in rules}
