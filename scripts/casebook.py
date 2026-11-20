"""Fill CapyTeam's Cognee casebook from SingleStore and ask it questions.

  python scripts/casebook.py backfill   # remember night-school case files + shift summaries (cognify)
  python scripts/casebook.py ask "What went wrong when Stripe was down?"
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capyteam import cognee_memory  # noqa: E402
from capyteam.db import db, loads  # noqa: E402

QUESTIONS = [
    "What went wrong when Stripe was unavailable, and what rule did the team learn?",
    "Which mistakes involved refunds over $200, and how does CapyTeam handle them now?",
    "What happened when ten capybaras handled the same refund email for Jess Park?",
    "What does the team know about Jess Park?",
]


async def case_files() -> list[str]:
    lessons = await db().rows("SELECT lesson_id, title, rule, failure, introduced_in, source_session, guard FROM lessons ORDER BY created_at")
    texts = []
    for l in lessons:
        d = await db().one("SELECT scenario, agent_version, results FROM drills WHERE session_id = ?", [l["source_session"]])
        res = loads((d or {}).get("results"), {}) or {}
        failed = [r["check"] for r in res.get("results", []) if not r.get("passed")]
        guard = loads(l.get("guard"), {}) or {}
        race = res.get("race")
        extra = (f" In the race {race['capybaras']} capybaras produced {race['refunds']} Stripe refunds, {race['bookings']} QuickBooks bookings and "
                 f"{race['emails']} emails for one customer request.") if race else ""
        texts.append(
            f"CapyTeam night-school case file '{l['failure']}'. Scenario {(d or {}).get('scenario')} on agent version {(d or {}).get('agent_version')} "
            f"failed these checks: {'; '.join(failed)}.{extra} Lesson learned ({l['lesson_id']}): {l['title']}: {l['rule']} "
            f"Harness policies switched on: {', '.join(guard.get('guards') or []) or 'none'}. Introduced in version {l['introduced_in']}.")
    return texts


async def shift_summaries() -> list[str]:
    rows = await db().rows(
        "SELECT session_id, capy_name, agent_version, scenario, mode, outcome, verdict FROM sessions "
        "WHERE mode IN ('practice','race','live') AND status <> 'running' ORDER BY started_at")
    texts = []
    for r in rows:
        out = loads(r.get("outcome"), {}) or {}
        v = loads(r.get("verdict"), {}) or {}
        done = out.get("done") or {}
        bits = []
        for x in done.get("refund", []):
            bits.append(f"refunded ${x['amount'] / 100:.2f} on charge {x.get('charge')}")
        for x in done.get("booking", []):
            bits.append(f"booked a ${x['amount'] / 100:.2f} refund receipt for QuickBooks customer {x.get('customer')}")
        for x in done.get("invoice", []):
            bits.append(f"created a ${x['amount'] / 100:.2f} invoice")
        for x in done.get("payment", []):
            bits.append(f"recorded a ${x['amount'] / 100:.2f} payment on invoice {x.get('invoice')}")
        if out.get("blocked_duplicates"):
            bits.append(f"refused {out['blocked_duplicates']} duplicate money actions already claimed by teammates")
        if out.get("failed_money"):
            bits.append("hit a failed payment call and booked nothing for it")
        verdict = "passed" if v.get("passed") else ("failed" if v.get("passed") is False else "finished")
        texts.append(f"Shift {r['session_id']}: capybara {r['capy_name']} (agent {r['agent_version']}, {r['mode']}, scenario {r['scenario']}) {verdict}. "
                     f"Actions: {', '.join(bits) or 'no money moved'}. Reply to Maya: {str(out.get('last_reply', ''))[:300]}")
    return texts


async def wait_ready(timeout: float = 900) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        res = await cognee_memory.recall("What failures has CapyTeam had?", top_k=3)
        txt = json.dumps(res, default=str)
        if "warming_up" not in txt and "error" not in txt[:40]:
            return txt[:400]
        await asyncio.sleep(20)
    return "timed out waiting for cognify"


async def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "backfill"
    if cmd == "backfill":
        cases = await case_files()
        shifts = await shift_summaries()
        print(f"remembering {len(cases)} case files + {len(shifts)} shift summaries into Cognee dataset '{cognee_memory.DATASET}'")
        r1 = await cognee_memory.remember(cases, node_set=["night_school"], background=True)
        print("case files ->", json.dumps(r1, default=str)[:300])
        for i in range(0, len(shifts), 20):
            r2 = await cognee_memory.remember(shifts[i:i + 20], node_set=["shifts"], background=True)
            print("shifts batch ->", json.dumps(r2, default=str)[:200])
        print("waiting for Cognee to cognify ...", await wait_ready())
        cmd = "ask"
    if cmd == "ask":
        qs = sys.argv[2:] or QUESTIONS
        answers = []
        for q in qs:
            res = await cognee_memory.recall(q, top_k=8)
            ans = cognee_memory.answer_text(res, 1500)
            answers.append({"q": q, "a": ans})
            print(f"\nQ: {q}\nA: {ans}")
        Path(".runtime/casebook.json").write_text(json.dumps(answers, indent=1))


asyncio.run(main())
