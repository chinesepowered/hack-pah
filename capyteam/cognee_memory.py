"""Cognee: CapyTeam's casebook, an open-source knowledge-graph memory shared across shifts.

SingleStore holds the operational truth (sessions, events, claims, lesson vectors). Cognee holds
what the team has *learned about the world*: every closed shift and every night-school case file is
remembered into a knowledge graph (customers -> orders -> incidents -> lessons), and recalled later:
  * night school recalls related past incidents before writing a lesson, so lessons generalize;
  * the live desk asks the casebook what the team already knows about a customer.

API: POST /api/v1/remember (add + cognify), POST /api/v1/recall (graph-aware search), X-Api-Key auth.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("capyteam.cognee")

DATASET = os.environ.get("COGNEE_DATASET", "capyteam_casebook")


def base_url() -> str:
    return os.environ.get("COGNEE_BASE_URL", "").rstrip("/")


def enabled() -> bool:
    return bool(base_url()) and os.environ.get("CAPY_COGNEE", "1") != "0"


def _headers() -> dict[str, str]:
    # In the cloud sandbox the egress proxy injects the real X-Api-Key; elsewhere set COGNEE_API_KEY.
    return {"X-Api-Key": os.environ.get("COGNEE_API_KEY") or "injected-by-proxy", "Accept": "application/json"}


async def remember(texts: list[str], *, dataset: str = DATASET, node_set: list[str] | None = None, background: bool = True) -> dict:
    if not enabled() or not texts:
        return {"skipped": True}
    files = [("raw_data", (None, t)) for t in texts]
    form: list[tuple[str, Any]] = files + [("datasetName", (None, dataset)), ("run_in_background", (None, "true" if background else "false")),
                                           ("self_improvement", (None, "false"))]
    for n in node_set or []:
        form.append(("node_set", (None, n)))
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=20.0), follow_redirects=True) as c:
        r = await c.post(f"{base_url()}/api/v1/remember", headers=_headers(), files=form)
    if r.status_code >= 400:
        log.warning("cognee remember %s: %s", r.status_code, r.text[:300])
        return {"error": r.status_code, "detail": r.text[:300]}
    try:
        return r.json()
    except ValueError:
        return {"ok": True}


async def recall(query: str, *, dataset: str = DATASET, top_k: int = 8, search_type: str | None = None) -> Any:
    if not enabled():
        return None
    body: dict[str, Any] = {"query": query, "datasets": [dataset], "top_k": top_k}
    if search_type:
        body["search_type"] = search_type
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=20.0), follow_redirects=True) as c:
        r = await c.post(f"{base_url()}/api/v1/recall", headers={**_headers(), "Content-Type": "application/json"}, json=body)
    if r.status_code >= 400:
        log.warning("cognee recall %s: %s", r.status_code, r.text[:300])
        return {"error": r.status_code, "detail": r.text[:300]}
    try:
        return r.json()
    except ValueError:
        return r.text


def answer_text(result: Any, limit: int = 1500) -> str:
    """Flatten a recall result into text a small model can read."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result[:limit]
    if isinstance(result, dict):
        for k in ("answer", "result", "results", "search_result", "data"):
            if k in result:
                return answer_text(result[k], limit)
        return json.dumps(result, default=str)[:limit]
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict):
                parts.append(str(item.get("search_result") or item.get("text") or item.get("answer") or item.get("content") or json.dumps(item, default=str)))
            else:
                parts.append(str(item))
        return "\n".join(parts)[:limit]
    return str(result)[:limit]


def shift_case(s: Any) -> str:
    """One closed shift as a plain-language case note for the casebook."""
    done = s.done
    lines = [f"CapyTeam shift {s.id}: capybara {s.capy} on agent version {s.version} ({s.mode}, scenario {s.scenario or 'ad hoc'})."]
    for r in done.get("refund", []):
        lines.append(f"Refunded ${r['amount'] / 100:.2f} on Stripe charge {r.get('charge')} (refund {r.get('id')}).")
    for b in done.get("booking", []):
        lines.append(f"Booked a ${b['amount'] / 100:.2f} refund receipt in QuickBooks for customer {b.get('customer')}.")
    for i in done.get("invoice", []):
        lines.append(f"Created QuickBooks invoice {i.get('id')} for ${i['amount'] / 100:.2f}.")
    for p in done.get("payment", []):
        lines.append(f"Recorded a ${p['amount'] / 100:.2f} payment against invoice {p.get('invoice')}.")
    if s.failed_money:
        lines.append("A payment-system call failed during this shift; nothing was booked for it.")
    if s.blocked_dupes:
        lines.append(f"{s.blocked_dupes} duplicate money actions were refused because another capybara had already claimed them.")
    if s.pending_approval and not s.approved:
        lines.append(f"Waiting for the owner's approval on a ${s.pending_approval.get('amount_usd')} refund.")
    if s.replies:
        lines.append(f"Final reply to the owner: {s.replies[-1][:400]}")
    return " ".join(lines)


_pending: list[str] = []
_lock = asyncio.Lock()


async def queue_shift(s: Any, flush_at: int = 8) -> None:
    """Batch closed shifts into the casebook (one remember call per batch)."""
    if not enabled():
        return
    async with _lock:
        _pending.append(shift_case(s))
        batch = list(_pending) if len(_pending) >= flush_at else []
        if batch:
            _pending.clear()
    if batch:
        await remember(batch, node_set=["shifts"])


async def flush() -> None:
    async with _lock:
        batch = list(_pending)
        _pending.clear()
    if batch:
        await remember(batch, node_set=["shifts"])
