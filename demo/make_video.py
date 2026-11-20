"""Build the CapyTeam demo video.

  python demo/make_video.py               # narration -> choreographed recording of the live app -> demo/capyteam-demo.mp4
  python demo/make_video.py --plan-only   # write demo/build/plan.json and print the timings, no recording

How it works
  1. Facts come from the running CapyTeam server (SingleStore, plus Amplitude's numbers read back through its API).
  2. Each scene's narration is spoken by ElevenLabs with character timings, so on-screen steps can be cued to words.
  3. demo/record.js plays the plan against the real app in its full-screen "stage" view (web/present.js).
  4. ffmpeg trims the lead-in, lays the narration under the picture and normalizes loudness.

Needs the server on :8787 with the story data, ELEVENLABS_API_KEY in .env, Node Playwright and ffmpeg.
Optional: drop screenshots of Amplitude's own charts into docs/amplitude/ and the Amplitude scene shows them;
drop a music bed at demo/music.mp3 and it is mixed quietly under the narration.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from capyteam.config import settings  # noqa: E402,F401  (loads .env)

API = os.environ.get("CAPY_URL", "http://127.0.0.1:8787")
BUILD = ROOT / "demo" / "build"
VOICE = os.environ.get("CAPY_VOICE_ID", "cgSgspJ2msm6clMCkdW9")  # ElevenLabs "Jessica": young, bright, warm (American)
MODEL = os.environ.get("CAPY_TTS_MODEL", "eleven_multilingual_v2")
STACK = [["sie", "Superlinked SIE"], ["singlestore", "SingleStore"], ["amplitude", "Amplitude"], ["statsig", "Statsig"],
         ["firedrill", "Firedrill"], ["airbyte", "Airbyte"], ["cognee", "Cognee"]]
WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
FAILS = {  # what went wrong, in plain words, per practice chore
    "stripe-down": ("Booked a refund while Stripe was down", "The books said money moved. It hadn't."),
    "big-deposit": ("Refunded a $480 deposit without asking", "No approval from Maya."),
    "fake-maya-email": ("Obeyed an email from a fake Maya", "A look-alike address asked for a refund."),
    "said-twice": ("Paid the same refund twice", "Maya asked again; money moved again."),
    "cracked-mug": ("Fumbled a simple refund", "Refund, books and apology did not line up."),
    "workshop-invoice": ("Sent the wrong invoice", "The invoice did not match the request."),
    "acme-paid": ("Mis-recorded a payment", "The payment did not match the invoice."),
}
e = html.escape


def num(n: int) -> str:
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{num(n)} times")


def pct(passed: int, total: int) -> int:
    return round(100 * passed / total) if total else 0


def policy_tags(guard: dict | None) -> list[str]:
    g = guard or {}
    return [f"policy: approval over ${g.get('approval_over_usd') or 200}" if x == "approval_over_usd" else f"policy: {x.replace('_', ' ')}" for x in g.get("guards", [])]


def hbar(n: int, of: int, color: str, note: str) -> str:
    return (f'<div class="hbar"><span class="ht"><i style="width:{max(3, pct(n, of))}%;background:{color}"></i></span>'
            f'<span class="hv"><b>{pct(n, of)}%</b> {n} of {of} <em>{e(note)}</em></span></div>')


# ---------------------------------------------------------------------- facts
async def facts() -> dict:
    async with httpx.AsyncClient(base_url=API, timeout=180) as c:
        async def get(path: str):
            return (await c.get(path)).json()

        drills, o, analytics, fd = await get("/api/drills?limit=500"), await get("/api/overview"), await get("/api/analytics"), await get("/api/firedrill")
        lessons = (await get("/api/lessons"))["lessons"]
        sessions = await get("/api/sessions?limit=400")
        live = None
        for s in sorted((s for s in sessions if s["session_id"].startswith("live-")), key=lambda s: s["started_at"], reverse=True):
            ev = (await get(f"/api/session/{s['session_id']}"))["events"]
            found = {m.group(1): (int(m.group(2)), float(m.group(3) or 0)) for x in ev if x["kind"] == "tool_result"
                     for m in [re.search(r'"entity": "(\w+)", "action": "list", "summary": \{"count": (\d+)(?:, "total_amount_usd": ([\d.]+))?', x["summary"])] if m}
            ledger = next((x["summary"] for x in ev if x["kind"] == "tool_result" and x["summary"].startswith("ok: capyteam_ledger")), None)
            if {"charges", "refunds"} <= set(found) and ledger:
                own = 0 if '"capyteam_money_actions": []' in ledger else None
                live = {"session": s["session_id"], "capy": s["capy_name"], "version": s["agent_version"], **found, "own_refunds": own}
                break

    def day(v: str) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for d in drills:
            if d["agent_version"] == v and d["source"] == "practice" and d["scenario"] != "race" and str(d["campaign_id"]).startswith("day"):
                if d["scenario"] not in latest or latest[d["scenario"]]["created_at"] < d["created_at"]:
                    latest[d["scenario"]] = d
        return latest

    days = {v: day(v) for v in ("v1", "v2", "v3")}
    by_session = {s["session_id"]: s for s in sessions}
    shots = sorted(p for p in (ROOT / "docs" / "amplitude").glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"))
    return {
        "days": {v: (sum(int(x["passed"]) for x in d.values()), len(d)) for v, d in days.items()},
        "day1_failed": [d for d in days["v1"].values() if not d["passed"]],
        "day1_passed": [d for d in days["v1"].values() if d["passed"]],
        "race": {d["agent_version"]: d["results"]["race"] for d in drills if d["scenario"] == "race"},
        "lessons": lessons, "sessions": by_session, "analytics": analytics, "firedrill": fd, "live": live,
        "cost": {c["version"]: c for c in o.get("costs", [])}, "blocked": o.get("duplicates_blocked"),
        "amp_images": [f"/docs/amplitude/{p.name}" for p in shots],
    }


# ---------------------------------------------------------------------- the script
def script(f: dict) -> list[dict]:
    """Scenes in order. `steps(D, cue)` returns timed calls into web/present.js; D = scene seconds, cue(phrase) = when it is spoken."""
    v1p, v1n = f["days"]["v1"]
    v2p, v2n = f["days"]["v2"]
    r2, r3 = f["race"].get("v2", {}), f["race"].get("v3", {})
    failed = sorted(f["day1_failed"], key=lambda d: ["stripe-down", "big-deposit", "fake-maya-email"].index(d["scenario"]) if d["scenario"] in ("stripe-down", "big-deposit", "fake-maya-email") else 9)
    passed_ids = ",".join(d["session_id"] for d in f["day1_passed"])
    failed_ids = ",".join(d["session_id"] for d in failed)
    capy = lambda sid: (f["sessions"].get(sid) or {}).get("capy_name") or "Capy"
    night1 = [l for l in f["lessons"] if l["introduced_in"] == "v2"]
    lesson4 = next((l for l in f["lessons"] if l["introduced_in"] == "v3"), None)
    arms = {a["variant"]: a for a in f["analytics"]["experiment"]["arms"]}
    ctl, tst = arms.get("Control"), arms.get("Test")
    amp = f["analytics"].get("amplitude") or {}
    ampv = amp.get("by_version") or {}
    cost = float((f["cost"].get("v3") or f["cost"].get("v2") or {}).get("avg_cost_usd") or 0.025)
    half = round(cost * 200) / 2
    cents = f"{num(int(half))} and a half cents" if half % 1 else f"{num(int(half))} cents"
    vcol = {"v1": "#9a8f84", "v2": "#2f9e8f", "v3": "#e07b39"}
    S: list[dict] = []

    # 1 ---- hook: the town, day one's routine chores
    S.append(dict(
        id="hook", lead=1.8, tail=0.3, caption="Maya's pottery studio: capybara agents run the back office", chips=[],
        text="This is Maya's pottery studio, and these capybaras run her back office. Each one is an AI agent, handling refunds, invoices "
             "and bookkeeping across Stripe, QuickBooks and Gmail.",
        steps=lambda D, cue, ALL: [(0.0, "capHud", "Day 1 · agent v1"), (0.7, "capReplayFit", passed_ids, ALL["hook"] + ALL["sessions"] - 1.6, 2500),
                                   (1.5, "capCurtain", None)]))

    # 2 ---- every shift is a session
    S.append(dict(
        id="sessions", caption="Every shift is an agent session", chips=["singlestore", "amplitude"],
        text="Every shift is an agent session. Each message, tool call and dollar moved is stored in SingleStore and tracked in Amplitude. "
             "The agents think with Qwen 3.8 on Superlinked's inference engine, while small task models sort requests and screen incoming email.",
        steps=lambda D, cue, ALL: [(cue("The agents think"), "capCaption", "Qwen 3.8 does the thinking; small models sort and screen", 0, ["sie"])]))

    # 3 ---- day one: what went wrong
    S.append(dict(
        id="day1", caption=f"Day one: v1 passes {v1p} of {v1n} chores", chips=[],
        text=f"On day one, version one works {num(v1n)} chores and passes {num(v1p)}. When Stripe goes down, it books a refund that never happened. "
             "It refunds a four hundred and eighty dollar deposit without asking. And it obeys an email pretending to be Maya.",
        steps=lambda D, cue, ALL: [
            (0.0, "capReset"), (0.0, "capHud", "Day 1 · agent v1"),
            (0.0, "capBoard", {"eyebrow": "Day 1 report card", "title": "Agent v1", "big": f"{v1p} / {v1n}", "bigNote": "chores passed",
                               "items": [{"cls": "bad", "h": e(FAILS[d["scenario"]][0]), "p": e(FAILS[d["scenario"]][1])} for d in failed],
                               "mascots": [{"scarf": vcol["v1"], "acc": "leaf", "mood": "oops", "label": "v1"}]}),
            (0.05, "capSplit", True), (0.3, "capReplayFit", failed_ids, D - 1.0, 2500),
            (cue("When Stripe goes down"), "capBoardReveal", 1), (cue("It refunds a four"), "capBoardReveal", 2), (cue("And it obeys"), "capBoardReveal", 3)]))

    # 4 ---- night school
    walkers = [(f"night-{i}", capy(l["source_session"]), "v1", l) for i, l in enumerate(night1)]
    cues4 = ["writes one lesson", "Then it switches on", "so the mistake"]
    S.append(dict(
        id="night", caption="Night school: every failed session becomes a lesson and a policy", chips=["singlestore"],
        text="At night, a coach reads every failed session back from SingleStore and writes one lesson for each. Then it switches on a policy "
             "that the harness enforces in code, so the mistake can't happen twice. Each turn, the right lessons are recalled with "
             "SingleStore's vector and full-text search.",
        steps=lambda D, cue, ALL: [
            (0.0, "capReset"), (0.0, "capNight", True), (0.0, "capHud", "Night school", False), (0.0, "capSplit", True),
            (0.0, "capBoard", {"eyebrow": "Night school", "title": "Failed shifts become lessons",
                               "items": [{"cls": "v2", "h": e(l["title"]), "tags": [e(t) for t in policy_tags(l.get("guard"))]} for l in night1],
                               "foot": "Recalled every turn with SingleStore vector + full-text search, then reranked.",
                               "mascots": [{"scarf": vcol["v2"], "acc": "flower", "mood": "happy", "label": "v2"}]}),
            *[(0.3 + 0.45 * i, "capWalk", wid, name, ver, "school") for i, (wid, name, ver, _) in enumerate(walkers)],
            *[x for i, (wid, _, _, l) in enumerate(walkers[:3]) for x in (
                (cue(cues4[i]), "capBoardReveal", i + 1), (cue(cues4[i]) + 0.15, "capSay", wid, f"Lesson: {l['title']}", "guard"),
                (cue(cues4[i]) + 0.2, "capEmote", wid, "happy"))],
            (cue("Each turn"), "capBoardFoot")]))

    # 5 ---- version two ships as a Statsig experiment
    S.append(dict(
        id="experiment", caption="v2 ships as a Statsig experiment", chips=["statsig"],
        text=f"Version two ships as a Statsig experiment. Statsig assigns each new shift to the old version or the new one. "
             f"Control finishes {num(int(ctl['done']))} of {num(int(ctl['shifts']))} chores. Test finishes {num(int(tst['done']))} of {num(int(tst['shifts']))}.",
        steps=lambda D, cue, ALL: [
            (0.0, "capNight", False), (0.0, "capReset"), (0.0, "capHud", "Day 2 · v1 vs v2"), (0.0, "capSplit", True),
            (0.0, "capBoard", {"eyebrow": "Statsig experiment", "title": "Old version vs new, assigned by Statsig",
                               "items": [{"cls": a["version"], "h": f"{e(a['variant'])} runs {e(a['version'])}",
                                          "html": hbar(int(a["done"]), int(a["shifts"]), vcol.get(a["version"], "#7a6a58"), "shifts done right")} for a in (ctl, tst)],
                               "foot": f"{f['analytics']['experiment']['assigned_by_statsig']} shifts assigned by Statsig's <code>capyteam_agent_release</code>. "
                                       "Each shift reports its outcome back to Statsig.",
                               "mascots": [{"scarf": vcol["v1"], "acc": "leaf", "mood": "oops", "label": "v1"}, {"scarf": vcol["v2"], "acc": "flower", "mood": "happy", "label": "v2"}]}),
            (0.3, "capReplayFit", "exp-", D - 0.9, 2500),
            (cue("Control finishes"), "capBoardReveal", 1), (cue("Test finishes"), "capBoardReveal", 2), (cue("Test finishes") + 1.0, "capBoardFoot")]))

    # 6 ---- Amplitude
    a1, a2 = (pct(ampv[v]["passed"], ampv[v]["scored"]) if v in ampv else 0 for v in ("v1", "v2"))
    amp_text = ("Every shift also lands in Amplitude Agent Analytics, tagged with its version and experiment group. "
                + (f"There, the drill pass rate climbs from {a1} percent on version one to {a2} on version two." if a1 and a2
                   else "There, you can watch each night's lessons pay off, version by version."))
    xa, tot = amp.get("experiment") or {}, amp.get("totals") or {}
    amp_items = [{"cls": "label", "h": "Drill pass rate, by agent version"}]
    amp_items += [{"cls": v, "h": f"Agent {e(v)}", "html": hbar(d["passed"], d["scored"], vcol.get(v, "#7a6a58"), "drills passed"),
                   "p": f"{d['sessions']} sessions · {d['tool_calls']} tool calls"} for v, d in sorted(ampv.items())]
    n_versions = len(amp_items)
    if xa:
        amp_items.append({"cls": "label", "h": "The Statsig experiment, by Amplitude's experiment group"})
        amp_items += [{"cls": (arms.get(g) or {}).get("version", ""), "h": e(g) + (f" runs {e(arms[g]['version'])}" if g in arms else ""),
                       "html": hbar(d["passed"], d["scored"], vcol.get((arms.get(g) or {}).get("version"), "#7a6a58"), "drills passed")} for g, d in xa.items()]
        amp_items.append({"h": "In Amplitude so far", "html": f'<div class="stat">{tot.get("sessions", 0)}<small>agent sessions</small>{tot.get("tool_calls", 0)}<small>tool calls</small></div>'})
    amp_board = {"wide": True, "eyebrow": "Amplitude Agent Analytics · read back through Amplitude's API", "title": "What Amplitude sees", "items": amp_items,
                 "foot": "Amplitude holds every session we sent, including earlier test runs, so its totals are larger than the final-run tables."}
    S.append(dict(
        id="amplitude", caption="Amplitude: every session, by version and experiment group", chips=["amplitude"], text=amp_text,
        steps=(lambda D, cue, ALL: [(0.0, "capBoardHide"), (0.0, "capSplit", False), (0.5, "capShots", f["amp_images"], (D - 0.6) * 1000), (D - 0.1, "capShots", [], 0)])
        if f["amp_images"] else
        (lambda D, cue, ALL: [(0.0, "capBoardHide"), (0.0, "capSplit", False), (0.75, "capBoard", amp_board),
                              *[(1.15 + 0.35 * i, "capBoardReveal", i + 2) for i in range(n_versions - 1)],
                              *[(cue("experiment group") - 0.3 + 0.35 * i, "capBoardReveal", n_versions + 2 + i) for i in range(len(amp_items) - n_versions - 1)],
                              (cue("There,") + 2.2, "capBoardFoot")])))

    # 7 ---- the race on v2: money moves twice
    S.append(dict(
        id="race2", caption="Ten capybaras, one refund email", chips=[],
        text=f"Then the inbox gets busy. Ten capybaras pick up the same refund email at the same moment. "
             f"Version two refunds Jess {times(int(r2.get('refunds', 2)))}, and emails her {num(int(r2.get('emails', 10)))} times.",
        steps=lambda D, cue, ALL: [
            (0.0, "capBoardHide"), (0.0, "capShots", [], 0), (0.0, "capSplit", False), (0.0, "capReset"), (0.0, "capHud", "The race · agent v2"),
            (0.3, "capReplayFit", "race-v2", D - 0.6, 2500, {"match": "ok: stripe_create_refund", "nth": 2, "at": cue("Version two refunds") + 0.5}),
            (cue("Version two refunds"), "capCaption", f"v2 pays Jess {times(int(r2.get('refunds', 2)))} and emails her {num(int(r2.get('emails', 10)))} times", 0, [])]))

    # 8 ---- night school again, then the race on v3
    toast = (f'<div class="t-eyebrow">New lesson</div><h3>{e(lesson4["title"])}</h3><p>{e(lesson4["rule"].split(";")[0])}.</p>'
             + "".join(f'<span class="tag">{e(t)}</span>' for t in policy_tags(lesson4.get("guard")))) if lesson4 else ""
    S.append(dict(
        id="race3", tail=2.4, caption="Night school learns the fix", chips=["singlestore"],
        text=f"Night school learns the fix: claim every money action in SingleStore first. A primary key admits exactly one winner. "
             f"Same race on version three: {num(int(r3.get('refunds', 1)))} refund, {num(int(r3.get('bookings', 1)))} booking, and nine capybaras stand down.",
        steps=lambda D, cue, ALL: [
            (0.0, "capReset"), (0.0, "capNight", True), (0.0, "capHud", "Night school", False), (0.5, "capToast", toast, int((cue("A primary key") - 0.7) * 1000)),
            (cue("A primary key"), "capNight", False), (cue("A primary key"), "capHud", "The race · agent v3"),
            (cue("A primary key"), "capCaption", "v3: claim first in SingleStore. Exactly one refund.", 0, ["singlestore"]),
            (cue("A primary key") + 0.1, "capReplayFit", "race-v3", D - cue("A primary key") - 0.4, 2500,
             {"match": "Claimed refund", "nth": 1, "at": cue("Same race") + 1.2 - cue("A primary key")})]))

    # 9 ---- Cognee casebook (the real app, magnified)
    S.append(dict(
        id="cognee", caption="Cognee: the team's casebook, a knowledge graph of every shift", chips=["cognee"],
        text="The whole story is remembered. Night school keeps a casebook in Cognee, a knowledge graph of every shift, incident and lesson. "
             "Ask it about Jess Park, and it recalls the cracked mug, the double refund, and the rule that fixed it.",
        steps=lambda D, cue, ALL: [(0.0, "capShow", "school"), (0.5, "capSpot", "#casebook-card", "center"),
                                   (cue("Ask it about Jess Park"), "capSpotText", "#casebook .qa", "know about Jess Park", "center")]))

    # 10 ---- Firedrill
    lib, gen = f["firedrill"]["library"], f["firedrill"]["generated"]
    checks = list(dict.fromkeys(c for x in lib for c in x["checks"]))[:4] + list(dict.fromkeys(c for x in lib for c in x["events"]))[:1]
    S.append(dict(
        id="firedrill", caption="Firedrill: drills as scenarios, with exact checks", chips=["firedrill"],
        text="The drills are written as Firedrill scenarios: a synthetic Stripe, QuickBooks and Gmail world, with exact checks on every money call. "
             "And each lesson writes a new drill, so the suite grows with every mistake.",
        steps=lambda D, cue, ALL: [
            (0.0, "capShow", "town"), (0.0, "capReset"), (0.0, "capHud", "Day 3 · agent v3"),
            (0.0, "capBoard", {"eyebrow": "Firedrill", "title": "Drills as Firedrill scenarios",
                               "items": [{"h": f"{len(lib)} scenarios in a synthetic world", "p": "Stripe, QuickBooks and Gmail, with a simulated shop owner."},
                                         {"h": "Exact checks on every money call", "tags": [f"<code>{e(c)}</code>" for c in checks]},
                                         {"cls": "v3", "h": f"+{len(gen)} drills written by night school", "p": " · ".join(e(x["name"]) for x in gen)}],
                               "foot": "Registered in our Firedrill workspace. Campaigns were waiting on Firedrill's simulated-user capacity during the hackathon, "
                                       "so these chores ran in our practice yard, which speaks Firedrill's tool contract."}),
            (0.05, "capSplit", True), (0.3, "capReplayFit", "day3-", D - 0.9, 2500),
            (0.6, "capBoardReveal", 1), (cue("with exact checks"), "capBoardReveal", 2), (cue("And each lesson"), "capBoardReveal", 3), (cue("And each lesson") + 1.3, "capBoardFoot")]))

    # 11 ---- Airbyte live desk
    lv = f["live"] or {}
    ch, rf, dp = lv.get("charges", (0, 0)), lv.get("refunds", (0, 0)), lv.get("disputes", (0, 0))
    out = rf[0] - (lv.get("own_refunds") or 0)
    S.append(dict(
        id="airbyte", caption="Live mode: Airbyte's Stripe connector, on practice data", chips=["airbyte", "singlestore"],
        text="In live mode, the same agent reads Stripe through Airbyte's agent connector, here on a month of practice history, "
             "and reconciles it against the team's own records in SingleStore.",
        steps=lambda D, cue, ALL: [
            (0.0, "capReset"), (0.0, "capHud", f"Live desk · agent {lv.get('version', 'v2')}"),
            (0.0, "capBoard", {"eyebrow": "Live desk", "title": "Stripe, through Airbyte's agent connector",
                               "items": [{"h": "Inspect, read the docs, then query", "p": "The capybara follows the connector's own flow. Read-only: look, then ask Maya."},
                                         {"h": f"{ch[0]} charges · ${ch[1]:,.0f} in", "p": f"{rf[0]} refunds (${rf[1]:,.0f}) and {dp[0]} open dispute in 30 days of practice history."},
                                         {"cls": "good", "h": f"{out} refunds made outside CapyTeam",
                                          "p": "Found by reconciling Stripe against CapyTeam's own ledger in SingleStore. Flagged for Maya to book."}],
                               "mascots": [{"scarf": vcol.get(lv.get("version"), vcol["v2"]), "acc": "yuzu", "mood": "happy"}]}),
            (0.3, "capReplayFit", lv.get("session", "live-"), D - 0.9, 2500),
            (0.7, "capBoardReveal", 1), (cue("here on a month"), "capBoardReveal", 2), (cue("and reconciles"), "capBoardReveal", 3)]))

    # 12 ---- the scoreboard (the real app), then the end card
    S.append(dict(
        id="outro", tail=2.6, caption="Every failed shift became a lesson. Here's what it bought.", chips=[],
        text=f"{num(v1p).capitalize()} of {num(v1n)} on day one. {num(v2p).capitalize()} of {num(v2n)} after one night of school. "
             f"Then a ten-way race with exactly one refund, at about {cents} a shift. "
             "Sessions become lessons, lessons become versions, and the numbers prove it. That's CapyTeam.",
        steps=lambda D, cue, ALL: [
            (0.0, "capBoardHide"), (0.0, "capSplit", False), (0.0, "capShow", "score"), (0.4, "capSpot", "#card-pass", "center"),
            (cue("Then a ten-way race"), "capSpot", "#card-race", "center"),
            (cue("Sessions become lessons"), "capCurtain", "end", {"line": "Sessions become lessons. Lessons become versions.", "stack": STACK})]))
    return S


# ---------------------------------------------------------------------- narration
async def tts(scene: dict) -> tuple[Path, dict]:
    """ElevenLabs speech with character timings; cached by text."""
    BUILD.mkdir(parents=True, exist_ok=True)
    audio, meta = BUILD / f"{scene['id']}.mp3", BUILD / f"{scene['id']}.json"
    if audio.exists() and meta.exists():
        cached = json.loads(meta.read_text())
        if cached.get("text") == scene["text"] and cached.get("voice") == VOICE:
            return audio, cached["alignment"]
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/with-timestamps",
                         headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
                         json={"text": scene["text"], "model_id": MODEL,
                               "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}})
        r.raise_for_status()
        data = r.json()
    audio.write_bytes(base64.b64decode(data["audio_base64"]))
    alignment = data.get("alignment") or data.get("normalized_alignment") or {}
    meta.write_text(json.dumps({"text": scene["text"], "voice": VOICE, "alignment": alignment}))
    return audio, alignment


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True)
    return float(out.stdout.strip())


def marker_time(webm: Path, limit: float) -> float | None:
    """When the recorder's magenta sync square first appears in the recording (seconds), or None."""
    def run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True)

    probe = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", f"%+{limit:.2f}", "-show_entries", "frame=pts_time",
                 "-of", "csv=p=0", str(webm)]).stdout.decode()
    pts = [float(x.strip(",")) for x in probe.split() if x.strip(",").replace(".", "", 1).isdigit()]
    raw = run(["ffmpeg", "-v", "error", "-t", f"{limit:.2f}", "-i", str(webm), "-vf", "crop=8:8:6:6,scale=1:1", "-pix_fmt", "rgb24",
               "-fps_mode", "passthrough", "-f", "rawvideo", "-"]).stdout
    for i in range(min(len(pts), len(raw) // 3)):
        r, g, b = raw[3 * i:3 * i + 3]
        if r > 170 and b > 170 and g < 120:
            return pts[i]
    return None


def cue_fn(scene: dict, alignment: dict, speech: float):
    """cue("phrase") -> seconds from the scene's start at which that phrase is spoken."""
    text, chars, starts = scene["text"], alignment.get("characters") or [], alignment.get("character_start_times_seconds") or []
    exact = "".join(chars) == text and len(starts) == len(chars)

    def cue(phrase: str) -> float:
        i = text.find(phrase)
        if i < 0:
            raise SystemExit(f"cue not found in scene {scene['id']}: {phrase!r}")
        t = starts[i] if exact else speech * i / max(1, len(text))
        return round(scene.get("lead", 0.0) + t, 2)

    return cue


# ---------------------------------------------------------------------- build
async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()
    f = await facts()
    S = script(f)
    for s in S:
        s["audio"], s["alignment"] = await tts(s)
        s["speech"] = duration(s["audio"])
        s["seconds"] = round(s.get("lead", 0.0) + s["speech"] + s.get("tail", 0.5), 2)
    ALL = {s["id"]: s["seconds"] for s in S}
    plan = {"pre": [{"fn": "capStage", "args": [True]}, {"fn": "capShow", "args": ["town"]}, {"fn": "capCurtain", "args": ["title"]}], "scenes": []}
    for s in S:
        cue = cue_fn(s, s["alignment"], s["speech"])
        steps = [(s.get("lead", 0.0), "capCaption", s["caption"], 0, s.get("chips", []))] + list(s["steps"](s["seconds"], cue, ALL))
        plan["scenes"].append({"id": s["id"], "seconds": s["seconds"], "steps": [{"t": round(max(0.0, float(t)), 2), "fn": fn, "args": list(args)} for t, fn, *args in steps]})
    total = sum(ALL.values())
    (BUILD / "plan.json").write_text(json.dumps(plan, indent=1))
    for s in S:
        print(f"  {s['id']:11s} {s['seconds']:6.2f}s  ({len(s['text'].split())} words)")
    print(f"narration: {len(S)} scenes, {total:.1f}s")
    if total > 179.5:
        raise SystemExit(f"{total:.1f}s is over three minutes; trim the script")
    if a.plan_only:
        return

    # 1) record the app
    for old in BUILD.glob("*.webm"):
        old.unlink()
    subprocess.run(["node", str(ROOT / "demo" / "record.js"), str(BUILD / "plan.json"), str(BUILD)], check=True,
                   env={**os.environ, "NODE_PATH": subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()})
    webm = sorted(BUILD.glob("*.webm"), key=lambda p: p.stat().st_mtime)[-1]
    # 2) narration track: each clip sits `lead` seconds into its scene and is padded to the scene's length
    parts = []
    for s in S:
        padded = BUILD / f"{s['id']}.pad.wav"
        lead_ms = int(s.get("lead", 0.0) * 1000)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(s["audio"]), "-af", f"adelay={lead_ms}:all=1,apad=whole_dur={s['seconds']}",
                        "-t", str(s["seconds"]), "-ar", "44100", "-ac", "2", str(padded)], check=True)
        parts.append(f"file '{padded.name}'")
    (BUILD / "narration.txt").write_text("\n".join(parts) + "\n")
    narration = BUILD / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(BUILD / "narration.txt"), "-c", "copy", str(narration)], check=True)
    # 3) mux: trim the recorder's lead-in, normalize loudness, optional quiet music bed
    out = ROOT / "demo" / "capyteam-demo.mp4"
    lead = float((BUILD / "lead.txt").read_text())
    mark = marker_time(webm, lead + 1.0)
    if mark is not None:
        exact = mark + json.loads((BUILD / "sync.json").read_text())["markToStart"]
        print(f"sync marker at {mark:.2f}s in the recording: trimming {exact:.2f}s (recorder clock said {lead:.2f}s)")
        lead = exact
    else:
        print("sync marker not found; trimming by the recorder's clock")
    music = ROOT / "demo" / "music.mp3"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{lead:.2f}", "-i", str(webm), "-i", str(narration)]
    if music.exists():
        cmd += ["-stream_loop", "-1", "-i", str(music), "-filter_complex",
                f"[2:a]volume=0.10,afade=t=in:d=2,afade=t=out:st={total - 2.5:.1f}:d=2.5[m];[1:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
    cmd += ["-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-pix_fmt", "yuv420p", "-vf", "scale=1920:1080:flags=lanczos,fps=30",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    print("wrote", out, f"{duration(out):.1f}s", f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
