"""Higgsfield connection for the server: one browser login, then images and videos on request.

Higgsfield exposes its tools over MCP and protects them with OAuth. The user logs in once
(authorization code + PKCE); the tokens are kept on the server and refreshed automatically.
Every generation spends the user's Higgsfield credits, so nothing here runs without an
explicit approval click on the dashboard.
"""

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import get_settings

log = logging.getLogger("mai.higgsfield")
router = APIRouter(prefix="/api/higgsfield")

AUTH = "https://clerk.higgsfield.ai/oauth"
SCOPE = "openid email offline_access"
_pending: dict[str, dict] = {}          # state → {verifier, created}
_lock = asyncio.Lock()


def _store():
    return get_settings().data_dir / "higgsfield.json"


def _load() -> dict:
    p = _store()
    return json.loads(p.read_text()) if p.exists() else {}


def _save(d: dict) -> None:
    p = _store()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d))
    p.chmod(0o600)


def _redirect_uri() -> str:
    return get_settings().higgsfield_redirect_uri


async def _client_id() -> str:
    d = _load()
    if d.get("client_id") and d.get("redirect_uri") == _redirect_uri():
        return d["client_id"]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{AUTH}/register", json={
            "client_name": "Marketing MAI", "redirect_uris": [_redirect_uri()],
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "token_endpoint_auth_method": "none", "scope": SCOPE})
    r.raise_for_status()
    d.update(client_id=r.json()["client_id"], redirect_uri=_redirect_uri())
    _save(d)
    return d["client_id"]


@router.get("/login")
async def login():
    """Send the user to Higgsfield's login page."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    for k in [k for k, v in _pending.items() if time.time() - v["created"] > 900]:
        _pending.pop(k, None)
    _pending[state] = {"verifier": verifier, "created": time.time()}
    q = urlencode({"response_type": "code", "client_id": await _client_id(), "redirect_uri": _redirect_uri(),
                   "scope": SCOPE, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                   "resource": get_settings().higgsfield_mcp_url})
    return RedirectResponse(f"{AUTH}/authorize?{q}")


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Marketing MAI</title>"
        "<body style='background:#060A12;color:#DCE7F5;font:16px system-ui;display:grid;place-items:center;"
        f"height:100vh;margin:0'><div style='max-width:520px;padding:24px'><h2>{title}</h2><p>{body}</p></div>")


@router.get("/callback")
async def callback(code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error:
        return _page("Higgsfield login did not finish", f"{error}: {error_description}")
    p = _pending.pop(state, None)
    if not p or not code:
        return _page("Login link expired", "Go back to the dashboard and press Connect Higgsfield again.")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{AUTH}/token", data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": _redirect_uri(),
            "client_id": await _client_id(), "code_verifier": p["verifier"],
            "resource": get_settings().higgsfield_mcp_url})
    if r.status_code != 200:
        return _page("Higgsfield login did not finish", r.text[:300])
    _keep(r.json())
    return _page("Higgsfield is connected", "You can close this tab and go back to the dashboard.")


def _keep(tok: dict) -> None:
    d = _load()
    d["access_token"] = tok["access_token"]
    if tok.get("refresh_token"):
        d["refresh_token"] = tok["refresh_token"]
    d["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
    _save(d)


async def _token() -> str:
    async with _lock:
        d = _load()
        if not d.get("access_token"):
            raise HTTPException(409, "Higgsfield is not connected. Press Connect Higgsfield on the dashboard.")
        if d.get("expires_at", 0) - time.time() > 90:
            return d["access_token"]
        if not d.get("refresh_token"):
            raise HTTPException(409, "The Higgsfield login expired. Press Connect Higgsfield again.")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{AUTH}/token", data={"grant_type": "refresh_token",
                                                    "refresh_token": d["refresh_token"], "client_id": d["client_id"]})
        if r.status_code != 200:
            raise HTTPException(409, "The Higgsfield login expired. Press Connect Higgsfield again.")
        _keep(r.json())
        return _load()["access_token"]


@asynccontextmanager
async def session():
    tok = await _token()
    async with streamablehttp_client(get_settings().higgsfield_mcp_url,
                                     headers={"Authorization": f"Bearer {tok}"}, timeout=60,
                                     sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            yield s


def _parse(result):
    """Tool results come back as text blocks holding JSON (or plain text)."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
    joined = "\n".join(texts)
    if result.isError:
        raise RuntimeError(f"Higgsfield: {joined[:400]}")
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, TypeError):
        return {"text": joined}


async def call(tool: str, args: dict | None = None, timeout: float = 120):
    async with session() as s:
        return _parse(await asyncio.wait_for(s.call_tool(tool, args or {}), timeout))


@router.get("/status")
async def status():
    d = _load()
    if not d.get("access_token"):
        return {"connected": False}
    try:
        return {"connected": True, **(await call("balance"))}
    except HTTPException as e:
        return {"connected": False, "reason": e.detail}
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "reason": str(e)[:200]}


@router.get("/tools")
async def tools():
    """The tools Higgsfield offers and the inputs each one takes."""
    async with session() as s:
        listed = await s.list_tools()
    return [{"name": t.name, "description": (t.description or "")[:600], "input": t.inputSchema}
            for t in listed.tools]
