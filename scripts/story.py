"""The CapyTeam story, end to end, against the real services.

  Day 1      v1 works seven practice chores                         (SIE + yard + SingleStore + Amplitude)
  Night 1    night school turns v1's failed shifts into v2          (coach on SIE, lessons in SingleStore)
  Day 2      v2 works the same seven chores
  Open hours real-shaped shifts; Statsig assigns v1 or v2 per shift  (experiment variant on every Amplitude event)
  Ship v2
  Race       ten capybaras grab the same customer email on v2       (concurrency: does money move once?)
  Night 2    night school learns from the race -> v3
  Race       the same ten capybaras on v3
  Day 3      v3 regression on the seven chores, then ship v3

usage: python scripts/story.py [--from STEP] [--reset]
"""
import argparse
import asyncio
import json
import logging
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capyteam import memory  # noqa: E402
from capyteam.analytics import analytics  # noqa: E402
from capyteam.coach import night_school  # noqa: E402
from capyteam.db import db  # noqa: E402
from capyteam.practice import DAY_ORDER, run_day, run_drill  # noqa: E402
from capyteam.race import run_race  # noqa: E402

OUT = Path(".runtime/story.json")
STEPS = ["day1", "night1", "day2", "open", "ship2", "race2", "night2", "race3", "day3", "ship3"]


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def brief(day: dict) -> dict:
    return {"run_id": day["run_id"], "passed": day["passed"], "total": day["total"],
            "drills": [{k: d.get(k) for k in ("scenario", "capy", "version", "passed", "score", "credits", "cost_usd")} | {
                "failed_checks": [r["check"] for r in d.get("results", []) if not r["passed"]]} for d in day["drills"]]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="day1", choices=STEPS)
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    story = json.loads(OUT.read_text()) if OUT.exists() and a.start != "day1" else {}
    log(f"database: {db().label}")
    await db().init_schema()
    if a.reset:
        await db().reset()
        log("reset all CapyTeam tables")
    await memory.ensure_v1()
    from capyteam.sie import sie
    log(f"warming SIE task models: {await sie.warmup()}")

    for step in STEPS[STEPS.index(a.start):]:
        log(f"=== {step}")
        if step == "day1":
            story["day1"] = brief(await run_day("v1", run_id="day1", parallel=3))
        elif step == "night1":
            story["night1"] = await night_school("v1", new_version="v2", run_id="day1")
        elif step == "day2":
            story["day2"] = brief(await run_day("v2", run_id="day2", parallel=3))
        elif step == "open":
            random.seed(7)
            picks = [random.choice(DAY_ORDER) for _ in range(8)]
            rows = []
            for i, sc in enumerate(picks):
                r = await run_drill(sc, version=None, run_id=f"open-{i:02d}")
                sess = await db().one("SELECT variant FROM sessions WHERE session_id = ?", [r["session"]])
                rows.append({"scenario": sc, "version": r["version"], "variant": (sess or {}).get("variant"), "passed": r["passed"]})
                log(f"  open shift {i}: {sc} -> {r['version']} ({rows[-1]['variant']}) {'PASS' if r['passed'] else 'FAIL'}")
            story["open"] = rows
        elif step == "ship2":
            await memory.set_version_status("v2", "shipped")
        elif step == "race2":
            r = await run_race("v2", 10, run_id="race-v2")
            story["race2"] = {k: v for k, v in r.items() if k != "by_capy"}
        elif step == "night2":
            story["night2"] = await night_school("v2", new_version="v3", run_id="race-v2")
        elif step == "race3":
            r = await run_race("v3", 10, run_id="race-v3")
            story["race3"] = {k: v for k, v in r.items() if k != "by_capy"}
        elif step == "day3":
            story["day3"] = brief(await run_day("v3", run_id="day3", parallel=3))
        elif step == "ship3":
            await memory.set_version_status("v3", "shipped")
        analytics.flush()
        OUT.write_text(json.dumps(story, indent=1, default=str))
        summary = story.get(step)
        if isinstance(summary, dict):
            log(json.dumps({k: v for k, v in summary.items() if k in ("passed", "total", "refunds", "bookings", "emails", "to", "policy", "blocked_duplicates")}, default=str))
    log("story complete")


logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
