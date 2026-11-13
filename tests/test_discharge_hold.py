"""Discharging in a house with a small base load: a running discharge at the
minimum power holds through a dip of the demand instead of switching off and on."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide


def _night(house_w: float, venus_ac: float = 0.0, state: str = "standby") -> Inputs:
    seen = -house_w + venus_ac  # the Venus counts as a house load in the surplus sensor
    return Inputs(
        surplus_mean=seen, surplus_instant=seen, surplus_ex_venus_mean=-house_w, venus_soc=60.0, venus_ac=venus_ac, venus_pv=0.0,
        venus_state=state, venus_capacity_kwh=5.12, primary_power=None, primary_soc=None,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )


P = Params(has_primary=False)
RUNNING = State(last_discharge_power=200)


def test_does_not_start_below_about_300_w():
    assert decide(_night(280), P, State()).target_mode == "stop"
    d = decide(_night(320), P, State())
    assert d.command == "discharge" and d.power == 200


def test_running_discharge_holds_through_a_dip():
    # the fridge switches off: 250 W would not start a discharge, but keeps one going
    for house in (250, 200, 170):
        d = decide(_night(house, venus_ac=200.0, state="discharging"), P, RUNNING)
        assert d.target_mode == "discharge" and d.command is None, house
        assert d.state.last_discharge_power == 200


def test_running_discharge_stops_when_the_house_needs_less_than_160_w():
    d = decide(_night(150, venus_ac=200.0, state="discharging"), P, RUNNING)
    assert d.command == "standby"


def test_higher_steps_still_come_down_before_they_export():
    # 400 W running, the house drops to 300 W: one step down per tick, no hold at 400
    d = decide(_night(300, venus_ac=400.0, state="discharging"), P, State(last_discharge_power=400))
    assert d.command == "discharge" and d.power < 400


def test_a_lower_minimum_serves_a_small_base_load():
    low = Params(has_primary=False, discharge_min_w=100)
    # 220 W of demand: nothing at the default minimum, 100 W at a minimum of 100 W
    assert decide(_night(220), P, State()).target_mode == "stop"
    d = decide(_night(220), low, State())
    assert d.command == "discharge" and d.power == 100
    # the hold follows the minimum: 40 W below it
    running = State(last_discharge_power=100)
    assert decide(_night(70, venus_ac=100.0, state="discharging"), low, running).target_mode == "discharge"
    assert decide(_night(50, venus_ac=100.0, state="discharging"), low, running).command == "standby"
