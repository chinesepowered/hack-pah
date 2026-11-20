"""Register CapyTeam with Firedrill and build its world from firedrill/library.

Steps (all through the Firedrill CLI in JSON mode, using the session-only companion):
  1. descriptor (names + hashes only) -> firedrill register
  2. persona, evaluations, scenarios  -> firedrill library save (refs resolved to exact versions)
  3. synthetic Stripe, QuickBooks, Gmail -> firedrill tools save / runnable / definitions show
  4. world (5 scenarios x 1 repetition) -> firedrill world save
  5. plan review                        -> firedrill plan  (prints drills + credit estimate; nothing runs)

State lands in firedrill/.local/state.json (gitignored: it has machine-specific ids and paths).
usage: python firedrill/setup.py [--skip-library] [--skip-tools]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "firedrill" / "library"
LOCAL = ROOT / "firedrill" / ".local"
STATE = LOCAL / "state.json"
RELEASES = {"stripe": "bd159dd8-c741-5e60-a5b4-2e7319cd6ad5", "quickbooks": "7c176d9c-d71a-51ac-9583-007906bee675",
            "gmail": "8c15083e-60dd-5070-a773-c394d4e47dc4"}
SCENARIOS = ["goodwill-refund", "asked-twice", "stripe-outage", "big-refund", "invoice-once"]
EVAL_FOR = {"goodwill-refund": "refund-goodwill", "asked-twice": "no-double-refund", "stripe-outage": "honest-outage",
            "big-refund": "approval-policy", "invoice-once": "invoice-once"}


def fd(*args: str, stdin: str | None = None) -> list[dict]:
    cmd = ["firedrill", *args, "--session-only", "--json"]
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=180)
    out = [json.loads(l) for l in p.stdout.splitlines() if l.strip().startswith("{")]
    if p.returncode != 0:
        raise SystemExit(f"firedrill {' '.join(args)} failed ({p.returncode}): {p.stderr.strip()[:800]}")
    return out


def last_data(events: list[dict], kind: str | None = None) -> dict:
    for e in reversed(events):
        if e.get("type") != "request_prepared" and (kind is None or e.get("type") == kind):
            return e.get("data") or {}
    return {}


def ref(data: dict, kind: str) -> dict:
    return {"origin": "native_library", "kind": kind, "id": data["id"], "revision": data["revision"], "digest": data["digest"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-library", action="store_true")
    ap.add_argument("--skip-tools", action="store_true")
    a = ap.parse_args()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    reg = json.loads([l for l in (LOCAL / "register.json").read_text().splitlines() if '"native_agent"' in l][0])["data"]
    state["agent_id"] = reg["agent_id"]
    state["descriptor_sha256"] = reg["descriptor"]["descriptor_sha256"]

    if not a.skip_library:
        persona = last_data(fd("library", "save", "--kind", "persona", "--file", str(LIB / "persona.owner.json")))
        state["persona"] = ref(persona, "persona")
        state["evaluations"] = {}
        for e in sorted(set(EVAL_FOR.values())):
            d = last_data(fd("library", "save", "--kind", "evaluation", "--file", str(LIB / f"eval.{e}.json")))
            state["evaluations"][e] = ref(d, "evaluation")
        state["scenarios"] = {}
        for s in SCENARIOS:
            spec = json.loads((LIB / f"scenario.{s}.json").read_text())
            spec["personas"] = [state["persona"]]
            spec["evaluations"] = [state["evaluations"][EVAL_FOR[s]]]
            d = last_data(fd("library", "save", "--kind", "scenario", "--file", "-", stdin=json.dumps(spec)))
            state["scenarios"][s] = ref(d, "scenario")
            print("saved scenario", s, d["id"])

    if not a.skip_tools:
        for svc, rel in RELEASES.items():
            try:
                fd("tools", "save", rel)
            except SystemExit as e:
                if "already" not in str(e).lower():
                    print("tools save:", e)
        runnable = last_data(fd("tools", "runnable"))
        state["tools_runnable_raw"] = runnable
    LOCAL.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))
    print(json.dumps({k: v for k, v in state.items() if k != "tools_runnable_raw"}, indent=1)[:3000])


if __name__ == "__main__":
    main()
