from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from pgvector.psycopg import register_vector_async
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb  # noqa: F401  (re-exported for callers: db.Jsonb)
from psycopg_pool import AsyncConnectionPool

from .config import get_settings

_pool: AsyncConnectionPool | None = None


async def _configure(conn):
    await register_vector_async(conn)


async def open_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            get_settings().database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=_configure,
            open=False,
        )
        await _pool.open()
    return _pool


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def conn():
    pool = await open_pool()
    async with pool.connection() as c:
        yield c


async def fetch(sql: str, *args: Any) -> list[dict]:
    async with conn() as c:
        cur = await c.execute(sql, args or None)
        return await cur.fetchall() if cur.description else []


async def fetchrow(sql: str, *args: Any) -> dict | None:
    rows = await fetch(sql, *args)
    return rows[0] if rows else None


async def execute(sql: str, *args: Any) -> None:
    async with conn() as c:
        await c.execute(sql, args or None)


def vec(v) -> np.ndarray:
    """A stored embedding as a numpy array (pgvector hands back its own Vector type)."""
    if hasattr(v, "to_numpy"):
        return v.to_numpy().astype(np.float32)
    return np.asarray(v, dtype=np.float32)
