"""Statsig decides which agent version each new shift runs.

Night school ships a new version as an *experiment*: Statsig splits sessions between the
shipped version (Control) and the candidate (Test). Amplitude Agent Analytics compares the
arms, and the winner becomes the new shipped version.

If the Statsig experiment has not been created yet, CapyTeam falls back to a deterministic
hash split and labels the provider accordingly, so no data is mislabeled as Statsig's.
"""

from __future__ import annotations

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
            except Exception as e:  # noqa: BLE001
                log.warning("Statsig unavailable: %s", e)
                self._ok = False
            return self._ok

    def statsig_group(self, unit_id: str, log_exposure: bool = True) -> str | None:
        if not self._init():
            return None
        try:
            from statsig import StatsigUser, statsig

            user = StatsigUser(user_id=unit_id, custom_ids={"agent_session": unit_id})
            get = statsig.get_experiment if log_exposure else statsig.get_experiment_with_exposure_logging_disabled
            exp = get(user, settings.statsig_experiment)
            group = exp.get_group_name() if hasattr(exp, "get_group_name") else getattr(exp, "group_name", None)
            return group or None
        except Exception as e:  # noqa: BLE001
            log.warning("Statsig get_experiment failed: %s", e)
            return None

    def assign(self, unit_id: str, shipped: str, candidate: str | None) -> Assignment:
        if settings.agent_version:
            return Assignment(settings.agent_version, "pinned", "pinned")
        if not candidate or candidate == shipped:
            return Assignment(shipped, "shipped", "none")
        group = self.statsig_group(unit_id)
        if group:
            is_test = group.lower() not in ("control", "default")
            return Assignment(candidate if is_test else shipped, group, "statsig")
        h = int(hashlib.sha256(unit_id.encode()).hexdigest(), 16) % 2
        return Assignment(candidate if h else shipped, "Test" if h else "Control", "capyteam-hash")

    def shutdown(self) -> None:
        if self._ok:
            try:
                from statsig import statsig

                statsig.shutdown()
            except Exception:  # noqa: BLE001
                pass


flags = Flags()
