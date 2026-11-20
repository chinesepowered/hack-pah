"""Fill README.md's {{placeholders}} from live SingleStore data (via the CapyTeam API on :8787)."""
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787"
c = httpx.Client(base_url=base, timeout=60)
o = c.get("/api/overview").json()
drills = c.get("/api/drills?limit=500").json()


def day(v: str) -> str:
    latest = {}
    for d in drills:
        if d["agent_version"] == v and d["source"] == "practice" and d["scenario"] != "race" and str(d["campaign_id"]).startswith("day"):
            if d["scenario"] not in latest or latest[d["scenario"]]["created_at"] < d["created_at"]:
                latest[d["scenario"]] = d
    return f"{sum(int(x['passed']) for x in latest.values())}/{len(latest)}" if latest else "n/a"


race = {d["agent_version"]: d["results"]["race"] for d in drills if d["scenario"] == "race"}
cost = {r["version"]: r for r in o.get("costs", [])}
money = lambda v: f"${float(cost[v]['avg_cost_usd']):.3f}" if v in cost and cost[v].get("avg_cost_usd") is not None else "n/a"
fdt = [d for d in drills if d["source"] == "firedrill-tools"]
fdc = [d for d in drills if d["source"] == "firedrill"]
r3 = race.get("v3", {})
blocked3 = sum(x.get("blocked_duplicates", 0) for x in r3.get("by_capy", []))

if fdt:
    by_v = {}
    for d in fdt:
        by_v.setdefault(d["agent_version"], []).append(d)
    parts = [f"{v}: {sum(int(x['passed']) for x in xs)}/{len(xs)} passed" for v, xs in sorted(by_v.items())]
    fd_tools = ("With Firedrill's simulated-user pool full (`native_participant_capacity_exceeded`), we ran CapyTeam's drills against a Firedrill "
                "**tool session**: Firedrill's own synthetic Stripe, QuickBooks and Gmail, reached through `firedrill tools access`, with every "
                "pass/fail decided by counts read back from those services. Results: " + "; ".join(parts) + ".")
else:
    fd_tools = ("Everything is registered in our Firedrill workspace: agent, persona, evaluations, scenarios, the world and a reviewed plan. "
                "Plan reviews returned `native_participant_capacity_exceeded` during the hackathon (Firedrill's simulated-user capacity), "
                "so campaigns run with `python firedrill/run.py go --version v3 --approve` once capacity is available.")
fd_note = ("Full Firedrill campaigns (simulated owners + rubric scoring) were blocked by `native_participant_capacity_exceeded` while we built this; "
           + ("the Firedrill results above come from a Firedrill tool session (synthetic services, scripted owner turns, exact checks)."
              if fdt else "practice-yard drills mirror the Firedrill scenarios one to one."))
if fdc:
    fd_note = f"Firedrill campaign verdicts imported: {sum(int(d['passed']) for d in fdc)}/{len(fdc)} drills passed."
starts = [e for e in c.get("/api/events?run=open-&limit=200").json() if e.get("kind") == "start"]
statsig_note = ("Open-hours shifts got their version from the Statsig experiment `capyteam_agent_release`."
                if any("via statsig" in e.get("summary", "") for e in starts) else "")
# provider label lives in Amplitude ([Agent] Experiment Provider); the session table keeps the group name
vals = {
    "v1_day": day("v1"), "v2_day": day("v2"), "v3_day": day("v3"),
    "r2_refunds": str(race.get("v2", {}).get("refunds", "n/a")), "r2_emails": str(race.get("v2", {}).get("emails", "n/a")),
    "r3_refunds": str(r3.get("refunds", "n/a")), "r3_blocked": str(blocked3),
    "c1": money("v1"), "c2": money("v2"), "c3": money("v3") if "v3" in cost else money("v2"),
    "events": f"{o.get('events', 0):,}", "lessons": str(o.get("lessons", 0)),
    "fd_tools": fd_tools, "fd_note": fd_note,
    "statsig_note": statsig_note or "Statsig: until the `capyteam_agent_release` experiment exists in the Statsig project, CapyTeam splits shifts with a deterministic hash and labels the provider `capyteam-hash` in Amplitude, so no data is mislabeled as Statsig's.",
}
cb = json.loads((ROOT / ".runtime" / "casebook.json").read_text()) if (ROOT / ".runtime" / "casebook.json").exists() else []
vals["cognee_qa"] = "\n".join(f"> **Q:** {x['q']}\n> **Cognee:** {' '.join(str(x['a']).split())[:420]}\n>" for x in cb[:4]).rstrip(">\n") or "_(run `python scripts/casebook.py backfill`)_"
p = ROOT / "README.md"
text = p.read_text()
for k, v in vals.items():
    text = text.replace("{{" + k + "}}", v)
left = re.findall(r"\{\{(\w+)\}\}", text)
p.write_text(text)
print(json.dumps(vals, indent=1)[:2000])
print("unfilled:", left)
