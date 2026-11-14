"""A Venus at 100 % that takes nothing is full: no charge command, and it
comes back only once the SoC has dropped (issue #3)."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide, state_from_dict, state_to_dict


def _inputs(**over) -> Inputs:
    base = dict(
        surplus_mean=1500.0, surplus_instant=1500.0, surplus_ex_venus_mean=None, venus_soc=100.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="charging", venus_capacity_kwh=5.12, primary_power=0.0, primary_soc=96.0,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )
    base.update(over)
    return Inputs(**base)


def _run(state: State, ticks: int, **over):
    d = None
    for _ in range(ticks):
        d = decide(_inputs(**over), Params(), state)
        state = d.state
    return d


def test_full_venus_goes_to_standby_after_confirmation():
    state = State(last_charge_power=1000, last_charge_target=1000)
    d = _run(state, 3)
    assert d.target_mode == "charge" and d.reason == "charge_ok"  # not yet: three ticks
    d = decide(_inputs(), Params(), d.state)
    assert d.target_mode == "stop" and d.reason == "venus_full" and d.command == "standby"
    assert d.values["venus_full"] is True


def test_venus_still_taking_power_at_100_keeps_charging():
    state = State(last_charge_power=1000, last_charge_target=1000)
    d = _run(state, 8, venus_ac=-300.0)
    assert d.target_mode == "charge" and d.state.full_latched is False


def test_full_latch_holds_until_below_resume():
    d = _run(State(), 4, venus_state="standby")
    assert d.reason == "venus_full"
    d = decide(_inputs(venus_soc=99.0, venus_state="standby"), Params(), d.state)
    assert d.target_mode == "stop" and d.reason == "venus_full" and d.command is None
    d = decide(_inputs(venus_soc=97.9, venus_state="standby"), Params(), d.state)
    assert d.target_mode == "charge" and d.command == "charge"


def test_full_venus_still_discharges_for_the_house():
    d = _run(State(), 4, venus_state="standby")
    assert d.state.full_latched
    d = decide(_inputs(surplus_mean=-800.0, surplus_instant=-800.0, primary_soc=10.0, venus_state="standby"), Params(), d.state)
    assert d.target_mode == "discharge"


def test_full_without_surplus_is_not_reported_as_full():
    d = _run(State(), 5, surplus_mean=0.0, surplus_instant=0.0, venus_state="standby")
    assert d.target_mode == "stop" and d.reason == "no_condition"


def test_latch_survives_a_restart():
    d = _run(State(), 4, venus_state="standby")
    restored = state_from_dict(state_to_dict(d.state))
    assert restored.full_latched is True
    assert state_from_dict({"last_charge_power": 0}).full_latched is False
