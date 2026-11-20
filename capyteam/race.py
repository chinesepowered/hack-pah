"""The exactly-once race: N capybaras pick up the same customer email at the same moment.

Without a shared claim, several of them refund and book the same thing. With the
`exactly_once` policy, every money action is first INSERTed into SingleStore's
money_claims table under one primary key; SingleStore admits exactly one winner and the
rest are told who already handled it.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from . import sandbox
from .agent import SESSIONS, open_session

CREW = ["Pip", "Mochi", "Biscuit", "Clover", "Hazel", "Nori", "Taro", "Pudding", "Toffee", "Juniper", "Olive", "Peanut"]
from .analytics import analytics
from .db import db, now
from .practice import _bookings, _emailed, _refunds, yard_urls

RACE_MESSAGE = ("A new email from Jess Park about a cracked mug just landed in the shared studio inbox. "
                "Please handle it right away: refund what she's owed and keep the books right.")


async def run_race(version: str | None, n: int = 10, *, run_id: str | None = None) -> dict:
    run_id = run_id or f"race-{version or 'auto'}-{uuid.uuid4().hex[:6]}"
    world = run_id
    sandbox.reset_world(world, "race")
    urls = yard_urls(world)
    sessions = [await open_session(f"{run_id}-{i:02d}", mode="race", source="sandbox", world_id=world, invoke_urls=urls,
                                   scenario="race", version=version, campaign_id=run_id, capy=CREW[i % len(CREW)]) for i in range(n)]
    t0 = time.time()
    replies = await asyncio.gather(*(s.respond(RACE_MESSAGE) for s in sessions), return_exceptions=True)
    elapsed = round(time.time() - t0, 1)
    st = sandbox.snapshot(world)
    refunds = _refunds(st, "ch_4821")
    bookings = _bookings(st, "58")
    emails = _emailed(st, "jess.park@example.com")
    by_capy = []
    for s, r in zip(sessions, replies):
        by_capy.append({"capy": s.capy, "session": s.id, "version": s.version, "refunded": len(s.done["refund"]), "booked": len(s.done["booking"]),
                        "emailed": len(s.done["email"]), "blocked_duplicates": s.blocked_dupes,
                        "reply": (r if isinstance(r, str) else f"error: {r}")[:240]})
    claims = await db().rows("SELECT capy_name, action, target, amount_cents, status FROM money_claims WHERE claim_key LIKE ? ORDER BY created_at", [f"{world}|%"])
    results = [
        {"check": "Stripe: exactly one $38 refund on Jess's charge across all capybaras", "passed": refunds == [3800], "kind": "exact",
         "observed": f"{len(refunds)} refund(s): {[r / 100 for r in refunds]}"},
        {"check": "QuickBooks: the refund is booked exactly once", "passed": bookings == [38.0], "kind": "exact",
         "observed": f"{len(bookings)} booking(s)"},
        {"check": "Gmail: Jess got at most one confirmation", "passed": emails <= 1, "kind": "exact", "observed": f"{emails} email(s)"},
    ]
    passed = all(r["passed"] for r in results)
    doubles = [c for c in by_capy if c["refunded"] or c["booked"]]
    verdict = {"passed": passed, "score": round(100 * sum(r["passed"] for r in results) / len(results)), "results": results,
               "policy": "One customer request = one refund and one booking, no matter how many capybaras see it.",
               "race": {"capybaras": n, "seconds": elapsed, "refunds": len(refunds), "bookings": len(bookings), "emails": emails,
                        "claims": claims, "actors": doubles, "by_capy": by_capy}}
    lead = (doubles[1] if len(doubles) > 1 else (doubles[0] if doubles else by_capy[0]))["session"]
    await db().execute(
        "INSERT INTO drills (drill_id, campaign_id, session_id, scenario, agent_version, variant, source, ending, passed, score, results, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [f"drill-{run_id}", run_id, lead, "race", sessions[0].version, sessions[0].variant, "practice", "inputs_exhausted", int(passed),
         verdict["score"], verdict, now()],
    )
    for s in sessions:
        await db().execute("UPDATE sessions SET verdict = ? WHERE session_id = ?", [{"race": run_id, "passed": passed}, s.id])
        analytics.score(s, "race-exactly-once", 1.0 if passed else 0.0, source="ai", comment=f"{len(refunds)} refunds, {len(bookings)} bookings across {n} capybaras")
        s.note_event("verdict", "school", f"Race: {len(refunds)} refund(s), {len(bookings)} booking(s) across {n} capybaras -> {'PASS' if passed else 'FAIL'}", {})
        await s.end(status="done" if passed else "failed")
        SESSIONS.pop(s.id, None)
    analytics.flush()
    return {"run_id": run_id, "version": sessions[0].version, "passed": passed, "seconds": elapsed, "refunds": len(refunds),
            "refund_amounts": [r / 100 for r in refunds], "bookings": len(bookings), "emails": emails, "claims": len(claims),
            "blocked_duplicates": sum(c["blocked_duplicates"] for c in by_capy), "by_capy": by_capy}
