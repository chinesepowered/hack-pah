"""Statsig decides which agent version each new shift runs.

Night school ships a new version as an *experiment*: Statsig splits sessions between the
shipped version (Control) and the candidate (Test). Amplitude Agent Analytics compares the
arms, and the winner becomes the new shipped version.

If the Statsig experiment has not been created yet, CapyTeam falls back to a deterministic
hash split and labels the provider accordingly, so no data is mislabeled as Statsig's.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import threading
from dataclasses import dataclass

from .config import settings

log = logging.getLogger("capyteam.flags")


@dataclass
class Assignment:
    version: str
    variant: str
    provider: str


class Flags:
    def __init__(self) -> None:
        self._ready = False
        self._ok = False
        self._lock = threading.Lock()

    def _init(self) -> bool:
        with self._lock:
            if self._ready:
                return self._ok
            self._ready = True
            if not settings.statsig_server_secret:
                return False
            try:
                from statsig import statsig
                from statsig.statsig_options import StatsigOptions

                statsig.initialize(settings.statsig_server_secret, StatsigOptions(tier="production", init_timeout=8))
                self._ok = True
                atexit.register(self.shutdown)  # scripts exit right after their last shift: send queued events first
            except Exception as e:  # noqa: BLE001
                log.warning("Statsig unavailable: %s", e)
                self._ok = False
            return self._ok

    @staticmethod
    def _user(unit_id: str):
        from statsig import StatsigUser

        return StatsigUser(user_id=unit_id, custom_ids={"agent_session": unit_id})

    def statsig_assignment(self, unit_id: str, log_exposure: bool = True) -> tuple[str, bool | None] | None:
        """(group, use_candidate) from the release experiment, or None when Statsig isn't serving it."""
        if not self._init():
            return None
        try:
            from statsig import statsig

            get = statsig.get_experiment if log_exposure else statsig.get_experiment_with_exposure_logging_disabled
            exp = get(self._user(unit_id), settings.statsig_experiment)
            group = exp.get_group_name() if hasattr(exp, "get_group_name") else getattr(exp, "group_name", None)
            if not group:
                return None
            use_candidate = exp.get("use_candidate", None)
            return group, (bool(use_candidate) if use_candidate is not None else None)
        except Exception as e:  # noqa: BLE001
            log.warning("Statsig get_experiment failed: %s", e)
            return None

    def statsig_group(self, unit_id: str, log_exposure: bool = True) -> str | None:
        a = self.statsig_assignment(unit_id, log_exposure)
        return a[0] if a else None

    def log_shift(self, unit_id: str, *, done: bool, version: str, variant: str, provider: str, scenario: str | None,
                  cost_usd: float, ended_ms: int | None = None) -> None:
        """Each shift's outcome as a Statsig event (capyteam_shift_done / capyteam_shift_failed), for the experiment's metrics."""
        if not self._init():
            return
        try:
            from statsig import StatsigEvent, statsig

            extra = {"_time": ended_ms} if ended_ms else {}
            statsig.log_event(StatsigEvent(self._user(unit_id), "capyteam_shift_done" if done else "capyteam_shift_failed",
                                           value=round(float(cost_usd or 0), 6),
                                           metadata={"agent_version": version, "variant": variant, "provider": provider,
                                                     "scenario": scenario or ""}, **extra))
        except Exception as e:  # noqa: BLE001 - analytics must never break a shift
            log.warning("Statsig log_event failed: %s", e)

    def assign(self, unit_id: str, shipped: str, candidate: str | None) -> Assignment:
        if settings.agent_version:
            return Assignment(settings.agent_version, "pinned", "pinned")
        if not candidate or candidate == shipped:
            return Assignment(shipped, "shipped", "none")
        a = self.statsig_assignment(unit_id)
        if a:
            group, use_candidate = a
            name = group.strip().lower()
            if name in ("control", "default"):        # Control always runs the shipped version
                is_test = False
            elif name in ("test", "treatment", "candidate", "variant"):  # Test always runs night school's candidate
                is_test = True
            else:                                      # custom group names: the use_candidate parameter decides
                is_test = use_candidate if use_candidate is not None else True
            return Assignment(candidate if is_test else shipped, group, "statsig")
        h = int(hashlib.sha256(unit_id.encode()).hexdigest(), 16) % 2
        return Assignment(candidate if h else shipped, "Test" if h else "Control", "capyteam-hash")

    def shutdown(self) -> None:
        if self._ok:
            self._ok = False
            try:
                from statsig import statsig

                statsig.shutdown()
            except Exception:  # noqa: BLE001
                pass


flags = Flags()
