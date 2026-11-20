"""Build the CapyTeam demo video: ElevenLabs narration + Playwright recording of the live app + ffmpeg.

  python demo/make_video.py             # narration (cached) -> recording -> demo/capyteam-demo.mp4

Needs the CapyTeam server on :8787 with the story data in SingleStore, ELEVENLABS_API_KEY in .env,
Node Playwright (preinstalled here) and ffmpeg.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from capyteam.config import settings  # noqa: E402,F401  (loads .env)

BUILD = ROOT / "demo" / "build"
VOICE = os.environ.get("CAPY_VOICE_ID", "cgSgspJ2msm6clMCkdW9")  # ElevenLabs "Jessica": young, bright, warm (American)
MODEL = os.environ.get("CAPY_TTS_MODEL", "eleven_multilingual_v2")


async def facts() -> dict:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8787", timeout=60) as c:
        drills = (await c.get("/api/drills?limit=500")).json()
        o = (await c.get("/api/overview")).json()
    def day(v):
        latest = {}
        for d in drills:
            if d["agent_version"] == v and d["source"] == "practice" and d["scenario"] != "race" and d["campaign_id"].startswith("day"):
                if d["scenario"] not in latest or latest[d["scenario"]]["created_at"] < d["created_at"]:
                    latest[d["scenario"]] = d
        return sum(int(x["passed"]) for x in latest.values()), len(latest)
    race = {d["agent_version"]: d["results"]["race"] for d in drills if d["scenario"] == "race"}
    costs = {c["version"]: c for c in o.get("costs", [])}
    fd = {}
    for d in drills:  # latest Firedrill tool-session verdict per (version, drill)
        if d["source"] == "firedrill-tools":
            k = (d["agent_version"], d["scenario"])
            if k not in fd or fd[k]["created_at"] < d["created_at"]:
                fd[k] = d
    fdtools = {}
    for (v, _), d in fd.items():
        p, n = fdtools.get(v, (0, 0))
        fdtools[v] = (p + int(d["passed"]), n + 1)
    return {"v1": day("v1"), "v2": day("v2"), "v3": day("v3"), "race": race, "lessons": o.get("lessons"), "events": o.get("events"),
            "cost": costs, "blocked": o.get("duplicates_blocked"), "fdtools": fdtools}


def scenes(f: dict) -> list[dict]:
    v1p, v1n = f["v1"]
    v2p, v2n = f["v2"]
    v3p, v3n = f["v3"]
    r2 = f["race"].get("v2", {})
    r3 = f["race"].get("v3", {})
    cents = round(100 * float((f["cost"].get("v3") or f["cost"].get("v2") or {}).get("avg_cost_usd") or 0.02), 1)
    return [
        {"id": "intro", "action": "town:day1", "caption": "CapyTeam: your back office, run by capybaras",
         "text": "Meet CapyTeam. It's a team of capybara agents that runs the back office for Maya's little pottery studio. "
                 "They handle refunds, invoices and bookkeeping across Stripe, QuickBooks and Gmail, and they get a little better after every shift."},
        {"id": "problem", "action": "town:day1", "caption": "Agents that touch money need practice and memory",
         "text": "Here's the problem. When an agent touches money, one mistake is a double refund or a fake invoice. "
                 "So every shift is an agent session. It's stored in SingleStore, tracked in Amplitude, and every model call is a small open model on Superlinked's SIE."},
        {"id": "day1", "action": "shifts:day1-stripe-down", "caption": f"Day one, v1: {v1p} of {v1n} practice chores pass",
         "text": f"On day one, version one worked seven chores and passed {v1p}. "
                 "When Stripe went down, it booked a refund that never happened. It refunded a four hundred and eighty dollar deposit without asking. "
                 "And it obeyed an email pretending to be Maya."},
        {"id": "night1", "action": "school", "caption": "Night school turns failed shifts into lessons",
         "text": "At night, the coach reads each failed session from SingleStore. It writes one lesson and switches on the harness policy that prevents it. "
                 "Then it designs a new Firedrill drill that reproduces the failure. The lessons are embedded with SIE and recalled with SingleStore's vector and full-text search."},
        {"id": "cognee", "action": "school:casebook-card", "caption": "Cognee: the team's casebook across every shift",
         "text": "Night school also keeps a casebook in Cognee. Every shift and every case file goes into Cognee's knowledge graph, "
                 "and the coach recalls related incidents before it writes a lesson. Ask it about Jess Park, and it remembers the cracked mug, "
                 "the double refund, and the rule that fixed it."},
        {"id": "day2", "action": "score", "caption": f"Day two, v2: {v2p} of {v2n} pass",
         "text": f"Version two goes out as an experiment, wired to Statsig. Each new shift is assigned a version, "
                 f"and Amplitude Agent Analytics compares the sessions by version and variant. Version two passes {v2p} of {v2n}."},
        {"id": "race2", "action": "race", "caption": f"The race on v2: {r2.get('refunds', 2)} refunds for one request",
         "text": f"Then the inbox gets busy. Ten capybaras pick up the same customer email at the same moment. "
                 f"Version two refunds Jess {r2.get('refunds', 2)} times and emails her {r2.get('emails', 10)} times. No lesson so far covered teammates."},
        {"id": "race3", "action": "town:race-v3", "caption": f"v3: exactly one refund. Claims in SingleStore",
         "text": f"Night school learns the fix: claim every money action in SingleStore first. "
                 f"A primary key admits exactly one winner. On version three, the same ten capybaras race again. "
                 f"{r3.get('refunds', 1)} refund, {r3.get('bookings', 1)} booking, and the rest stand down."},
        ({"id": "firedrill", "action": "town:fdtools", "caption": "Drills on Firedrill's synthetic Stripe, QuickBooks and Gmail",
          "text": "Firedrill is the training ground. CapyTeam is registered in a Firedrill world, and we ran its drills against Firedrill's "
                  "synthetic Stripe, QuickBooks and Gmail. Pass or fail comes from counts read back from those services. "
                  + " ".join(f"Version {'one' if v == 'v1' else 'two' if v == 'v2' else 'three'} passed {p} of {n}." for v, (p, n) in sorted(f["fdtools"].items()))
                  + " Every night-school lesson adds a new drill, so the suite grows with every mistake."}
         if f.get("fdtools") and all(n >= 3 for _, n in f["fdtools"].values()) and len(f["fdtools"]) >= 2 else
         {"id": "firedrill", "action": "school:gen-drills", "caption": "Firedrill: a synthetic Stripe, QuickBooks and Gmail world",
          "text": "Firedrill is where the drills live. CapyTeam is registered in a Firedrill world with synthetic Stripe, QuickBooks and Gmail. "
                  "Its drills cover a repeated refund, a Stripe outage and a large refund that needs approval, with exact checks on the tool calls. "
                  "Every night-school lesson adds a new Firedrill drill, so the test suite grows with every mistake."}),
        {"id": "airbyte", "action": "shifts:live", "caption": "Live mode: Airbyte's Stripe connector, on practice data",
         "text": "In live mode, the same agent reads Stripe through Airbyte's agent connector, here on a month of practice history. "
                 "It inspects the connector, reads its docs, then queries, and reconciles what Stripe says against what the team recorded in SingleStore."},
        {"id": "outro", "action": "score", "caption": "CapyTeam gets better every night",
         "text": f"Every model call is a small open model on SIE, at about {cents} cents a shift. "
                 "Sessions become lessons, lessons become versions, and the data shows each version is better. That's CapyTeam."},
    ]


async def tts(scene: dict) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / f"{scene['id']}.mp3"
    meta = BUILD / f"{scene['id']}.txt"
    if path.exists() and meta.exists() and meta.read_text() == scene["text"]:
        return path
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}",
                         headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "accept": "audio/mpeg"},
                         json={"text": scene["text"], "model_id": MODEL,
                               "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}})
        r.raise_for_status()
        path.write_bytes(r.content)
        meta.write_text(scene["text"])
    return path


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True)
    return float(out.stdout.strip())


async def main() -> None:
    f = await facts()
    print(json.dumps({k: v for k, v in f.items() if k != "cost"}, default=str)[:600])
    sc = scenes(f)
    for s in sc:
        s["audio"] = str(await tts(s))
        s["seconds"] = round(duration(Path(s["audio"])) + 0.6, 2)
    total = sum(s["seconds"] for s in sc)
    print(f"narration: {len(sc)} scenes, {total:.1f}s")
    (BUILD / "scenes.json").write_text(json.dumps(sc, indent=1))
    # 1) record the app
    subprocess.run(["node", str(ROOT / "demo" / "record.js"), str(BUILD / "scenes.json"), str(BUILD)], check=True,
                   env={**os.environ, "NODE_PATH": subprocess.run(["npm", "root", "-g"], capture_output=True, text=True).stdout.strip()})
    webm = sorted(BUILD.glob("*.webm"), key=lambda p: p.stat().st_mtime)[-1]
    # 2) narration track: each clip padded to its scene length
    concat = BUILD / "narration.txt"
    parts = []
    for s in sc:
        padded = BUILD / f"{s['id']}.pad.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", s["audio"], "-af", f"apad=whole_dur={s['seconds']}",
                        "-ar", "44100", "-ac", "2", str(padded)], check=True)
        parts.append(f"file '{padded.name}'")
    concat.write_text("\n".join(parts) + "\n")
    narration = BUILD / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(narration)], check=True)
    # 3) mux (skip the recorder's first second of page load)
    out = ROOT / "demo" / "capyteam-demo.mp4"
    lead = float((BUILD / "lead.txt").read_text()) if (BUILD / "lead.txt").exists() else 0.0
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{lead:.2f}", "-i", str(webm), "-i", str(narration),
                    "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-vf", "scale=1920:1080:flags=lanczos,fps=30", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out)], check=True)
    print("wrote", out, f"{duration(out):.1f}s", f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    asyncio.run(main())
