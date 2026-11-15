"""Control quality: mode changes within the window, and a Venus that does
less than commanded or nothing at all."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.venus_surplus.quality import FOLLOW_TICKS, MIN_TICKS, OSCILLATION_CHANGES, WINDOW, QualityTracker, limit_reason

T0 = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
TICK = timedelta(seconds=30)


def _warm(q: QualityTracker, now: datetime = T0) -> datetime:
    for _ in range(MIN_TICKS):
        q.tick(now, "standby", 0, 0.0, True)
        now += TICK
    return now


def test_collecting_until_enough_ticks_then_stable():
    q = QualityTracker()
    for n in range(MIN_TICKS - 1):
        q.tick(T0 + n * TICK, "standby", 0, 0.0, True)
        assert q.state() == "collecting"
    q.tick(T0 + MIN_TICKS * TICK, "standby", 0, 0.0, True)
    assert q.state() == "stable"
    assert q.state(paused=True) == "paused"


def test_frequent_mode_changes_are_oscillating_and_age_out():
    q = QualityTracker()
    now = _warm(q)
    modes = ["charge", "standby"] * 4
    for mode in modes[: OSCILLATION_CHANGES]:  # the first command is no change yet
        q.command(now, mode)
        now += TICK
    assert q.mode_changes == OSCILLATION_CHANGES - 1 and q.state() == "stable"
    q.command(now, modes[OSCILLATION_CHANGES])
    q.command(now, modes[OSCILLATION_CHANGES])  # the same command again is no change
    assert q.mode_changes == OSCILLATION_CHANGES and q.state() == "oscillating"
    q.tick(now + WINDOW + TICK, "standby", 0, 0.0, True)
    assert q.mode_changes == 0 and q.state() == "stable"


def test_venus_that_takes_nothing_is_not_responding():
    q = QualityTracker()
    now = _warm(q)
    for n in range(FOLLOW_TICKS + 1):  # the first tick of a command is not judged
        assert q.state() == "stable"
        q.tick(now, "charge", 1000, 0.0, True)
        now += TICK
    assert q.state() == "not_responding" and q.follow_percent == 0
    q.tick(now, "charge", 1000, -950.0, True)
    assert q.state() == "stable" and q.follow_percent == 95


def test_venus_that_does_clearly_less_is_limited():
    q = QualityTracker()
    now = _warm(q)
    for _ in range(FOLLOW_TICKS + 1):
        q.tick(now, "discharge", 1500, 800.0, True)
        now += TICK
    assert q.state() == "limited" and q.follow_percent == 53
    # a small gap is not worth a word: 150 of 200 W
    q2 = QualityTracker()
    now = _warm(q2)
    for _ in range(FOLLOW_TICKS + 3):
        q2.tick(now, "discharge", 200, 150.0, True)
        now += TICK
    assert q2.state() == "stable"


def test_limited_charge_names_its_reason():
    q = QualityTracker()
    now = _warm(q)
    for _ in range(FOLLOW_TICKS + 1):
        q.tick(now, "charge", 1200, -800.0, True)  # a cold Venus A: 20 A instead of the command
        now += TICK
    assert q.state() == "limited"  # nothing known
    assert q.state(soc=23, cell_min=9.8, cell_max=10.4) == "limited_cold"
    assert q.state(soc=23, cell_min=25, cell_max=41) == "limited_warm"
    assert q.state(soc=93, cell_min=9.8, cell_max=10.4) == "limited_near_full"
    assert q.state(soc=50, cell_min=25, cell_max=27) == "limited"  # neither: a limit of the device
    assert q.state(soc=50) == "limited"  # no cell temperatures
    # only a limited charge gets a reason; discharging has other limits
    assert limit_reason("discharge", 50, 5, 6) == "limited"
    # and a Venus that follows is stable, however cold it is
    q.tick(now, "charge", 1200, -1150.0, True)
    assert q.state(soc=23, cell_min=5, cell_max=6) == "stable"


def test_a_new_command_starts_the_count_again():
    q = QualityTracker()
    now = _warm(q)
    for n in range(FOLLOW_TICKS * 3):
        q.tick(now, "charge", 1000 + 100 * (n % 2), 0.0, True)  # the command changes every tick
        now += TICK
    assert q.zero_ticks == 0 and q.state() == "stable"


def test_dry_run_does_not_judge_the_venus():
    q = QualityTracker()
    now = _warm(q)
    for _ in range(FOLLOW_TICKS * 2):
        q.tick(now, "charge", 1000, 0.0, False)
        now += TICK
    assert q.state() == "stable" and q.follow_percent is None
