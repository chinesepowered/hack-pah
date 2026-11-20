"""Run a release as a Statsig experiment: Statsig assigns each shift to the shipped version (Control)
or night school's candidate (Test), and every shift reports its outcome back to Statsig and Amplitude.

  python scripts/experiment.py                # v1 (shipped) vs v2 (candidate), 2 rounds of the seven chores
  python scripts/experiment.py --shipped v2 --candidate v3 --rounds 1

Results land in SingleStore (sessions/drills with campaign `exp-*`), Amplitude ([Agent] Experiment Variant /
Provider on every event) and Statsig (exposures + capyteam_shift_done / capyteam_shift_failed).
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capyteam.sie import sie  # noqa: E402
from capyteam.analytics import analytics  # noqa: E402
from capyteam.flags import flags  # noqa: E402
from capyteam.practice import DAY_ORDER, run_drill  # noqa: E402

OUT = Path(".runtime/experiment.json")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shipped", default="v1")
    ap.add_argument("--candidate", default="v2")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--prefix", default="exp")
    a = ap.parse_args()
    release = (a.shipped, a.candidate)
    print("warming SIE task models:", await sie.warmup(), flush=True)
    sem = asyncio.Semaphore(a.parallel)
    jobs = [(f"{a.prefix}-{r * len(DAY_ORDER) + i:02d}", name) for r in range(a.rounds) for i, name in enumerate(DAY_ORDER)]

    async def one(run_id: str, name: str) -> dict:
        async with sem:
            try:
                r = await run_drill(name, version=None, run_id=run_id, release=release)
            except Exception as e:  # noqa: BLE001
                print(f"  {run_id}-{name}: error {str(e)[:200]}", flush=True)
                return {"scenario": name, "session": f"{run_id}-{name}", "error": str(e)[:300], "passed": False}
            print(f"  {r['session']}: {r['variant']} via {r['provider']} -> {r['version']} {'PASS' if r['passed'] else 'FAIL'}", flush=True)
            return {k: r[k] for k in ("scenario", "session", "version", "variant", "provider", "passed", "score", "cost_usd")}

    t0 = time.time()
    rows = await asyncio.gather(*(one(run_id, name) for run_id, name in jobs))
    groups: dict[str, dict] = {}
    for r in rows:
        if "error" in r:
            continue
        g = groups.setdefault(r["variant"], {"version": r["version"], "shifts": 0, "done": 0, "providers": set()})
        g["shifts"] += 1
        g["done"] += int(r["passed"])
        g["providers"].add(r["provider"])
    summary = {"release": {"shipped": a.shipped, "candidate": a.candidate}, "seconds": round(time.time() - t0),
               "groups": {k: {**v, "providers": sorted(v["providers"])} for k, v in groups.items()}, "shifts": rows}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "shifts"}, indent=1))
    analytics.flush()
    flags.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
