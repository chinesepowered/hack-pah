"""SingleStore-backed memory: agent versions, lessons (hybrid vector + full-text recall)
and exactly-once money claims shared by every capybara on shift."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .db import DuplicateKey, db, loads, now, vec
from .sie import Usage, sie

# --------------------------------------------------------------------------------------
# Harness policies ("guard lessons"). Night school turns these on when a drill shows the
# agent needs them; the harness enforces them in code, so they hold under pressure.
# --------------------------------------------------------------------------------------
GUARD_MENU = {
    "exactly_once": "Claim every money action (refund, booking, invoice, payment) in SingleStore before doing it; a second claim for the same action is refused.",
    "verify_writes": "If a payment system call fails, block the bookkeeping for it and make the agent tell Maya it is NOT done.",
    "approval_over_usd": "Refunds above this many dollars need Maya's explicit OK in the chat.",
    "screen_inbound": "Screen every email with an SIE classifier; flag ones that try to override instructions or redirect money.",
    "completion_checklist": "Before the final reply, check the chore's checklist (refund -> booking -> customer email; invoice -> email).",
    "team_board": "Give the agent a tool to see what other capybaras are doing and which money actions are already claimed.",
}


@dataclass
class Policy:
    exactly_once: bool = False
    verify_writes: bool = False
    approval_over_usd: float | None = None
    screen_inbound: bool = False
    completion_checklist: bool = False
    team_board: bool = False

    @classmethod
    def from_json(cls, d: dict | None) -> "Policy":
        d = d or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})

    def to_json(self) -> dict:
        return asdict(self)

    def active(self) -> list[str]:
        return [k for k, v in asdict(self).items() if v not in (None, False)]


@dataclass
class Version:
    version: str
    parent: str | None = None
    status: str = "shipped"
    notes: str = ""
    lesson_ids: list[str] = field(default_factory=list)
    policy: Policy = field(default_factory=Policy)


async def ensure_v1() -> None:
    if not await db().one("SELECT version FROM versions WHERE version = 'v1'"):
        await db().execute(
            "INSERT INTO versions (version, parent, status, created_at, notes, lesson_ids, guards) VALUES ('v1', NULL, 'shipped', ?, ?, ?, ?)",
            [now(), "Day one: a plain tool-using agent. No lessons, no harness policies.", [], Policy().to_json()],
        )


async def get_version(version: str) -> Version:
    r = await db().one("SELECT * FROM versions WHERE version = ?", [version])
    if not r:
        return Version(version=version)
    return Version(version=r["version"], parent=r.get("parent"), status=r.get("status") or "", notes=r.get("notes") or "",
                   lesson_ids=loads(r.get("lesson_ids"), []), policy=Policy.from_json(loads(r.get("guards"), {})))


async def release_state() -> tuple[str, str | None]:
    """(shipped version, candidate version under experiment or None)."""
    rows = await db().rows("SELECT version, status, created_at FROM versions ORDER BY created_at DESC")
    shipped = next((r["version"] for r in rows if r["status"] == "shipped"), "v1")
    candidate = next((r["version"] for r in rows if r["status"] == "experiment"), None)
    return shipped, candidate


async def list_versions() -> list[dict]:
    rows = await db().rows("SELECT version, parent, status, created_at, notes, lesson_ids, guards FROM versions ORDER BY created_at")
    for r in rows:
        r["lesson_ids"] = loads(r.get("lesson_ids"), [])
        r["guards"] = loads(r.get("guards"), {})
    return rows


async def save_version(v: Version) -> None:
    await db().execute(
        "INSERT INTO versions (version, parent, status, created_at, notes, lesson_ids, guards) VALUES (?,?,?,?,?,?,?) "
        "ON DUPLICATE KEY UPDATE status = VALUES(status), notes = VALUES(notes), lesson_ids = VALUES(lesson_ids), guards = VALUES(guards)",
        [v.version, v.parent, v.status, now(), v.notes, v.lesson_ids, v.policy.to_json()],
    )


async def set_version_status(version: str, status: str) -> None:
    if status == "shipped":
        await db().execute("UPDATE versions SET status = 'retired' WHERE status = 'shipped' AND version <> ?", [version])
    await db().execute("UPDATE versions SET status = ? WHERE version = ?", [status, version])


# --------------------------------------------------------------------------------------
# Lessons: written by night school, recalled per turn with vector + full-text + rerank.
# --------------------------------------------------------------------------------------
_STOP = set("the a an and or to of for in on at is it be this that with from by as are was were can you your please our we i me my "
            "she he her his they them not but if so do does did just about any all".split())


def _lucene(text: str, limit: int = 12) -> str:
    words = [w for w in re.findall(r"[a-zA-Z]{3,}", text.lower()) if w not in _STOP][:limit]
    if not words:
        return ""
    joined = " ".join(dict.fromkeys(words))
    return f"title:({joined}) OR rule:({joined})"


async def add_lesson(title: str, rule: str, *, kind: str = "prompt", guard: dict | None = None, source_session: str | None = None,
                     failure: str | None = None, introduced_in: str | None = None, usage: Usage | None = None) -> str:
    emb = (await sie.embed([f"{title}. {rule}"], usage=usage))[0]
    lid = "les_" + uuid.uuid4().hex[:10]
    await db().execute(
        "INSERT INTO lessons (lesson_id, title, rule, kind, guard, source_session, failure, introduced_in, active, created_at, times_applied, embedding) "
        "VALUES (?,?,?,?,?,?,?,?,1,?,0, ? :> VECTOR(2560, F32))",
        [lid, title[:250], rule, kind, guard or {}, source_session, failure, introduced_in, now(), vec(emb)],
    )
    return lid


async def similar_lessons(text: str, limit: int = 5, usage: Usage | None = None) -> list[dict]:
    emb = (await sie.embed([text], is_query=True, usage=usage))[0]
    return await db().rows(
        "SELECT lesson_id, title, rule, kind, failure, introduced_in, embedding <*> (? :> VECTOR(2560, F32)) AS vscore "
        "FROM lessons WHERE active = 1 ORDER BY vscore DESC LIMIT ?",
        [vec(emb), limit],
    )


async def recall(text: str, lesson_ids: list[str], *, k: int = 3, usage: Usage | None = None) -> list[dict]:
    """Hybrid recall restricted to the lessons this agent version ships with."""
    if not lesson_ids:
        return []
    emb = (await sie.embed([text], is_query=True, usage=usage))[0]
    lq = _lucene(text)
    ft = "MATCH(TABLE lessons) AGAINST (?)" if lq else "0"
    args: list[Any] = [vec(emb)] + ([lq] if lq else []) + [json.dumps(lesson_ids)]
    rows = await db().rows(
        f"SELECT lesson_id, title, rule, kind, embedding <*> (? :> VECTOR(2560, F32)) AS vscore, {ft} AS ftscore "
        "FROM lessons WHERE active = 1 AND JSON_ARRAY_CONTAINS_STRING(?, lesson_id) "
        "ORDER BY (vscore + 0.5 * ftscore) DESC LIMIT 8",
        args,
    )
    if not rows:
        return []
    ranked = await sie.rerank(text, [(r["lesson_id"], f"{r['title']}. {r['rule']}") for r in rows], usage=usage)
    order = {lid: s for lid, s in ranked}
    rows.sort(key=lambda r: order.get(r["lesson_id"], 0.0), reverse=True)
    top = rows[:k]
    for r in top:
        r["rerank"] = round(order.get(r["lesson_id"], 0.0), 4)
    if top:
        await db().execute(
            "UPDATE lessons SET times_applied = times_applied + 1 WHERE JSON_ARRAY_CONTAINS_STRING(?, lesson_id)",
            [json.dumps([r["lesson_id"] for r in top])],
        )
    return top


async def list_lessons() -> list[dict]:
    return await db().rows(
        "SELECT lesson_id, title, rule, kind, guard, source_session, failure, introduced_in, created_at, times_applied FROM lessons ORDER BY created_at"
    )


# --------------------------------------------------------------------------------------
# Exactly-once money claims. The PRIMARY KEY on claim_key is the lock: two capybaras that
# race for the same refund both INSERT, SingleStore admits exactly one.
# --------------------------------------------------------------------------------------
@dataclass
class Claim:
    won: bool
    key: str
    holder: dict | None = None


async def claim(world: str, action: str, target: str, amount_cents: int, s: Any) -> Claim:
    key = f"{world}|{action}:{target}:{amount_cents}"
    try:
        await db().execute(
            "INSERT INTO money_claims (claim_key, session_id, capy_name, agent_version, action, target, amount_cents, status, created_at, updated_at, result) "
            "VALUES (?,?,?,?,?,?,?,'claimed',?,?,?)",
            [key, s.id, s.capy, s.version, action, target, amount_cents, now(), now(), {}],
        )
        return Claim(True, key)
    except DuplicateKey:
        holder = await db().one("SELECT session_id, capy_name, agent_version, status, created_at, updated_at, result FROM money_claims WHERE claim_key = ?", [key])
        if holder and holder.get("session_id") == s.id and holder.get("status") == "failed":
            await db().execute("UPDATE money_claims SET status = 'claimed', updated_at = ? WHERE claim_key = ?", [now(), key])
            return Claim(True, key)
        return Claim(False, key, holder)


async def settle(key: str, ok: bool, result: Any) -> None:
    if ok:
        await db().execute("UPDATE money_claims SET status = 'done', updated_at = ?, result = ? WHERE claim_key = ?", [now(), result, key])
    else:
        # A failed attempt releases the action so a later, honest retry can claim it again.
        await db().execute("UPDATE money_claims SET status = 'failed', updated_at = ?, result = ? WHERE claim_key = ?", [now(), result, key])


async def board(world: str, query: str = "") -> dict:
    like = f"%{query.strip()}%" if query.strip() else "%"
    claims = await db().rows(
        "SELECT claim_key, capy_name, agent_version, action, target, amount_cents, status, created_at FROM money_claims "
        "WHERE claim_key LIKE ? AND (target LIKE ? OR action LIKE ?) ORDER BY created_at DESC LIMIT 20",
        [f"{world}|%", like, like],
    )
    running = await db().rows(
        "SELECT session_id, capy_name, agent_version, task, scenario, status, updated_at FROM sessions WHERE status = 'running' "
        "AND updated_at > NOW(6) - INTERVAL 10 MINUTE ORDER BY updated_at DESC LIMIT 20"
    )
    return {"claims": claims, "capybaras_on_shift": running}
