"""Night school: failed shifts of a version -> lessons + policies + new Firedrill scenarios -> candidate version.

usage: python scripts/night_school.py v1 [--run-id day1-v1] [--to v2]
"""
import argparse, asyncio, json, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capyteam.coach import night_school

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="v1")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--to", default=None)
    a = ap.parse_args()
    out = await night_school(a.base, new_version=a.to, run_id=a.run_id)
    print(json.dumps({k: v for k, v in out.items() if k != "lessons"}, indent=1))
    for l in out["lessons"]:
        print(f"\n[{l['scenario']}] {l['failure']}  ({'reused' if l['reused'] else 'new'} {l['lesson_id']})")
        print("  diagnosis:", l["diagnosis"])
        print("  lesson:   ", l["lesson"])
        print("  guards:   ", l["guards"], "->", l["new_drill"])
    Path(f".runtime/night-{a.base}.json").write_text(json.dumps(out, indent=1, default=str))

logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
