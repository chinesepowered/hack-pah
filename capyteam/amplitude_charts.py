"""Read CapyTeam's agent analytics back from Amplitude (Dashboard REST API, event segmentation).

The same numbers Amplitude's own charts show: drill pass rate by agent version, sessions by experiment
group, event volumes. Needs AMPLITUDE_API_KEY + AMPLITUDE_SECRET_KEY. Results are cached for five minutes.

Amplitude keeps every session we ever sent (including earlier test runs), so its totals can be larger
than the SingleStore tables, which hold the final story run.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("capyteam.amplitude_charts")
URL = "https://amplitude.com/api/2/events/segmentation"
TTL = 300
_cache: dict[str, Any] = {"at": 0.0, "data": None}
_lock = asyncio.Lock()


def available() -> bool:
    return bool(settings.amplitude_api_key and settings.amplitude_secret_key)


def _f(key: str, values: list[str]) -> dict:
    return {"subprop_type": "event", "subprop_key": key, "subprop_op": "is", "subprop_value": values}


async def _totals(c: httpx.AsyncClient, event: str, group: str | None, filters: list[dict], start: str, end: str) -> dict[str, int]:
    e = {"event_type": event, "filters": filters, "group_by": [{"type": "event", "value": group}] if group else []}
    r = await c.get(URL, params={"e": json.dumps(e), "m": "totals", "start": start, "end": end})
    r.raise_for_status()
    d = r.json()["data"]
    labels = [x[1] if isinstance(x, list) and len(x) > 1 else x for x in d.get("seriesLabels", [])] or ["all"]
    sums = [sum(v.get("value", 0) if isinstance(v, dict) else v for v in row) for row in d.get("series", [])]
    return {str(k): int(v) for k, v in zip(labels, sums)}


async def snapshot(force: bool = False) -> dict[str, Any]:
    """Pass rates by version, experiment arms and volumes, as Amplitude reports them."""
    if not available():
        return {"available": False}
    async with _lock:
        if _cache["data"] is not None and not force and time.time() - _cache["at"] < TTL:
            return _cache["data"]
        today = dt.datetime.now(dt.timezone.utc).date()
        start, end = (today - dt.timedelta(days=29)).strftime("%Y%m%d"), (today + dt.timedelta(days=1)).strftime("%Y%m%d")
        ver, var = "[Agent] Agent Version", "[Agent] Experiment Variant"
        drill = _f("[Agent] Score Name", ["drill-pass"])
        won = _f("[Agent] Score Value", ["1", "1.0"])
        statsig = _f("[Agent] Experiment Provider", ["statsig"])
        try:
            async with httpx.AsyncClient(timeout=60, auth=(settings.amplitude_api_key, settings.amplitude_secret_key)) as c:
                q = [  # sequential on purpose: the Dashboard REST API limits concurrent queries
                    ("scored", "[Agent] Score", ver, [drill]), ("passed", "[Agent] Score", ver, [drill, won]),
                    ("sessions", "[Agent] Session End", ver, []), ("tools", "[Agent] Tool Call", ver, []),
                    ("ai", "[Agent] AI Response", ver, []),
                    ("x_sessions", "[Agent] Session End", var, [statsig]),
                    ("x_scored", "[Agent] Score", var, [drill, statsig]), ("x_passed", "[Agent] Score", var, [drill, statsig, won]),
                ]
                out: dict[str, dict[str, int]] = {}
                for name, event, group, filters in q:
                    out[name] = await _totals(c, event, group, filters, start, end)
        except Exception as e:  # noqa: BLE001 - the UI works without this card
            log.warning("amplitude read failed: %s", e)
            return {"available": False, "error": str(e)[:200]}
        versions = sorted(v for v in out["scored"] if re.fullmatch(r"v\d+", v))
        data = {
            "available": True, "window": {"start": start, "end": end},
            "by_version": {v: {"passed": out["passed"].get(v, 0), "scored": out["scored"].get(v, 0), "sessions": out["sessions"].get(v, 0),
                               "tool_calls": out["tools"].get(v, 0), "ai_responses": out["ai"].get(v, 0)} for v in versions},
            "experiment": {g: {"sessions": n, "passed": out["x_passed"].get(g, 0), "scored": out["x_scored"].get(g, 0)}
                           for g, n in sorted(out["x_sessions"].items())},
            "totals": {"sessions": sum(out["sessions"].get(v, 0) for v in versions), "tool_calls": sum(out["tools"].get(v, 0) for v in versions),
                       "ai_responses": sum(out["ai"].get(v, 0) for v in versions)},
        }
        _cache.update(at=time.time(), data=data)
        return data
