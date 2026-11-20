"""CapyTeam HTTP server.

  POST /chat                 Firedrill http.v1 driver: {"message", "session"} -> {"reply"}
  GET  /health               readiness for Firedrill's local plan
  /yard/...                  local practice yard (synthetic Stripe / QuickBooks / Gmail)
  GET  /api/...              town UI data, read live from SingleStore
  GET  /api/stream           server-sent events: new session events as they land in SingleStore
  POST /api/run/{day|race|night}  start practice days, races and night school from the UI
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import memory, sandbox
from .agent import SESSIONS, open_session
from .analytics import analytics
from .config import ROOT, settings
from .db import db, loads

log = logging.getLogger("capyteam.server")
WEB = ROOT / "web"
JOBS: dict[str, dict] = {}


def _drill_urls() -> dict[str, str]:
    return {k: v for k, v in {"stripe": settings.stripe_invoke_url, "quickbooks": settings.quickbooks_invoke_url,
                              "gmail": settings.gmail_invoke_url}.items() if v}


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await db().init_schema()
        await memory.ensure_v1()
    except Exception as e:  # noqa: BLE001
        log.warning("schema init skipped: %s", e)
    yield
    # Firedrill stops a per-drill service when the drill ends: close every open shift cleanly
    for s in list(SESSIONS.values()):
        try:
            await s.end(status="done")
        except Exception as e:  # noqa: BLE001
            log.warning("closing %s failed: %s", s.id, e)
    analytics.flush()


app = FastAPI(title="CapyTeam", lifespan=lifespan)
app.mount("/yard", sandbox.app)


@app.get("/health")
async def health():
    return {"ok": True, "mode": settings.mode}


# ---------------------------------------------------------------------- Firedrill driver
@app.post("/chat")
async def chat(request: Request):
    body = await request.json()
    text = str(body.get("message") or body.get("input") or "")
    key = str(body.get("session") or request.headers.get("x-session") or uuid.uuid4().hex[:12])
    urls = _drill_urls()
    if urls:  # running inside a Firedrill drill: synthetic tools come from the CLI's local addresses
        sid, mode, source, world = f"fd-{key}", "drill", "firedrill", f"fd-{key}"
    else:     # ad-hoc chat against the practice yard
        sid, mode, source, world = f"chat-{key}", "practice", "sandbox", "town"
        base = f"http://127.0.0.1:{settings.port}/yard"
        urls = {a: f"{base}/w/{world}/{a}/v1/invoke" for a in ("stripe", "quickbooks", "gmail")}
    s = await open_session(sid, mode=mode, source=source, world_id=world, invoke_urls=urls, scenario=os.environ.get("CAPY_SCENARIO"),
                           campaign_id=os.environ.get("CAPY_CAMPAIGN"))
    reply = await s.respond(text)
    analytics.flush()
    return {"reply": reply, "capy": s.capy, "version": s.version}


# ---------------------------------------------------------------------- UI data
def _jsonify(rows: list[dict], *cols: str) -> list[dict]:
    for r in rows:
        for c in cols:
            if c in r:
                r[c] = loads(r[c], r[c])
    return rows


_STATSIG: dict[str, Any] = {"at": 0.0, "serving": False}


async def _statsig_serving() -> bool:
    """True only when Statsig itself returns a group for the release experiment (not the hash fallback)."""
    from .flags import flags

    if time.time() - _STATSIG["at"] > 60:
        _STATSIG["serving"] = bool(await asyncio.to_thread(flags.statsig_group, "capyteam-probe", False))
        _STATSIG["at"] = time.time()
    return _STATSIG["serving"]


@app.get("/api/overview")
async def overview():
    versions = await memory.list_versions()
    stats = await db().rows(
        "SELECT agent_version AS version, source, COUNT(*) AS drills, SUM(passed) AS passed, ROUND(AVG(score),1) AS avg_score "
        "FROM drills GROUP BY agent_version, source ORDER BY agent_version")
    races = await db().rows(
        "SELECT agent_version AS version, COUNT(*) AS races, SUM(passed) AS passed FROM drills WHERE scenario = 'race' GROUP BY agent_version")
    costs = await db().rows(
        "SELECT agent_version AS version, COUNT(*) AS shifts, ROUND(AVG(cost_usd),5) AS avg_cost_usd, ROUND(AVG(tool_calls),1) AS avg_tools, "
        "ROUND(SUM(cost_usd),4) AS total_cost_usd, SUM(tokens) AS tokens FROM sessions GROUP BY agent_version ORDER BY agent_version")
    claims = await db().one("SELECT COUNT(*) AS claims, SUM(status = 'done') AS done FROM money_claims")
    blocked = await db().one("SELECT COUNT(*) AS n FROM events WHERE kind = 'claim' AND summary LIKE 'Claim refused%'")
    lessons = await db().one("SELECT COUNT(*) AS n FROM lessons")
    events = await db().one("SELECT COUNT(*) AS n FROM events")
    shipped, candidate = await memory.release_state()
    return {"versions": versions, "drill_stats": stats, "race_stats": races, "costs": costs, "claims": claims,
            "duplicates_blocked": (blocked or {}).get("n", 0), "lessons": (lessons or {}).get("n", 0), "events": (events or {}).get("n", 0),
            "shipped": shipped, "candidate": candidate, "db": db().label, "amplitude_events": analytics.sent,
            "experiment_provider": "statsig" if await _statsig_serving() else "capyteam-hash"}


@app.get("/api/sessions")
async def sessions(limit: int = 80, run: str | None = None):
    if run:
        rows = await db().rows("SELECT * FROM sessions WHERE session_id LIKE ? OR campaign_id = ? ORDER BY started_at DESC LIMIT ?", [f"{run}%", run, limit])
    else:
        rows = await db().rows("SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", [limit])
    return _jsonify(rows, "outcome", "verdict", "lessons_used")


@app.get("/api/session/{sid}")
async def session(sid: str):
    s = await db().one("SELECT * FROM sessions WHERE session_id = ?", [sid])
    ev = await db().rows("SELECT seq, ts, kind, building, capy_name, summary, payload FROM events WHERE session_id = ? ORDER BY seq", [sid])
    return {"session": _jsonify([s], "outcome", "verdict", "lessons_used")[0] if s else None, "events": _jsonify(ev, "payload")}


@app.get("/api/events")
async def events(since: str | None = None, run: str | None = None, limit: int = 300):
    q = "SELECT session_id, seq, ts, kind, building, capy_name, agent_version, mode, summary FROM events WHERE 1=1"
    args: list[Any] = []
    if since:
        q += " AND ts > ?"
        args.append(since)
    if run:
        q += " AND session_id LIKE ?"
        args.append(f"{run}%")
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    rows = await db().rows(q, args)
    rows.reverse()
    return rows


@app.get("/api/stream")
async def stream(request: Request, since: str | None = None, run: str | None = None):
    async def gen():
        cursor = since
        if cursor is None:
            last = await db().one("SELECT MAX(ts) AS ts FROM events")
            cursor = str((last or {}).get("ts") or "1970-01-01 00:00:00")
        while not await request.is_disconnected():
            q = "SELECT session_id, seq, ts, kind, building, capy_name, agent_version, mode, summary FROM events WHERE ts > ?"
            args: list[Any] = [cursor]
            if run:
                q += " AND session_id LIKE ?"
                args.append(f"{run}%")
            rows = await db().rows(q + " ORDER BY ts LIMIT 200", args)
            for r in rows:
                cursor = str(r["ts"])
                yield f"data: {json.dumps(r, default=str)}\n\n"
            yield ": keepalive\n\n"
            await asyncio.sleep(0.6)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/lessons")
async def lessons():
    rows = _jsonify(await memory.list_lessons(), "guard")
    scen = _jsonify(await db().rows("SELECT scenario_id, name, source_session, lesson_id, created_at FROM scenarios ORDER BY created_at"))
    return {"lessons": rows, "scenarios": scen}


@app.get("/api/casebook")
async def casebook(q: str | None = None):
    """Cognee casebook: cached answers from scripts/casebook.py, or a live recall for ?q=..."""
    from . import cognee_memory

    if q:
        res = await cognee_memory.recall(q, top_k=8)
        return {"live": True, "answers": [{"q": q, "a": cognee_memory.answer_text(res, 1500)}], "dataset": cognee_memory.DATASET}
    path = ROOT / ".runtime" / "casebook.json"
    answers = json.loads(path.read_text()) if path.exists() else []
    return {"live": False, "answers": answers, "dataset": cognee_memory.DATASET, "enabled": cognee_memory.enabled()}


@app.get("/api/analytics")
async def analytics_view():
    """The release experiment's arms (SingleStore) next to what Amplitude reports for the same sessions."""
    from . import amplitude_charts

    arms = await db().rows(
        "SELECT variant, agent_version AS version, COUNT(*) AS shifts, SUM(passed) AS done FROM drills "
        "WHERE campaign_id LIKE 'exp-%' GROUP BY variant, agent_version ORDER BY variant")
    via = await db().one("SELECT COUNT(*) AS n FROM events WHERE kind = 'start' AND session_id LIKE 'exp-%' AND summary LIKE '%via statsig%'")
    total = sum(int(a["shifts"]) for a in arms)
    return {"experiment": {"name": settings.statsig_experiment, "arms": arms, "shifts": total,
                           "assigned_by_statsig": int((via or {}).get("n", 0))},
            "amplitude": await amplitude_charts.snapshot()}


@app.get("/api/firedrill")
async def firedrill_view():
    """The drills as Firedrill scenarios: the library we registered plus the ones night school wrote."""
    root = ROOT / "firedrill"

    def load(path: Path) -> dict:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}

    evals = {p.name.removeprefix("eval.").removesuffix(".json"): load(p) for p in (root / "library").glob("eval.*.json")}
    library = []
    for p in sorted((root / "library").glob("scenario.*.json")):
        sc = load(p)
        checks, rubric = [], []
        for ref in sc.get("evaluations", []):
            ev = evals.get(ref.split(":")[-1], {})
            rubric.append(ev.get("name"))
            checks += [f"{c['service']}.{c['operation']} {c['comparison']} {c['expected']}" for c in ev.get("exact_checks", [])]
        library.append({"name": sc.get("name"), "description": sc.get("description"), "checks": checks, "rubric": [r for r in rubric if r],
                        "events": [f"{e.get('dependency') or ''} {e.get('kind') or 'event'}".strip() for e in sc.get("events", [])],
                        "twin": next((c.split(": ")[-1] for c in sc.get("conditions", []) if c.startswith("Practice-yard twin")), None)})
    generated = []
    for p in sorted((root / "generated").glob("*.scenario.json")):
        sc = load(p)
        ev = load(p.with_name(p.name.replace(".scenario.", ".evaluation.")))
        src = next((c for c in sc.get("conditions", []) if c.startswith("Generated from")), "")
        generated.append({"name": (ev.get("name") or sc.get("name") or "").replace("Night school: ", ""), "description": sc.get("description"),
                          "checks": [f"{c['service']}.{c['operation']} {c['comparison']} {c['expected']}" for c in ev.get("exact_checks", [])],
                          "source": src.replace("Generated from session ", "").split(" (")[0]})
    return {"library": library, "generated": generated}


@app.get("/api/drills")
async def drills(limit: int = 200):
    rows = await db().rows("SELECT drill_id, campaign_id, session_id, scenario, agent_version, variant, source, ending, passed, score, results, created_at "
                           "FROM drills ORDER BY created_at DESC LIMIT ?", [limit])
    return _jsonify(rows, "results")


@app.get("/api/claims")
async def claims(world: str | None = None, limit: int = 100):
    if world:
        rows = await db().rows("SELECT * FROM money_claims WHERE claim_key LIKE ? ORDER BY created_at", [f"{world}|%"])
    else:
        rows = await db().rows("SELECT * FROM money_claims ORDER BY created_at DESC LIMIT ?", [limit])
    return _jsonify(rows, "result")


@app.get("/api/yard/{world}")
async def yard_state(world: str):
    return sandbox.snapshot(world)


# ---------------------------------------------------------------------- jobs
async def _job(kind: str, coro) -> str:
    jid = f"{kind}-{uuid.uuid4().hex[:6]}"
    JOBS[jid] = {"id": jid, "kind": kind, "status": "running", "started": time.time()}

    async def runner():
        try:
            JOBS[jid]["result"] = await coro
            JOBS[jid]["status"] = "done"
        except Exception as e:  # noqa: BLE001
            JOBS[jid]["status"] = "failed"
            JOBS[jid]["error"] = str(e)[:500]
            log.exception("job %s failed", jid)

    asyncio.create_task(runner())
    return jid


@app.post("/api/run/day")
async def run_day_api(request: Request):
    from .practice import run_day

    body = await request.json() if await request.body() else {}
    run_id = body.get("run_id") or f"day-{body.get('version') or 'auto'}-{uuid.uuid4().hex[:5]}"
    jid = await _job("day", run_day(body.get("version"), body.get("scenarios"), run_id=run_id, parallel=int(body.get("parallel", 3))))
    return {"job": jid, "run_id": run_id}


@app.post("/api/run/race")
async def run_race_api(request: Request):
    from .race import run_race

    body = await request.json() if await request.body() else {}
    run_id = body.get("run_id") or f"race-{body.get('version') or 'auto'}-{uuid.uuid4().hex[:5]}"
    jid = await _job("race", run_race(body.get("version"), int(body.get("n", 10)), run_id=run_id))
    return {"job": jid, "run_id": run_id}


@app.post("/api/run/night")
async def run_night_api(request: Request):
    from .coach import night_school

    body = await request.json() if await request.body() else {}
    jid = await _job("night", night_school(body.get("base", "v1"), new_version=body.get("to"), run_id=body.get("run_id")))
    return {"job": jid}


@app.post("/api/ship/{version}")
async def ship(version: str):
    await memory.set_version_status(version, "shipped")
    return {"shipped": version}


@app.get("/api/jobs")
async def jobs():
    return list(JOBS.values())


# ---------------------------------------------------------------------- static UI
if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")
if (ROOT / "docs").exists():  # README screenshots, and the Amplitude charts the demo video shows
    app.mount("/docs", StaticFiles(directory=ROOT / "docs"), name="docs")


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("capyteam.server:app", host="0.0.0.0", port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
