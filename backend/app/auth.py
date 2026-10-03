"""The login in front of the dashboard when it is opened through the public web address.

Requests reach the backend two ways:
  - through the web proxy (Caddy), from the internet. The proxy marks every such request with the
    X-MAI-Public header, and those need a login session.
  - directly on the server (the SSH connection from the office Mac, MAI's own services). Those are
    already protected by the server's SSH key and pass without a login.

One shared password (DASHBOARD_PASSWORD, set with scripts/add-keys.sh). The session is a signed cookie.
Wrong passwords are counted per visitor and overall; too many lock the login for a while.
"""

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .config import get_settings

COOKIE = "mai_session"
DAYS = 14
MIN_PASSWORD = 10
OPEN_PATHS = {"/login", "/api/login", "/api/logout", "/favicon.ico", "/static/logo-white.svg"}
HIDDEN = ("/mcp", "/docs", "/redoc", "/openapi.json")          # never offered to the internet
MAX_TRIES, LOCK_SECONDS, MAX_TRIES_ALL = 5, 900, 40

STATIC = Path(__file__).resolve().parent.parent / "static"
router = APIRouter()
_fails: dict[str, list[float]] = {}        # visitor address → times of recent wrong passwords


def _password() -> str:
    return get_settings().dashboard_password


def ready() -> bool:
    """A login exists only when a long enough password and a signing secret are set."""
    s = get_settings()
    return len(s.dashboard_password) >= MIN_PASSWORD and len(s.session_secret) >= 32


def _key() -> bytes:
    s = get_settings()            # tied to the password, so changing it signs everyone out
    return hmac.new(s.session_secret.encode(), s.dashboard_password.encode(), hashlib.sha256).digest()


def _sign(body: str) -> str:
    return hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()


def new_session() -> str:
    body = f"{int(time.time()) + DAYS * 86400}.{secrets.token_urlsafe(16)}"
    return f"{body}.{_sign(body)}"


def valid_session(value: str | None) -> bool:
    if not value or not ready() or value.count(".") != 2:
        return False
    expires, nonce, sig = value.split(".")
    if not hmac.compare_digest(sig, _sign(f"{expires}.{nonce}")):
        return False
    return expires.isdigit() and int(expires) > time.time()


def _cookies(header: str) -> dict[str, str]:
    out = {}
    for part in header.split(";"):
        if "=" in part:
            k, v = part.strip().split("=", 1)
            out[k] = v
    return out


def _locked(who: str) -> bool:
    now = time.time()
    for k in list(_fails):
        _fails[k] = [t for t in _fails[k] if now - t < LOCK_SECONDS]
        if not _fails[k]:
            del _fails[k]
    return len(_fails.get(who, [])) >= MAX_TRIES or sum(len(v) for v in _fails.values()) >= MAX_TRIES_ALL


async def _reply(send, status: int, body: bytes, content_type: str, extra: list | None = None) -> None:
    headers = [(b"content-type", content_type.encode()), (b"cache-control", b"no-store")] + (extra or [])
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class Gate:
    """Lets a request from the internet through only with a valid session."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if "x-mai-public" not in headers:
            return await self.app(scope, receive, send)
        path = scope["path"]
        if any(path == h or path.startswith(h + "/") for h in HIDDEN):
            return await _reply(send, 404, b"Not found", "text/plain")
        if not ready():
            return await _reply(send, 503, b"The login is not set up yet. Set a dashboard password first.",
                                "text/plain")
        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            origin = headers.get("origin")          # a page on another site may not act on this one
            if origin and urlparse(origin).netloc != headers.get("host"):
                return await _reply(send, 403, b'{"detail":"Request from another site refused."}',
                                    "application/json")
        if path in OPEN_PATHS or valid_session(_cookies(headers.get("cookie", "")).get(COOKIE)):
            return await self.app(scope, receive, send)
        if path.startswith("/api/") or path.startswith("/media/"):
            return await _reply(send, 401, b'{"detail":"Please log in."}', "application/json",
                                [(b"x-mai-login", b"1")])
        return await _reply(send, 302, b"", "text/plain", [(b"location", b"/login")])


@router.get("/login")
async def login_page(request: Request):
    if "x-mai-public" not in request.headers:           # on the office connection there is nothing to log in to
        return RedirectResponse("/")
    return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-store"})


@router.post("/api/login")
async def login(request: Request):
    who = (request.headers.get("x-forwarded-for") or "unknown").split(",")[0].strip()
    if _locked(who):
        return JSONResponse({"detail": "Too many wrong passwords. Try again in 15 minutes."}, status_code=429)
    try:
        password = str((json.loads(await request.body()) or {}).get("password") or "")
    except (ValueError, AttributeError):
        password = ""
    if not ready() or not hmac.compare_digest(password.encode(), _password().encode()):
        _fails.setdefault(who, []).append(time.time())
        return JSONResponse({"detail": "Wrong password."}, status_code=401)
    _fails.pop(who, None)
    r = JSONResponse({"ok": True})
    r.set_cookie(COOKIE, new_session(), max_age=DAYS * 86400, httponly=True, secure=True, samesite="lax", path="/")
    return r


@router.post("/api/logout")
async def logout():
    r = JSONResponse({"ok": True})
    r.delete_cookie(COOKIE, path="/")
    return r
