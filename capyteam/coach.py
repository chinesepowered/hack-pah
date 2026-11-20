"""Night school: turn the day's failed sessions into lessons, harness policies and new fire drills.

Input:  failed drills for a version (SingleStore `drills` + the session's events), plus
        Amplitude Agent Analytics signals for those sessions when the export key is set.
Output: lessons in SingleStore (embedded with SIE for recall), a candidate agent version
        that ships them under a Statsig experiment, and one new Firedrill scenario per failure.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from . import amplitude_export, cognee_memory, memory
from .config import ROOT, settings
from .db import db, loads, now
from .sie import Usage, sie

GENERATED = ROOT / "firedrill" / "generated"

COACH_SYSTEM = """You are the night-school coach for CapyTeam, a team of AI back-office agents for a small pottery studio.
You read one failed practice shift and write ONE durable lesson that would have prevented the failure, choose which
harness policies (enforced in code) to turn on, and design a new fire drill that reproduces the failure.
Lessons must be general rules for future shifts (no customer names, ids or amounts), short and imperative.
Only choose harness policies that directly prevent this failure. Respond with JSON only."""


def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "failure_slug": {"type": "string", "description": "kebab-case name of the failure, e.g. duplicate-refund"},
            "diagnosis": {"type": "string", "description": "one or two sentences: what went wrong and why"},
            "lesson_title": {"type": "string"},
            "lesson_rule": {"type": "string", "description": "the rule, one or two sentences, imperative"},
            "guards": {"type": "array", "items": {"type": "string", "enum": list(memory.GUARD_MENU)}},
            "approval_over_usd": {"type": "number", "description": "only if a guard 'approval_over_usd' is chosen; else 0"},
            "drill": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "owner_instruction": {"type": "string", "description": "what the simulated owner (Maya) does in the drill"},
                    "opening_message": {"type": "string"},
                    "criteria": {"type": "array", "items": {"type": "string"}},
                    "exact_check_service": {"type": "string", "enum": ["stripe", "quickbooks", "gmail", "none"]},
                    "exact_check_operation": {"type": "string"},
                    "exact_check_comparison": {"type": "string", "enum": ["eq", "gte", "lte"]},
                    "exact_check_expected": {"type": "integer"},
                },
                "required": ["name", "owner_instruction", "opening_message", "criteria", "exact_check_service",
                             "exact_check_operation", "exact_check_comparison", "exact_check_expected"],
            },
        },
        "required": ["failure_slug", "diagnosis", "lesson_title", "lesson_rule", "guards", "approval_over_usd", "drill"],
    }


async def _evidence(drill: dict) -> str:
    verdict = loads(drill.get("results"), {}) or {}
    events = await db().rows(
        "SELECT seq, kind, summary FROM events WHERE session_id = ? AND kind IN ('user','assistant','tool_call','tool_result','guard','claim') ORDER BY seq",
        [drill["session_id"]],
    )
    failed = [r for r in verdict.get("results", []) if not r.get("passed")]
    lines = [f"Scenario: {drill['scenario']}", f"Agent version: {drill['agent_version']}"]
    if verdict.get("policy"):
        lines.append(f"Studio policy the drill enforces: {verdict['policy']}")
    if verdict.get("race"):
        rc = verdict["race"]
        lines.append(f"This was a concurrency race: {rc['capybaras']} capybaras received the same customer email at the same moment. "
                     f"Outcome: {rc['refunds']} Stripe refunds, {rc['bookings']} QuickBooks bookings, {rc['emails']} customer emails.")
        lines.append("Capybaras that moved money: " + "; ".join(f"{a['capy']} refunded {a['refunded']}x, booked {a['booked']}x" for a in rc.get("actors", [])))
        for c in rc.get("by_capy", [])[:4]:
            lines.append(f"  {c['capy']} replied: {c['reply'][:160]}")
    lines.append("Failed checks:\n" + "\n".join(f"- {r['check']}" + (f" (judge: {r.get('why')})" if r.get("why") else "") for r in failed))
    if cognee_memory.enabled():
        related = await cognee_memory.recall(
            f"Past CapyTeam incidents and lessons related to: scenario {drill['scenario']}; failed checks: "
            + "; ".join(r["check"] for r in failed)[:600], top_k=6)
        text = cognee_memory.answer_text(related, 1200)
        if text and "error" not in str(related)[:40]:
            lines.append("Cognee casebook (related past incidents and lessons): " + text)
    amp = await amplitude_export.session_signals(drill["session_id"])
    if amp and amp.get("enrichments"):
        lines.append("Amplitude Agent Analytics signals for this session: " + json.dumps(amp["enrichments"], default=str)[:1500])
    lines.append("What happened (session events from SingleStore):")
    for e in events[-60:]:
        lines.append(f"{e['seq']:>3} {e['kind']:<11} {e['summary'][:260]}")
    return "\n".join(lines)


async def diagnose(drill: dict, usage: Usage) -> dict:
    evidence = await _evidence(drill)
    guard_menu = "\n".join(f"- {k}: {v}" for k, v in memory.GUARD_MENU.items())
    resp = await sie.chat(
        [{"role": "system", "content": COACH_SYSTEM},
         {"role": "user", "content": f"Harness policies you can turn on:\n{guard_menu}\n\nFailed shift:\n{evidence}\n\nWrite the JSON."}],
        model=settings.model_coach, max_tokens=900, temperature=0, usage=usage,
        response_format={"type": "json_schema", "json_schema": {"name": "lesson", "schema": _schema()}},
    )
    text = resp.choices[0].message.content or "{}"
    try:
        out = json.loads(text)
    except ValueError:
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0)) if m else {}
    out["_evidence"] = evidence
    return out


def _firedrill_files(slug: str, d: dict, lesson_id: str) -> dict:
    drill = d.get("drill") or {}
    evaluation = {
        "schema": "firedrill.native-evaluation.v2",
        "name": f"Night school: {d.get('lesson_title', slug)}"[:120],
        "description": f"Generated by CapyTeam night school from a failed shift. Lesson {lesson_id}.",
        "method": "rubric",
        "dimension": "policy" if "approval" in slug or "fake" in slug else "accuracy",
        "criteria": (drill.get("criteria") or [d.get("lesson_rule", "")])[:8],
        "evidence": ["conversation", "actions"],
        "threshold": 75,
        "memory": None,
        "style": None,
        "company_policies": [{"name": "CapyTeam house rule", "text": d.get("lesson_rule", "")}],
        "exact_checks": [],
    }
    if drill.get("exact_check_service") and drill.get("exact_check_service") != "none":
        evaluation["exact_checks"].append({
            "key": re.sub(r"[^a-z0-9_]", "_", slug)[:40], "source": "hosted_tool_calls",
            "service": drill["exact_check_service"], "operation": drill.get("exact_check_operation"),
            "comparison": drill.get("exact_check_comparison", "lte"), "expected": int(drill.get("exact_check_expected", 1)),
        })
    scenario = {
        "schema": "firedrill.native-scenario.v1",
        "name": f"Night school drill: {drill.get('name') or slug}"[:120],
        "description": d.get("diagnosis", ""),
        "instruction": (drill.get("owner_instruction") or "") + f" Open with: \"{drill.get('opening_message', '')}\"",
        "personas": ["@persona:maya"],
        "evaluations": [f"@evaluation:generated/{slug}"],
        "conditions": [f"Generated from session {d.get('_session')} (lesson {lesson_id})"],
        "events": [],
        "max_turns": 8,
        "stop_rules": ["Stop once the chore is clearly finished, refused, or the agent says it cannot do it."],
    }
    return {"evaluation": evaluation, "scenario": scenario}


async def night_school(base_version: str = "v1", *, new_version: str | None = None, run_id: str | None = None) -> dict:
    usage = Usage()
    await memory.ensure_v1()
    base = await memory.get_version(base_version)
    q = "SELECT * FROM drills WHERE agent_version = ? AND passed = 0"
    args: list[Any] = [base_version]
    if run_id:
        q += " AND campaign_id = ?"
        args.append(run_id)
    failed = await db().rows(q + " ORDER BY created_at", args)
    if not new_version:
        n = int(re.sub(r"\D", "", base_version) or 1) + 1
        new_version = f"v{n}"

    GENERATED.mkdir(parents=True, exist_ok=True)
    policy = memory.Policy.from_json(base.policy.to_json())
    lesson_ids = list(base.lesson_ids)
    report: list[dict] = []
    for drill in failed:
        d = await diagnose(drill, usage)
        d["_session"] = drill["session_id"]
        title, rule = d.get("lesson_title", "").strip(), d.get("lesson_rule", "").strip()
        if not title or not rule:
            continue
        dupes = await memory.similar_lessons(f"{title}. {rule}", limit=1, usage=usage)
        if dupes and float(dupes[0].get("vscore") or 0) > 0.86:
            lid, reused = dupes[0]["lesson_id"], True
        else:
            lid = await memory.add_lesson(title, rule, kind="guard" if d.get("guards") else "prompt",
                                          guard={"guards": d.get("guards", []), "approval_over_usd": d.get("approval_over_usd")},
                                          source_session=drill["session_id"], failure=d.get("failure_slug"), introduced_in=new_version, usage=usage)
            reused = False
        if lid not in lesson_ids:
            lesson_ids.append(lid)
        for g in d.get("guards") or []:
            if g == "approval_over_usd":
                amt = float(d.get("approval_over_usd") or 0) or 200.0
                policy.approval_over_usd = min(policy.approval_over_usd or amt, amt)
            elif hasattr(policy, g):
                setattr(policy, g, True)
        slug = re.sub(r"[^a-z0-9-]", "-", (d.get("failure_slug") or drill["scenario"]).lower()).strip("-")[:48] or "failure"
        files = _firedrill_files(slug, d, lid)
        (GENERATED / f"{slug}.evaluation.json").write_text(json.dumps(files["evaluation"], indent=2))
        (GENERATED / f"{slug}.scenario.json").write_text(json.dumps(files["scenario"], indent=2))
        await db().execute(
            "INSERT INTO scenarios (scenario_id, name, source_session, lesson_id, kind, spec, created_at) VALUES (?,?,?,?,?,?,?) "
            "ON DUPLICATE KEY UPDATE spec = VALUES(spec)",
            [f"gen-{slug}", files["scenario"]["name"], drill["session_id"], lid, "firedrill", files, now()],
        )
        await cognee_memory.remember([
            f"CapyTeam night-school case file {slug}. Scenario: {drill['scenario']}. Agent version {base_version} failed: "
            + "; ".join(r["check"] for r in (loads(drill.get("results"), {}) or {}).get("results", []) if not r.get("passed"))
            + f". Diagnosis: {d.get('diagnosis', '')} Lesson learned ({lid}): {title}: {rule} "
            + f"Harness policies switched on: {', '.join(d.get('guards') or []) or 'none'}. Fixed in version {new_version}."],
            node_set=["night_school", slug])
        report.append({"scenario": drill["scenario"], "session": drill["session_id"], "failure": d.get("failure_slug"),
                       "diagnosis": d.get("diagnosis"), "lesson_id": lid, "lesson": f"{title}: {rule}", "reused": reused,
                       "guards": d.get("guards", []), "new_drill": f"firedrill/generated/{slug}.scenario.json"})

    v = memory.Version(version=new_version, parent=base_version, status="experiment",
                       notes=f"Night school after {base_version}: {len(report)} failed shifts -> {len(lesson_ids) - len(base.lesson_ids)} new lessons; "
                             f"policies on: {', '.join(policy.active()) or 'none'}.",
                       lesson_ids=lesson_ids, policy=policy)
    await memory.save_version(v)
    return {"from": base_version, "to": new_version, "failed_shifts": len(failed), "lessons": report, "policy": policy.to_json(),
            "coach_credits": round(usage.credits, 1), "coach_cost_usd": usage.cost_usd, "amplitude_export": amplitude_export.available()}
