"""Live mode: the capybara reads the shop's real systems through Airbyte.

Airbyte's Stripe agent connector (airbyte-agent-sdk) gives the agent typed, read-only
access with Airbyte's recommended flow: inspect the connector -> read its skill docs ->
execute(entity, action, params). Three ways to run it:

  * STRIPE_API_KEY set           -> local connector against your real Stripe account
  * AIRBYTE_CLIENT_ID/SECRET set -> hosted connector from your Airbyte workspace (credentials stay in Airbyte)
  * neither (demo)               -> the same connector pointed at the practice yard's Stripe-compatible API

The live desk then reconciles what Stripe says against what CapyTeam recorded in SingleStore.
"""

from __future__ import annotations

import json
import os
from typing import Any

from .config import settings
from .db import db

READ_ACTIONS = {"list", "get", "search"}


def airbyte_mode() -> str:
    if settings.stripe_api_key:
        return "local-stripe"
    if settings.airbyte_client_id and settings.airbyte_client_secret and os.environ.get("CAPY_AIRBYTE_HOSTED") == "1":
        return "hosted"
    return "yard"


async def stripe_connector(world: str):
    mode = airbyte_mode()
    if mode == "hosted":
        from airbyte_agent_sdk import connect

        return await connect("stripe", client_id=settings.airbyte_client_id, client_secret=settings.airbyte_client_secret)
    from airbyte_agent_sdk.connectors.stripe import StripeAuthConfig, StripeConnector

    conn = StripeConnector(auth_config=StripeAuthConfig(api_key=settings.stripe_api_key or "sk_test_capyteam_yard"))
    if mode == "yard":
        conn._executor.http_client.base_url = f"http://127.0.0.1:{settings.sandbox_port}/stripe-rest/{world}"
    return conn


def _fn(name: str, description: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": props, "required": required}}}


LIVE_TOOLS = [
    _fn("airbyte_stripe_inspect", "Airbyte Stripe agent connector: what this connector is and how it is connected.", {}, []),
    _fn("airbyte_stripe_docs", "Airbyte Stripe agent connector skill docs: the entities (customers, charges, refunds, disputes, payouts, balance...) and the parameters each action accepts. Read before executing.",
        {"section": {"type": "string", "description": "optional entity name to focus on"}}, []),
    _fn("airbyte_stripe", "Run a READ action on Stripe through Airbyte. entity e.g. charges/refunds/disputes/payouts/customers/balance; action list|get|search.",
        {"entity": {"type": "string"}, "action": {"type": "string", "enum": ["list", "get", "search"]},
         "params": {"type": "object", "description": "e.g. {\"limit\": 50} or {\"id\": \"ch_...\"} or {\"created\": {\"gte\": 1700000000}}"}},
        ["entity", "action"]),
    _fn("capyteam_ledger", "What CapyTeam itself did: money actions claimed and completed by capybaras (from SingleStore).",
        {"query": {"type": "string", "description": "optional charge id or customer to filter"}}, []),
]


async def run_live_tool(s: Any, name: str, args: dict) -> tuple[Any, bool, str]:
    if name == "capyteam_ledger":
        like = f"%{args.get('query', '').strip()}%"
        rows = await db().rows(
            "SELECT capy_name, agent_version, action, target, amount_cents, status, created_at FROM money_claims "
            "WHERE status = 'done' AND (target LIKE ? OR claim_key LIKE ?) ORDER BY created_at DESC LIMIT 50", [like, like])
        return {"capyteam_money_actions": rows, "note": "Refunds CapyTeam made itself; anything in Stripe not listed here was done outside CapyTeam."}, True, "archive"
    conn = s.airbyte
    if name == "airbyte_stripe_inspect":
        info = await conn.inspect_connector()
        return {**(info if isinstance(info, dict) else {"info": str(info)}), "capyteam_mode": airbyte_mode()}, True, "harbor"
    if name == "airbyte_stripe_docs":
        docs = await conn.read_skill_docs(args.get("section"))
        text = docs if isinstance(docs, str) else json.dumps(docs, default=str)
        if args.get("section"):
            sec = str(args["section"]).lower()
            blocks = [b for b in text.split("\n  ") if b.lower().startswith(sec)]
            text = ("  " + "\n  ".join(blocks)) if blocks else text
        return {"docs": text[:3000]}, True, "harbor"
    if name == "airbyte_stripe":
        action = str(args.get("action", "list"))
        if action not in READ_ACTIONS:
            return {"blocked": True, "detail": "Live mode is read-only: CapyTeam looks, then asks Maya before touching real money."}, False, "harbor"
        params = args.get("params") or {}
        if action == "list":
            params.setdefault("limit", 50)
        try:
            result = await conn.execute(str(args.get("entity")), action, params)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:400]}, False, "harbor"
        data = getattr(result, "data", result)
        if hasattr(data, "model_dump"):
            data = data.model_dump()
        rows = data if isinstance(data, list) else data
        out = json.loads(json.dumps(rows, default=str))
        if isinstance(out, list):
            out = [{k: v for k, v in (r.items() if isinstance(r, dict) else []) if k in (
                "id", "object", "name", "email", "customer", "charge", "amount", "amount_refunded", "refunded", "currency", "status",
                "reason", "description", "created", "disputed", "arrival_date", "metadata", "available", "pending", "evidence_details")} for r in out]
        if isinstance(out, list):
            summary: dict[str, Any] = {"count": len(out)}
            amounts = [r.get("amount") for r in out if isinstance(r.get("amount"), (int, float))]
            if amounts:
                summary["total_amount_usd"] = round(sum(amounts) / 100, 2)
            refunded = [r.get("amount_refunded") for r in out if isinstance(r.get("amount_refunded"), (int, float))]
            if refunded:
                summary["total_refunded_usd"] = round(sum(refunded) / 100, 2)
            for r in out:
                for k in ("amount", "amount_refunded"):
                    if isinstance(r.get(k), (int, float)):
                        r[k + "_usd"] = r.pop(k) / 100
            return {"entity": args.get("entity"), "action": action, "summary": summary, "newest": out[:12],
                    "note": "amounts in dollars; 'newest' shows up to 12 rows, summary covers all rows"}, True, "harbor"
        return {"entity": args.get("entity"), "action": action, "data": out}, True, "harbor"
    return {"error": f"unknown live tool {name}"}, False, "harbor"
