"""Amplitude Agent Analytics for CapyTeam.

Every capybara shift is an Amplitude agent session:
  [Agent] User Message / AI Response / Tool Call on each turn,
  agent_version + Statsig experiment variant on every event,
  drill verdicts and exact checks as [Agent] Score events,
  and an explicit [Agent] Session End so Amplitude scores the session right away.
Night school reads the same sessions back (export API when a secret key is set).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from .config import settings

log = logging.getLogger("capyteam.analytics")

AGENT_ID = "capyteam-bookkeeper"
PROVIDER = "superlinked-sie"


class Analytics:
    def __init__(self) -> None:
        self._ai = None
        self._lock = threading.Lock()
        self.enabled = settings.amplitude_enabled
        self.sent = 0

    def ai(self):
        if not self.enabled:
            return None
        with self._lock:
            if self._ai is None:
                try:
                    from amplitude_ai import AIConfig, AmplitudeAI

                    self._ai = AmplitudeAI(api_key=settings.amplitude_api_key, config=AIConfig(redact_pii=True))
                except Exception as e:  # noqa: BLE001
                    log.warning("Amplitude disabled: %s", e)
                    self.enabled = False
                    return None
            return self._ai

    def _bound(self, s: Any):
        ai = self.ai()
        if ai is None:
            return None
        if getattr(s, "_amp", None) is None:
            experiments = [{"key": settings.statsig_experiment, "variant": s.variant, "provider": s.flag_provider, "unit": "agent_session"}]
            s._amp = ai.agent(
                AGENT_ID,
                user_id=s.owner_id,
                agent_version=s.version,
                env=s.mode,
                description="CapyTeam back-office agent for Maya's Mug Studio (refunds, invoices, bookkeeping)",
                context={"capy": s.capy, "scenario": s.scenario or "", "world": s.world_id, "source": s.source},
                experiments=experiments,
            )
        return s._amp

    def _safe(self, fn, *args, **kwargs):
        try:
            out = fn(*args, **kwargs)
            self.sent += 1
            return out
        except Exception as e:  # noqa: BLE001 - analytics must never break a shift
            log.warning("amplitude call failed: %s", e)
            return None

    def user_message(self, s: Any, content: str, turn: int) -> str | None:
        a = self._bound(s)
        if a is None:
            return None
        return self._safe(a.track_user_message, content=content, session_id=s.id, turn_id=turn, idle_timeout_minutes=240)

    def ai_message(self, s: Any, content: str, turn: int, *, model: str, latency_ms: float, input_tokens: int,
                   output_tokens: int, cost_usd: float, tool_calls: list | None = None, finish_reason: str | None = None,
                   system_prompt: str | None = None, is_error: bool = False, error_message: str | None = None) -> str | None:
        a = self._bound(s)
        if a is None:
            return None
        return self._safe(
            a.track_ai_message, content=content, session_id=s.id, turn_id=turn, model=model, provider=PROVIDER,
            latency_ms=latency_ms, input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens, total_cost_usd=cost_usd, auto_calculate_cost=False,
            finish_reason=finish_reason, tool_calls=tool_calls, system_prompt=system_prompt, is_error=is_error,
            error_message=error_message, model_tier="small-open",
        )

    def tool_call(self, s: Any, turn: int, *, name: str, args: dict, output: Any, ok: bool, latency_ms: float,
                  owner: str, error: str | None = None) -> None:
        a = self._bound(s)
        if a is None:
            return
        self._safe(a.track_tool_call, tool_name=name, tool_type="function", tool_owner=owner, latency_ms=latency_ms,
                   success=ok, session_id=s.id, turn_id=turn, input=args, output=output, error_message=error)

    def score(self, s: Any, name: str, value: float, *, source: str = "ai", comment: str | None = None) -> None:
        a = self._bound(s)
        if a is None:
            return
        self._safe(a.score, name=name, value=value, target_id=s.id, target_type="session", source=source,
                   comment=comment, session_id=s.id)

    def end(self, s: Any) -> None:
        a = self._bound(s)
        if a is None:
            return
        self._safe(a.track_session_end, session_id=s.id)

    def flush(self) -> None:
        ai = self._ai
        if ai is not None:
            try:
                ai.flush()
            except Exception as e:  # noqa: BLE001
                log.warning("amplitude flush failed: %s", e)


analytics = Analytics()
