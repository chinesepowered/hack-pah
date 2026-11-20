"""Run the exactly-once race. usage: python scripts/race.py v2 [--n 10]"""
import argparse, asyncio, json, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capyteam.race import run_race

async def main():
    ap = argparse.ArgumentParser(); ap.add_argument("version", nargs="?", default=None); ap.add_argument("--n", type=int, default=10); ap.add_argument("--run-id")
    a = ap.parse_args()
    out = await run_race(a.version, a.n, run_id=a.run_id)
    print(json.dumps({k: v for k, v in out.items() if k != "by_capy"}, indent=1))
    for c in out["by_capy"]:
        print(f"  {c['capy']:<12} refunded={c['refunded']} booked={c['booked']} emailed={c['emailed']} blocked={c['blocked_duplicates']} | {c['reply'][:110]}")
    Path(f".runtime/{out['run_id']}.json").write_text(json.dumps(out, indent=1, default=str))

logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
