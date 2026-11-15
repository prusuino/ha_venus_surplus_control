"""Discharging into a small house load: the Venus starts at a demand it can
serve, follows it in 50 W steps, leaves a reserve that fits the demand, and
does not switch off and on with every dip."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide


def _night(house_w: float, venus_ac: float = 0.0, state: str = "standby", **over) -> Inputs:
    seen = -house_w + venus_ac  # the Venus counts as a house load in the surplus sensor
    base = dict(
        surplus_mean=seen, surplus_instant=seen, surplus_ex_venus_mean=-house_w, venus_soc=60.0, venus_ac=venus_ac, venus_pv=0.0,
        venus_state=state, venus_capacity_kwh=5.12, primary_power=None, primary_soc=None,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )
    base.update(over)
    return Inputs(**base)


P = Params(has_primary=False, discharge_min_w=100)


def test_a_house_drawing_220_w_is_served():
    # the reserve follows the demand (20 %, at least 40 W) instead of a flat 120 W
    d = decide(_night(220), P, State())
    assert d.command == "discharge" and d.power == 150
    assert d.values["discharge_reserve_w"] == 44


def test_does_not_start_for_a_trickle():
    assert decide(_night(100), P, State()).target_mode == "stop"


def test_follows_the_demand_in_50_w_steps():
    running = State(last_discharge_power=150)
    d = decide(_night(360, venus_ac=150.0, state="discharging"), P, running)  # the freezer switches on
    assert d.command == "discharge" and d.power == 200  # one step per tick
    d = decide(_night(360, venus_ac=200.0, state="discharging"), P, d.state)
    assert d.power == 250


def test_never_commands_more_than_the_house_needs():
    for house in (130, 180, 220, 260, 350, 480, 700, 950):
        d = decide(_night(house), P, State())
        assert d.command == "discharge" and d.power <= house - 30, house


def test_a_large_demand_keeps_the_full_reserve():
    d = decide(_night(900), P, State())
    assert d.values["discharge_reserve_w"] == 120


def test_running_discharge_holds_through_a_dip():
    running = State(last_discharge_power=100)
    for house in (110, 90, 70):
        d = decide(_night(house, venus_ac=100.0, state="discharging"), P, running)
        assert d.target_mode == "discharge" and d.command is None, house
    assert decide(_night(50, venus_ac=100.0, state="discharging"), P, running).command == "standby"


def test_a_minimum_set_by_hand_still_applies():
    p200 = Params(has_primary=False, discharge_min_w=200)
    assert decide(_night(220), p200, State()).target_mode == "stop"
    d = decide(_night(300), p200, State())
    assert d.command == "discharge" and d.power >= 200


# ---- a first battery that delivers nothing ---------------------------------

WITH_FIRST = Params(has_primary=True, discharge_min_w=100)


def _paused(house_w: float, **over) -> Inputs:
    return _night(house_w, primary_power=0.0, primary_soc=35.0, **over)


def test_a_paused_first_battery_lets_the_venus_take_over_after_three_minutes():
    state = State()
    for n in range(5):
        d = decide(_paused(240), WITH_FIRST, state)
        assert d.target_mode == "stop", n  # it might just be between two readings
        state = d.state
    d = decide(_paused(240), WITH_FIRST, state)
    assert d.command == "discharge" and d.reason == "discharge_primary_idle"


def test_a_first_battery_that_delivers_keeps_its_turn():
    state = State()
    for _ in range(10):
        d = decide(_night(240, primary_power=230.0, primary_soc=35.0), WITH_FIRST, state)
        state = d.state
    assert d.target_mode == "stop"  # it covers the house itself


def test_no_takeover_while_the_sun_still_covers_the_house():
    state = State()
    for _ in range(10):
        d = decide(_night(0, primary_power=0.0, primary_soc=35.0, surplus_mean=300.0, surplus_instant=300.0, surplus_ex_venus_mean=300.0), WITH_FIRST, state)
        state = d.state
    assert d.target_mode != "discharge"


def _demand(need: float) -> Inputs:
    """The house imports `need` W, no first battery in the way."""
    return Inputs(
        surplus_mean=-need, surplus_instant=-need, surplus_ex_venus_mean=None, venus_soc=60.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="discharging", venus_capacity_kwh=5.12, primary_power=None, primary_soc=None,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )


def _climb(up_step: int, need: float, ticks: int) -> list[int]:
    params = Params(has_primary=False, discharge_min_w=100, discharge_up_step_w=up_step)
    state = State(last_discharge_power=400)
    seen = []
    for _ in range(ticks):
        d = decide(_demand(need), params, state)
        state = d.state
        seen.append(state.last_discharge_power)
    return seen


def test_discharge_climbs_as_fast_as_the_reaction_allows():
    assert _climb(50, 1800, 4) == [450, 500, 550, 600]  # calm: as before
    assert _climb(100, 1800, 4) == [500, 600, 700, 800]
    assert _climb(200, 1800, 4) == [600, 800, 1000, 1000]  # and stops at the limit


def test_a_fast_climb_does_not_overshoot_the_demand():
    # 520 W of demand: 480 W after the reserve of 104 W ... the power settles where the slow climb settles
    slow = _climb(50, 620, 12)
    fast = _climb(200, 620, 12)
    assert fast[-1] == slow[-1]
    assert max(fast) == fast[-1]  # never above where it ends
    assert fast.index(fast[-1]) < slow.index(slow[-1])  # but there sooner
