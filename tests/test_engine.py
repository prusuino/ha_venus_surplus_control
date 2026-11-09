"""The decision engine: readiness, mode mapping and the main paths of one
tick (charge, discharge, stop, protection, incomplete data)."""
from __future__ import annotations

from custom_components.venus_surplus.engine import (
    Inputs,
    Params,
    State,
    _floor_step,
    current_mode,
    data_ready,
    decide,
    state_from_dict,
    state_to_dict,
)


def _inputs(**over) -> Inputs:
    base = dict(
        surplus_mean=0.0, surplus_instant=0.0, surplus_ex_venus_mean=None, venus_soc=50.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=5.12, primary_power=0.0, primary_soc=95.0,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )
    base.update(over)
    return Inputs(**base)


def test_helpers():
    assert _floor_step(1234, 100) == 1200
    assert _floor_step(-5, 100) == 0
    assert current_mode("Charging") == "charge"
    assert current_mode("selling") == "discharge"
    assert current_mode("standby") == "stop"
    assert current_mode(None) == "stop"


def test_data_ready():
    p = Params()
    assert data_ready(_inputs(), p) is True
    assert data_ready(_inputs(venus_soc=None), p) is False
    assert data_ready(_inputs(venus_state="unavailable"), p) is False
    assert data_ready(_inputs(primary_soc=None), p) is False
    assert data_ready(_inputs(primary_soc=None, primary_power=None), Params(has_primary=False)) is True


def test_incomplete_data_sends_standby_after_two_bad_ticks():
    p = Params()
    first = decide(_inputs(venus_soc=None), p, State(last_charge_power=500))
    assert first.target_mode == "no_data" and first.command is None
    assert first.state.bad_data_count == 1 and first.state.last_charge_power == 500
    second = decide(_inputs(venus_soc=None), p, first.state)
    assert second.command == "standby" and second.state.last_charge_power == 0
    assert second.state.bad_data_count == 2


def test_charges_from_surplus_when_the_first_battery_is_full():
    p = Params()
    d = decide(_inputs(surplus_mean=1500.0, surplus_instant=1500.0, primary_soc=96.0, venus_state="standby"), p, State())
    assert d.target_mode == "charge" and d.reason == "charge_ok"
    assert d.command == "charge"
    assert d.power == 1200  # headroom 1300 W floored to 100 W steps, capped by the AC limit
    assert d.state.last_charge_power == 1200 and d.state.expected_mode() == "charge"
    assert d.values["headroom_w"] == 1300 and d.values["current_mode"] == "stop"
    # the same tick again while already charging at that power sends nothing new
    again = decide(_inputs(surplus_mean=1500.0, surplus_instant=1500.0, primary_soc=96.0, venus_state="charging"), p, d.state)
    assert again.target_mode == "charge" and again.command is None


def test_waits_while_the_first_battery_is_still_absorbing():
    p = Params()
    d = decide(_inputs(surplus_mean=900.0, surplus_instant=900.0, primary_soc=60.0, primary_power=-800.0), p, State())
    assert d.target_mode == "stop" and d.reason == "no_condition"
    assert d.command is None  # already stopped: nothing to send
    assert d.values["primary_charge_w"] == 800 and d.values["parallel_allowed"] is False


def test_discharges_at_night_when_the_first_battery_is_empty():
    p = Params()
    d = decide(_inputs(surplus_mean=-700.0, surplus_instant=-700.0, primary_soc=10.0, primary_power=0.0, venus_soc=60.0), p, State())
    assert d.target_mode == "discharge" and d.reason == "discharge_ok"
    assert d.command == "discharge"
    assert 200 <= d.power <= 600
    assert d.state.last_discharge_power == d.power


def test_venus_soc_protection_stops_a_running_discharge():
    p = Params()
    d = decide(_inputs(surplus_mean=-700.0, surplus_instant=-700.0, primary_soc=10.0, venus_soc=11.0, venus_state="discharging"), p, State(last_discharge_power=400))
    assert d.target_mode == "stop" and d.reason == "venus_soc_protect"
    assert d.command == "standby"
    assert d.state.last_discharge_power == 0


def test_cross_trip_stops_charging_fed_by_the_first_battery():
    p = Params()
    d = decide(_inputs(surplus_mean=1500.0, surplus_instant=1500.0, primary_soc=96.0, primary_power=700.0, venus_state="charging"), p, State(last_charge_power=1200))
    assert d.target_mode == "stop" and d.reason == "cross_trip"
    assert d.command == "standby"


def test_state_round_trip_ignores_unknown_keys():
    s = State(last_charge_power=300, rest_latched=True)
    d = state_to_dict(s)
    assert d["last_charge_power"] == 300
    assert state_from_dict({**d, "future_field": 1}) == s
    assert state_from_dict(None) == State()
