"""SingleStore access for CapyTeam.

Two transports with one async interface:
  * Data API (HTTPS JSON SQL) for Helios from anywhere, and the local dev image on :9000.
  * MySQL wire protocol (singlestoredb) when the network allows it.

Agents write sessions, events and money claims concurrently; the UI and the coach
read the same tables while they do.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from .config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class DuplicateKey(Exception):
    """A unique key already holds this value (used for exactly-once money claims)."""


class DBError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")


def _jsonable(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return v


class SingleStore:
    def __init__(self, url: str | None = None, database: str | None = None):
        url = url or settings.singlestore_url
        if not url:
            raise DBError("SINGLESTORE_URL is not set")
        u = urlparse(url)
        self.user = unquote(u.username or "root")
        self.password = unquote(u.password or "")
        self.host = u.hostname or "localhost"
        self.port = u.port
        self.database = database or (u.path.strip("/") or settings.singlestore_db)
        self.scheme = u.scheme
        if u.scheme in ("http", "https"):
            port = f":{u.port}" if u.port else ""
            self.base = f"{u.scheme}://{self.host}{port}"
            self.transport = "data-api"
        elif u.scheme in ("mysql", "singlestore", "s2"):
            # Helios also serves the Data API on 443 for the same host; used if TCP is blocked.
            self.base = f"https://{self.host}"
            self.transport = "mysql"
        else:
            raise DBError(f"unsupported SINGLESTORE_URL scheme {u.scheme!r}")
        self._client: httpx.AsyncClient | None = None
        self._mysql_ok: bool | None = None
        self._sem = asyncio.Semaphore(64)

    @property
    def label(self) -> str:
        where = "Helios" if "singlestore.com" in self.host else ("local dev image" if self.host in ("localhost", "127.0.0.1") else self.host)
        via = "MySQL protocol" if (self.transport == "mysql" and self._mysql_ok) else ("Data API (HTTPS)" if self.base.startswith("https") else "Data API")
        return f"SingleStore {where} via {via}"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base,
                auth=(self.user, self.password),
                timeout=httpx.Timeout(60.0, connect=20.0),
                limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---------------- transport ----------------
    async def _data_api(self, path: str, sql: str, args: list[Any] | None, use_db: bool = True) -> dict:
        body: dict[str, Any] = {"sql": sql}
        if args:
            body["args"] = [_jsonable(a) for a in args]
        if use_db and self.database:
            body["database"] = self.database
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                async with self._sem:
                    r = await self._http().post(path, json=body)
            except (httpx.TransportError, httpx.ProxyError) as e:  # transient network trouble
                last_exc = e
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            if r.status_code == 200:
                return r.json()
            text = r.text
            if "Duplicate entry" in text or "1062" in text and "uplicate" in text:
                raise DuplicateKey(text)
            if r.status_code >= 500 and attempt < 3 and "Lock wait timeout" not in text:
                last_exc = DBError(f"{r.status_code}: {text[:300]}")
                await asyncio.sleep(0.5 * (2**attempt))
                continue
            raise DBError(f"{r.status_code}: {text[:500]}")
        raise DBError(f"SingleStore unreachable at {self.base}: {last_exc}")

    def _mysql_call(self, sql: str, args: list[Any] | None, fetch: bool, use_db: bool = True):
        import singlestoredb as s2

        conn = s2.connect(
            host=self.host, port=self.port or 3306, user=self.user, password=self.password,
            database=self.database if use_db else None, connect_timeout=15, autocommit=True,
        )
        try:
            cur = conn.cursor()
            q = sql.replace("?", "%s") if args else sql
            try:
                cur.execute(q, [_jsonable(a) for a in (args or [])] or None)
            except Exception as e:  # noqa: BLE001
                if "Duplicate entry" in str(e):
                    raise DuplicateKey(str(e)) from e
                raise
            if fetch:
                cols = [d[0] for d in cur.description or []]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
            return {"rowsAffected": cur.rowcount}
        finally:
            conn.close()

    async def _use_mysql(self) -> bool:
        if self.transport != "mysql":
            return False
        if self._mysql_ok is None:
            try:
                await asyncio.to_thread(self._mysql_call, "SELECT 1", None, True, False)
                self._mysql_ok = True
            except DuplicateKey:
                self._mysql_ok = True
            except Exception:  # noqa: BLE001 - fall back to the Data API on 443
                self._mysql_ok = False
        return self._mysql_ok

    # ---------------- public API ----------------
    async def execute(self, sql: str, args: list[Any] | None = None, use_db: bool = True) -> dict:
        if await self._use_mysql():
            return await asyncio.to_thread(self._mysql_call, sql, args, False, use_db)
        return await self._data_api("/api/v2/exec", sql, args, use_db)

    async def rows(self, sql: str, args: list[Any] | None = None, use_db: bool = True) -> list[dict]:
        if await self._use_mysql():
            return await asyncio.to_thread(self._mysql_call, sql, args, True, use_db)
        out = await self._data_api("/api/v2/query/rows", sql, args, use_db)
        results = out.get("results") or []
        return results[0].get("rows", []) if results else []

    async def one(self, sql: str, args: list[Any] | None = None) -> dict | None:
        r = await self.rows(sql, args)
        return r[0] if r else None

    async def ping(self) -> float:
        t = time.perf_counter()
        await self.rows("SELECT 1 AS ok", use_db=False)
        return (time.perf_counter() - t) * 1000

    async def init_schema(self) -> list[str]:
        await self.execute(f"CREATE DATABASE IF NOT EXISTS {self.database}", use_db=False)
        sql = re.sub(r"--[^\n]*", "", SCHEMA_PATH.read_text())
        created = []
        for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
            await self.execute(stmt)
            created.append(stmt.split("(")[0].replace("CREATE TABLE IF NOT EXISTS", "").strip())
        return created

    async def reset(self) -> None:
        for t in ["sessions", "events", "money_claims", "lessons", "drills", "versions", "scenarios"]:
            await self.execute(f"DELETE FROM {t}")


_db: SingleStore | None = None


def db() -> SingleStore:
    global _db
    if _db is None:
        _db = SingleStore()
    return _db


def vec(values: list[float]) -> str:
    return json.dumps([round(float(x), 6) for x in values])


def loads(v: Any, default: Any = None) -> Any:
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default
