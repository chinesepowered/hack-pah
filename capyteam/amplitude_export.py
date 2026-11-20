"""Read Amplitude Agent Analytics sessions back for night school.

Needs the project's secret key: either AMPLITUDE_SECRET_KEY, or AMPLITUDE_EXPORT_AUTH=proxy when a
network proxy injects the Basic auth (API key as username, secret key as password) for the export host.

GET https://developer-api.amplitude.com/v1/agent-analytics/export/sessions/{session_id}
returns Amplitude's own signals (task completion, friction, data quality...) with rationales.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("capyteam.amplitude_export")
BASE = "https://developer-api.amplitude.com/v1/agent-analytics/export"


def available() -> bool:
    return bool(settings.amplitude_api_key and (settings.amplitude_secret_key or settings.amplitude_export_auth == "proxy"))


def _auth() -> tuple[str, str]:
    # with AMPLITUDE_EXPORT_AUTH=proxy the password is a placeholder that the proxy replaces with the real secret
    return settings.amplitude_api_key, settings.amplitude_secret_key or "injected-by-proxy"


async def session_signals(session_id: str) -> dict[str, Any] | None:
    if not available():
        return None
    try:
        async with httpx.AsyncClient(timeout=30, auth=_auth()) as c:
            r = await c.get(f"{BASE}/sessions/{session_id}")
        if r.status_code != 200:
            log.info("amplitude export %s -> %s", session_id, r.status_code)
            return None
        data = r.json()
        return {"enrichments": data.get("enrichments"), "evaluations": data.get("evaluations"),
                "turns": data.get("conversation_turn_count")}
    except Exception as e:  # noqa: BLE001
        log.warning("amplitude export failed: %s", e)
        return None


async def list_sessions(start_time: str | None = None, page_size: int = 100) -> list[dict]:
    if not available():
        return []
    params: dict[str, Any] = {"agent_name": "capyteam-bookkeeper", "page_size": page_size}
    if start_time:
        params["start_time"] = start_time
    try:
        async with httpx.AsyncClient(timeout=30, auth=_auth()) as c:
            r = await c.get(f"{BASE}/sessions", params=params)
        return (r.json() or {}).get("data", []) if r.status_code == 200 else []
    except Exception as e:  # noqa: BLE001
        log.warning("amplitude export list failed: %s", e)
        return []
