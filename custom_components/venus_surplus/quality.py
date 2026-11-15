"""How well the control runs: pure Python, no Home Assistant imports.

Two things are watched from tick to tick. How often the controller changes
between charging, discharging and standby: many changes in a short time
mean the surplus or the house demand sits right at a threshold. And whether
the Venus does what it was told: a standing command it follows only in part
(a device limit, a taper near full, a cold pack) or not at all.

Nothing here changes a decision; it is what the diagnostic sensor shows.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

WINDOW = timedelta(minutes=30)
MIN_TICKS = 10  # fewer ticks since the start: still collecting
OSCILLATION_CHANGES = 6  # mode changes within the window
FOLLOW_TICKS = 6  # ticks a standing command must have gone unanswered
NOT_RESPONDING_SHARE = 0.05
LIMITED_SHARE = 0.7
LIMITED_MIN_GAP_W = 100
NOISE_W = 40

# Why a Venus charges less than commanded. Its battery management cuts the
# charge current by cell temperature and state of charge: full current only
# between 20 and 40 °C, about half between 10 and 15 °C, less below; from
# 90 % it tapers, and at 100 % the current is zero. The limits are those of
# the Venus firmware as far as they are known; the power itself is not
# calculated here, only the reason is named.
COLD_BELOW_C = 20.0
WARM_FROM_C = 40.0
NEAR_FULL_SOC = 90.0

STATES = ["collecting", "stable", "oscillating", "limited", "limited_cold", "limited_warm", "limited_near_full", "not_responding", "paused"]


def limit_reason(mode: str | None, soc: float | None, cell_min: float | None, cell_max: float | None) -> str:
    """The state for a Venus that does clearly less than commanded."""
    if mode != "charge":
        return "limited"
    if soc is not None and soc >= NEAR_FULL_SOC:
        return "limited_near_full"
    if cell_min is not None and cell_min < COLD_BELOW_C:
        return "limited_cold"
    if cell_max is not None and cell_max >= WARM_FROM_C:
        return "limited_warm"
    return "limited"


class QualityTracker:
    """Fed once per tick and once per command."""

    def __init__(self) -> None:
        self._changes: deque[datetime] = deque()
        self._last_mode: str | None = None
        self._standing: tuple[str, int] | None = None
        self._ticks = 0
        self.zero_ticks = 0  # ticks in a row the Venus has not answered a standing command
        self.low_ticks = 0  # ticks in a row it has done clearly less than commanded
        self.follow_percent: int | None = None

    def command(self, now: datetime, mode: str) -> None:
        """A command was issued (or, in dry run, would have been)."""
        if mode == self._last_mode:
            return
        if self._last_mode is not None:
            self._changes.append(now)
        self._last_mode = mode

    def tick(self, now: datetime, mode: str, power: int, venus_ac: float | None, check_follow: bool) -> None:
        """`mode` and `power` are the command that stood since the last tick,
        `venus_ac` what the Venus does now (positive = delivering)."""
        self._ticks = min(MIN_TICKS, self._ticks + 1)
        while self._changes and now - self._changes[0] > WINDOW:
            self._changes.popleft()
        standing = (mode, int(power)) if mode in ("charge", "discharge") and power > 0 else None
        if not check_follow or standing is None or venus_ac is None or standing != self._standing:
            # a new command gets one tick to take effect
            self._standing = standing
            self.zero_ticks = self.low_ticks = 0
            self.follow_percent = None
            return
        actual = max(0.0, -venus_ac if mode == "charge" else venus_ac)
        self.follow_percent = round(100 * actual / power)
        answered = actual >= max(NOISE_W, NOT_RESPONDING_SHARE * power)
        self.zero_ticks = 0 if answered else min(1000, self.zero_ticks + 1)
        low = actual < LIMITED_SHARE * power and power - actual > LIMITED_MIN_GAP_W
        self.low_ticks = min(1000, self.low_ticks + 1) if low else 0

    @property
    def mode_changes(self) -> int:
        return len(self._changes)

    def state(self, paused: bool = False, soc: float | None = None, cell_min: float | None = None, cell_max: float | None = None) -> str:
        if paused:
            return "paused"
        if self._ticks < MIN_TICKS:
            return "collecting"
        if self.zero_ticks >= FOLLOW_TICKS:
            return "not_responding"
        if self.mode_changes >= OSCILLATION_CHANGES:
            return "oscillating"
        if self.low_ticks >= FOLLOW_TICKS:
            return limit_reason(self._standing[0] if self._standing else None, soc, cell_min, cell_max)
        return "stable"
