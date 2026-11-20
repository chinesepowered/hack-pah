"""Run one practice day (all scenarios) for an agent version and print the results.

usage: python scripts/run_day.py v1 [--scenarios a,b] [--parallel 3]
"""
import argparse, asyncio, json, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capyteam.db import db
from capyteam.practice import run_day

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", nargs="?", default=None)
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    await db().init_schema()
    out = await run_day(a.version, [s for s in a.scenarios.split(",") if s] or None, run_id=a.run_id, parallel=a.parallel)
    for d in out["drills"]:
        print(f"{d['scenario']:18} {'PASS' if d.get('passed') else 'FAIL'} {d.get('score',0):>3}  {d.get('capy','')} {d.get('version','')} credits={d.get('credits','')}  {d.get('error','')}")
        for r in d.get("results", []):
            if not r["passed"]:
                print(f"      x {r['check']}  {r.get('why','')}")
    print(f"== {out['run_id']}: {out['passed']}/{out['total']} passed")
    Path(".runtime").mkdir(exist_ok=True)
    Path(f".runtime/{out['run_id']}.json").write_text(json.dumps(out, indent=1, default=str))

logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
