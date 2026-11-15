"""When is a surplus sensor silent for too long? Pure Python.

A value that stays in the state machine without being reported again looks
like a reading and is none: frozen at a large surplus or a large demand it
would keep the Venus charging from the grid or exporting. But sensors differ.
One reports every few seconds; another only when its value changes, and is
then silent for as long as the house draws the same. A fixed limit would
stop the Venus behind the second kind for no reason.

So the limit is learned per sensor: the gaps between its reports are
measured, a day at first without judging anything, and silence counts once
it lasts several times longer than this sensor has ever been silent.
"""
from __future__ import annotations

from datetime import datetime

MIN_LIMIT_S = 600.0  # never judged before 10 minutes
FACTOR = 3.0  # silence = this many times the longest gap seen
DAYS = 7  # daily maxima that are kept
OBSERVE_S = 86400.0  # running time before anything is judged


class SilenceWatch:
    """Fed once per tick with the time of the sensor's last report."""

    def __init__(self, data: dict | None = None) -> None:
        data = data if isinstance(data, dict) else {}
        self.entity: str | None = data.get("entity") if isinstance(data.get("entity"), str) else None
        self.days: list[float] = [float(v) for v in data.get("days") or [] if isinstance(v, (int, float))][-DAYS:]
        self.today: float = float(data.get("today") or 0.0)
        self.day: str | None = data.get("day") if isinstance(data.get("day"), str) else None
        self.observed_s: float = float(data.get("observed_s") or 0.0)
        self._last: float | None = None  # the last report seen in this run

    def to_dict(self) -> dict:
        return {"entity": self.entity, "days": [round(v) for v in self.days], "today": round(self.today), "day": self.day, "observed_s": round(self.observed_s)}

    @property
    def longest_gap_s(self) -> float:
        return max([*self.days, self.today], default=0.0)

    @property
    def limit_s(self) -> float:
        return max(MIN_LIMIT_S, FACTOR * self.longest_gap_s)

    @property
    def ready(self) -> bool:
        return self.observed_s >= OBSERVE_S

    def update(self, entity: str | None, reported: datetime | None, now: datetime, day: str, tick_s: float) -> bool:
        """Returns whether the sensor counts as silent now. `reported` is
        None while the sensor has no state at all (that is a missing input)."""
        if entity != self.entity:  # another sensor: start over
            self.__init__({"entity": entity})
        if day != self.day:
            if self.day is not None:
                self.days = (self.days + [self.today])[-DAYS:]
                self.today = 0.0
            self.day = day
        if reported is None:
            self._last = None
            return False
        ts = reported.timestamp()
        if self._last is not None and ts > self._last:
            gap = ts - self._last
            # A silence that was judged is not taken at its full length: a
            # real outage of hours would switch the check off for a week. It
            # still raises the limit by half, so that a sensor whose normal
            # gaps were underestimated is left alone after a few of them.
            learned = gap if (not self.ready or gap < self.limit_s) else self.limit_s / 2
            self.today = max(self.today, learned)
        self._last = ts
        self.observed_s = min(OBSERVE_S, self.observed_s + tick_s)
        return self.ready and now.timestamp() - ts >= self.limit_s
