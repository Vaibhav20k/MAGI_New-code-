"""Cognee memory service — a small HTTP wrapper around the Cognee SDK (1.6.2).

Endpoints
  GET  /health
  POST /add              {"items":[{"id","text","meta"}], "dataset":"learnings"}
  POST /cognify          {"dataset":"learnings"}          (background job)
  GET  /cognify/status
  POST /search           {"query","dataset","top_k":8,"mode":"graph"|"chunks"|"summaries"}
  POST /forget           {"id","dataset"}

All configuration comes from environment variables (see docker-compose.cognee.yml).
Run with a single uvicorn worker: the cognify job state lives in this process.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import cognee  # reads its configuration from the process environment at import
from cognee import SearchType
from cognee.tasks.ingestion.data_item import DataItem

log = logging.getLogger("cognee-service")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

# Stable namespace: data_id = uuid5(NAMESPACE, "<dataset>:<item id>"). Never change it,
# or previously added items can no longer be found for update / forget.
NAMESPACE = uuid.UUID("6f1c2b0e-6d0a-5c1e-9b57-3a2f4d8c1e77")

DEFAULT_DATASET = os.getenv("COGNEE_DEFAULT_DATASET", "learnings")
CHUNKS_PER_BATCH = int(os.getenv("COGNIFY_CHUNKS_PER_BATCH", "4"))
DATA_PER_BATCH = int(os.getenv("COGNIFY_DATA_PER_BATCH", "2"))
COGNIFY_TIMEOUT_S = int(os.getenv("COGNIFY_TIMEOUT_S", "3600"))
SEARCH_TIMEOUT_S = int(os.getenv("SEARCH_TIMEOUT_S", "120"))


def data_id_for(dataset: str, item_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{dataset}:{item_id}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:600]}"


# --------------------------------------------------------------------------- LLM call counter
LLM_CALLS = {"ok": 0, "failed": 0}

try:  # best effort: count LiteLLM requests so callers can watch free-tier usage
    import litellm
    from litellm.integrations.custom_logger import CustomLogger

    class _CallCounter(CustomLogger):
        def log_success_event(self, kwargs, response_obj, start_time, end_time):
            LLM_CALLS["ok"] += 1

        def log_failure_event(self, kwargs, response_obj, start_time, end_time):
            LLM_CALLS["failed"] += 1

        async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
            LLM_CALLS["ok"] += 1

        async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
            LLM_CALLS["failed"] += 1

    litellm.callbacks.append(_CallCounter())
except Exception as exc:  # pragma: no cover
    log.warning("LLM call counter not installed: %s", _err(exc))


# --------------------------------------------------------------------------- setup
_setup_done = False
_setup_lock = asyncio.Lock()


async def ensure_setup() -> None:
    """Create Cognee's relational tables / default user once (idempotent)."""
    global _setup_done
    if _setup_done:
        return
    async with _setup_lock:
        if _setup_done:
            return
        from cognee.low_level import setup

        await setup()
        _setup_done = True


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await ensure_setup()
        log.info("cognee setup complete")
    except Exception as exc:  # the DB may not be up yet; retried lazily on first request
        log.warning("cognee setup deferred: %s", _err(exc))
    yield


app = FastAPI(title="Cognee memory service", version="1.0", lifespan=lifespan)

# add/forget are serialised; cognify runs as one background job at a time.
_write_lock = asyncio.Lock()


# --------------------------------------------------------------------------- models
class Item(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)


class AddBody(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=500)
    dataset: str = DEFAULT_DATASET


class CognifyBody(BaseModel):
    dataset: str = DEFAULT_DATASET


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    dataset: str = DEFAULT_DATASET
    top_k: int = Field(default=8, ge=1, le=50)
    mode: Literal["graph", "chunks", "summaries"] = "graph"


class ForgetBody(BaseModel):
    id: str = Field(min_length=1)
    dataset: str = DEFAULT_DATASET


# --------------------------------------------------------------------------- helpers
async def _existing(data_ids: list[uuid.UUID]) -> dict[str, dict]:
    """Return {data_id: external_metadata} for items already stored in Cognee."""
    from sqlalchemy import select

    from cognee.infrastructure.databases.relational import get_relational_engine
    from cognee.modules.data.models import Data

    engine = get_relational_engine()
    async with engine.get_async_session() as session:
        rows = (
            await session.execute(
                select(Data.id, Data.external_metadata).where(Data.id.in_(data_ids))
            )
        ).all()
    out: dict[str, dict] = {}
    for row_id, ext in rows:
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        out[str(row_id)] = ext or {}
    return out


_TEXT_KEYS = ("text", "content", "summary", "description", "answer", "name")


def _texts(obj: Any) -> list[str]:
    """Flatten whatever cognee.search returns into a list of plain strings."""
    if obj is None:
        return []
    if isinstance(obj, str):
        return [obj.strip()] if obj.strip() else []
    if isinstance(obj, (list, tuple, set)):
        out: list[str] = []
        for part in obj:
            out.extend(_texts(part))
        return out
    if hasattr(obj, "search_result"):  # cognee SearchResult model
        return _texts(obj.search_result)
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    if isinstance(obj, dict):
        if "search_result" in obj:
            return _texts(obj["search_result"])
        for key in _TEXT_KEYS:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return [value.strip()]
        return [json.dumps(obj, default=str, ensure_ascii=False)]
    return [str(obj)]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _is_missing(exc: BaseException) -> bool:
    """True for 'dataset / data does not exist (yet)' style errors."""
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    return (
        "notfound" in name
        or "not found" in text
        or "no datasets" in text
        or "does not exist" in text
        or "no data" in text
    )


# --------------------------------------------------------------------------- cognify job
JOB: dict[str, Any] = {
    "state": "idle",  # idle | running
    "dataset": None,
    "started_at": None,
    "finished_at": None,
    "duration_s": None,
    "last_result": None,
    "last_error": None,
    "llm_calls": None,
    "runs": 0,
}
_queue: list[str] = []
_job_task: asyncio.Task | None = None


def _status() -> dict[str, Any]:
    return {**JOB, "queued": list(_queue), "llm_calls_total": dict(LLM_CALLS)}


def _summarise_run(result: Any) -> Any:
    """cognify returns {dataset_id: PipelineRunInfo}; keep only the readable bits."""
    if isinstance(result, dict):
        out = {}
        for key, info in result.items():
            status = getattr(info, "status", None) or type(info).__name__
            out[str(key)] = str(status)
        return out
    return str(result)[:500]


async def _run_queue() -> None:
    while _queue:
        dataset = _queue.pop(0)
        calls_before = dict(LLM_CALLS)
        started = time.monotonic()
        JOB.update(state="running", dataset=dataset, started_at=_now(), finished_at=None)
        try:
            await ensure_setup()
            result = await asyncio.wait_for(
                cognee.cognify(
                    datasets=[dataset],
                    chunks_per_batch=CHUNKS_PER_BATCH,
                    data_per_batch=DATA_PER_BATCH,
                ),
                timeout=COGNIFY_TIMEOUT_S,
            )
            JOB.update(last_result=_summarise_run(result), last_error=None)
            log.info("cognify finished for %s: %s", dataset, JOB["last_result"])
        except BaseException as exc:  # noqa: BLE001 - report everything in /cognify/status
            JOB.update(last_result=None, last_error=_err(exc))
            log.exception("cognify failed for %s", dataset)
            if isinstance(exc, asyncio.CancelledError):
                JOB.update(state="idle")
                raise
        finally:
            JOB.update(
                finished_at=_now(),
                duration_s=round(time.monotonic() - started, 1),
                llm_calls={k: LLM_CALLS[k] - calls_before[k] for k in LLM_CALLS},
                runs=JOB["runs"] + 1,
            )
    JOB.update(state="idle")


# --------------------------------------------------------------------------- endpoints
@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "cognee_version": getattr(cognee, "__version__", None),
        "llm_model": os.getenv("LLM_MODEL"),
        "embedding_model": os.getenv("EMBEDDING_MODEL"),
        "setup_done": _setup_done,
        "cognify_state": JOB["state"],
    }


@app.post("/add")
async def add(body: AddBody) -> dict[str, Any]:
    dataset = body.dataset
    # last occurrence of an id wins
    items = list({item.id: item for item in body.items}.values())
    ids = {item.id: data_id_for(dataset, item.id) for item in items}

    async with _write_lock:
        try:
            await ensure_setup()
            existing = await _existing(list(ids.values()))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"cognee store unavailable: {_err(exc)}")

        report: list[dict[str, Any]] = []
        to_add: list[DataItem] = []
        for item in items:
            data_id = ids[item.id]
            sha = _sha(item.text)
            entry = {"id": item.id, "data_id": str(data_id)}
            previous = existing.get(str(data_id))
            if previous is not None and previous.get("text_sha256") == sha:
                report.append({**entry, "status": "unchanged"})
                continue
            if previous is not None:
                if JOB["state"] == "running":
                    report.append({**entry, "status": "error",
                                   "error": "text changed but cognify is running; retry later"})
                    continue
                try:  # text changed: drop the old document and its graph before re-adding
                    await cognee.forget(data_id=data_id, dataset=dataset)
                except Exception as exc:
                    report.append({**entry, "status": "error", "error": _err(exc)})
                    continue
                entry["status"] = "updated"
            else:
                entry["status"] = "added"
            report.append(entry)
            to_add.append(
                DataItem(
                    data=item.text,
                    label=item.id,
                    external_metadata={**item.meta, "source_id": item.id, "text_sha256": sha},
                    data_id=data_id,
                )
            )

        if to_add:
            try:
                await cognee.add(to_add, dataset_name=dataset, node_set=[dataset])
            except Exception as exc:
                log.exception("add failed")
                raise HTTPException(status_code=500, detail=f"cognee.add failed: {_err(exc)}")

    counts = {s: sum(1 for r in report if r["status"] == s)
              for s in ("added", "updated", "unchanged", "error")}
    return {"dataset": dataset, **counts, "needs_cognify": bool(to_add), "items": report}


@app.post("/cognify")
async def cognify(body: CognifyBody) -> dict[str, Any]:
    """Start (or queue) a background graph build. Returns immediately."""
    global _job_task
    running = _job_task is not None and not _job_task.done()
    if running:
        if body.dataset not in _queue:
            _queue.append(body.dataset)  # run again afterwards to pick up newer data
        return {"started": False, "already_running": True, **_status()}
    _queue.append(body.dataset)
    JOB.update(state="running", dataset=body.dataset, started_at=_now(), finished_at=None)
    _job_task = asyncio.create_task(_run_queue())
    return {"started": True, "already_running": False, **_status()}


@app.get("/cognify/status")
async def cognify_status() -> dict[str, Any]:
    return _status()


_MODES = {
    "graph": SearchType.GRAPH_COMPLETION,
    "chunks": SearchType.CHUNKS,
    "summaries": SearchType.SUMMARIES,
}


async def _search(query: str, query_type: SearchType, dataset: str, top_k: int, **kwargs) -> Any:
    return await asyncio.wait_for(
        cognee.search(query, query_type=query_type, datasets=[dataset], top_k=top_k, **kwargs),
        timeout=SEARCH_TIMEOUT_S,
    )


@app.post("/search")
async def search(body: SearchBody) -> dict[str, Any]:
    out: dict[str, Any] = {
        "query": body.query,
        "dataset": body.dataset,
        "mode": body.mode,
        "answer": None,
        "results": [],
    }
    try:
        await ensure_setup()
        if body.mode == "graph":
            # 1 LLM call: answer generated from the knowledge-graph context
            answer = _texts(await _search(body.query, _MODES["graph"], body.dataset, body.top_k))
            out["answer"] = "\n".join(answer) if answer else None
            # supporting source passages (vector search only, no LLM call)
            chunks = await _search(body.query, SearchType.CHUNKS, body.dataset, body.top_k)
            out["results"] = _dedupe(_texts(chunks))[: body.top_k]
        else:
            raw = await _search(body.query, _MODES[body.mode], body.dataset, body.top_k)
            out["results"] = _dedupe(_texts(raw))[: body.top_k]
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="search timed out")
    except Exception as exc:
        if _is_missing(exc):
            out["note"] = f"nothing searchable in dataset yet: {_err(exc)}"
            return out
        log.exception("search failed")
        raise HTTPException(status_code=500, detail=f"cognee.search failed: {_err(exc)}")
    return out


@app.post("/forget")
async def forget(body: ForgetBody) -> dict[str, Any]:
    data_id = data_id_for(body.dataset, body.id)
    if JOB["state"] == "running":
        raise HTTPException(status_code=409, detail="cognify is running; retry when idle")
    async with _write_lock:
        try:
            await ensure_setup()
            existing = await _existing([data_id])
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"cognee store unavailable: {_err(exc)}")
        if str(data_id) not in existing:
            return {"id": body.id, "data_id": str(data_id), "dataset": body.dataset,
                    "status": "not_found"}
        try:
            result = await cognee.forget(data_id=data_id, dataset=body.dataset)
        except Exception as exc:
            log.exception("forget failed")
            raise HTTPException(status_code=500, detail=f"cognee.forget failed: {_err(exc)}")
    return {"id": body.id, "data_id": str(data_id), "dataset": body.dataset,
            "status": "forgotten", "cognee": result}
