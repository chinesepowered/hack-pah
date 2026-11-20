"""Run a Firedrill campaign for one CapyTeam agent version and import the verdicts.

  python firedrill/run.py plan                      # plan review: drills, gates, credit estimate (nothing runs)
  python firedrill/run.py go --version v1 --approve # apply the reviewed plan, run drills locally, import report
  python firedrill/run.py import --campaign <id> --version v1

`--approve` records that a person approved this campaign's credit estimate and local commands,
as Firedrill's agent mode requires. Verdicts land in SingleStore (drills, sessions.verdict)
and in Amplitude as [Agent] Score events on the drill's agent session.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
LOCAL = ROOT / "firedrill" / ".local"
STATE = LOCAL / "state.json"


def fd(*args: str, timeout: int = 3600, check: bool = True) -> list[dict]:
    p = subprocess.run(["firedrill", *args, "--session-only", "--json"], capture_output=True, text=True, timeout=timeout)
    events = [json.loads(l) for l in p.stdout.splitlines() if l.strip().startswith("{")]
    if check and p.returncode != 0:
        raise SystemExit(f"firedrill {' '.join(args)} -> {p.returncode}\n{p.stderr.strip()[:1500]}")
    return events


def data_of(events: list[dict], kind: str | None = None) -> dict:
    for e in reversed(events):
        if e.get("type") != "request_prepared" and (kind is None or e.get("type") == kind):
            return e.get("data") or {}
    return {}


def write_plan(version: str) -> Path:
    st = json.loads(STATE.read_text())
    desc = json.loads((LOCAL / "descriptor.json").read_text())
    plan = {
        "version": 1,
        "descriptor_sha256": st["descriptor_sha256"],
        "roots": [{"alias": "app", "path": str(ROOT), "identity_sha256": desc["source_roots"][0]["identity_sha256"]}],
        "services": [{
            "alias": "agent", "root_alias": "app", "mode": "launch",
            "command": {"executable": str(ROOT / ".venv" / "bin" / "python"), "args": ["-m", "capyteam.server"]},
            "cwd": ".",
            "env_passthrough": [],
            "env_static": {"CAPY_MODE": "drill", "CAPY_AGENT_VERSION": version,
                           "CAPY_BUSINESS": "Lumen Trail Supply Co. (a small outdoor-gear shop)", "CAPY_OWNER": "the owner"},
            "local_secret_env": ["SIE_API_KEY", "SINGLESTORE_URL", "AMPLITUDE_API_KEY", "STATSIG_SERVER_SECRET"],
            "readiness": {"kind": "http", "url": "http://127.0.0.1:0/health", "expect_status": [200]},
            "readiness_timeout_ms": 90000,
            "stop_timeout_ms": 20000,
            "per_drill": True,
            "port_env": "PORT",
            "dependency_env": [{"alias": "stripe", "name": "STRIPE_INVOKE_URL", "url": "invoke"},
                               {"alias": "quickbooks", "name": "QUICKBOOKS_INVOKE_URL", "url": "invoke"},
                               {"alias": "gmail", "name": "GMAIL_INVOKE_URL", "url": "invoke"}],
        }],
        "driver": {"profile": "http.v1", "service_alias": "agent", "path": "/chat", "method": "POST", "stream": "none",
                   "session_header": None, "request_template": "message-text", "response_pointer": "/reply"},
        "state_hooks": [],
        "max_parallel_drills": 1,
    }
    path = LOCAL / f"plan.{version}.json"
    path.write_text(json.dumps(plan, indent=2))
    return path


def cmd_plan() -> dict:
    st = json.loads(STATE.read_text())
    d = data_of(fd("plan", "--world", st["world_id"], timeout=300), "plan")
    rv = d.get("review", {})
    summary = {"plan_id": d.get("id"), "drills": rv.get("requested_drills"), "serial": rv.get("requires_serial"), "gaps": rv.get("gaps"),
               "estimate": d.get("estimate"), "estimate_error": d.get("estimate_error"), "expires_at": d.get("expires_at")}
    st["last_plan"] = summary
    STATE.write_text(json.dumps(st, indent=2))
    print(json.dumps(summary, indent=1))
    return summary


async def import_report(campaign: str, version: str) -> list[dict]:
    from capyteam.analytics import analytics
    from capyteam.db import db, now

    report = fd("report", campaign, timeout=300)
    (LOCAL / f"report.{campaign}.json").write_text("\n".join(json.dumps(e) for e in report))
    data = data_of(report)
    drills = data.get("drills") or data.get("results") or []
    rows = []
    for dr in drills:
        did = dr.get("drill_id") or dr.get("id")
        detail = data_of(fd("report", campaign, "drill", did, "results", timeout=300, check=False))
        crit = detail.get("criteria") or detail.get("results") or detail.get("evaluations") or []
        passed = bool(crit) and all(c.get("threshold_met") and c.get("exact_check") is not False for c in crit)
        scores = [c.get("quality_score") for c in crit if c.get("quality_score") is not None]
        session_key = dr.get("session_key") or (detail.get("drill") or {}).get("session_key")
        sid = f"fd-{session_key}" if session_key else None
        score = round(sum(scores) / len(scores), 1) if scores else 0.0
        verdict = {"source": "firedrill", "campaign": campaign, "drill": did, "ending": dr.get("ending"), "criteria": crit, "passed": passed}
        await db().execute(
            "INSERT INTO drills (drill_id, campaign_id, session_id, scenario, agent_version, variant, source, ending, passed, score, results, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE passed = VALUES(passed), score = VALUES(score), results = VALUES(results)",
            [f"fd-{did}", campaign, sid, dr.get("scenario_name") or dr.get("scenario") or "firedrill", version, "pinned", "firedrill",
             dr.get("ending"), int(passed), score, verdict, now()],
        )
        if sid:
            await db().execute("UPDATE sessions SET verdict = ?, scenario = COALESCE(scenario, ?) WHERE session_id = ?",
                               [verdict, dr.get("scenario_name") or "firedrill", sid])
            s = type("S", (), {})()
            s.id, s.owner_id, s.version, s.mode, s.variant, s.flag_provider = sid, "owner-lumen", version, "drill", "pinned", "pinned"
            s.capy, s.scenario, s.world_id, s.source, s._amp = "", dr.get("scenario_name") or "", sid, "firedrill", None
            for c in crit:
                analytics.score(s, f"firedrill:{(c.get('name') or 'criterion')[:50]}", (c.get("quality_score") or 0) / 100, source="reviewer")
            analytics.score(s, "drill-pass", 1.0 if passed else 0.0, source="reviewer", comment=f"Firedrill {campaign}")
        rows.append({"drill": did, "session": sid, "ending": dr.get("ending"), "passed": passed, "score": score})
    analytics.flush()
    return rows


def cmd_go(version: str, approve: bool) -> None:
    if not approve:
        raise SystemExit("Pass --approve once a person has approved this campaign's credit estimate and local commands.")
    st = json.loads(STATE.read_text())
    summary = cmd_plan()
    if summary.get("gaps"):
        raise SystemExit(f"plan has gaps: {summary['gaps']}")
    applied = data_of(fd("apply", summary["plan_id"], "--approve", "--follow", timeout=1800))
    campaign = applied.get("campaign_id") or (applied.get("campaign") or {}).get("id")
    print("campaign", campaign)
    st.setdefault("campaigns", {})[version] = campaign
    STATE.write_text(json.dumps(st, indent=2))
    fd("runner", "enroll", "--enroll-device", timeout=300, check=False)
    plan = write_plan(version)
    env = dict(os.environ)
    p = subprocess.run(["firedrill", "run", "--plan", str(plan), "--descriptor", str(LOCAL / "descriptor.json"), "--campaign", campaign,
                        "--approve", "--session-only", "--json"], capture_output=True, text=True, timeout=7200, env=env)
    (LOCAL / f"run.{campaign}.log").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr)
    print("run exit", p.returncode)
    fd("watch", campaign, "--follow", timeout=3600, check=False)
    rows = asyncio.run(import_report(campaign, version))
    print(json.dumps(rows, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "go", "import", "write-plan"])
    ap.add_argument("--version", default="v1")
    ap.add_argument("--campaign")
    ap.add_argument("--approve", action="store_true")
    a = ap.parse_args()
    if a.cmd == "plan":
        cmd_plan()
    elif a.cmd == "write-plan":
        print(write_plan(a.version))
    elif a.cmd == "go":
        cmd_go(a.version, a.approve)
    else:
        print(json.dumps(asyncio.run(import_report(a.campaign, a.version)), indent=1))


if __name__ == "__main__":
    main()
