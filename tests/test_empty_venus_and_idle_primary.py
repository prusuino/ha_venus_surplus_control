"""An empty Venus must still charge (the SoC protection only blocks
discharging), and a first battery that takes nothing leaves the surplus to
the Venus."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide


def _inputs(**over) -> Inputs:
    base = dict(
        surplus_mean=0.0, surplus_instant=0.0, surplus_ex_venus_mean=None, venus_soc=50.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=5.12, primary_power=0.0, primary_soc=95.0,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )
    base.update(over)
    return Inputs(**base)


def test_empty_venus_charges_from_surplus():
    d = decide(_inputs(surplus_mean=1500.0, surplus_instant=1500.0, primary_soc=96.0, venus_soc=11.0), Params(), State())
    assert d.target_mode == "charge" and d.reason == "charge_ok"
    assert d.command == "charge" and d.power == 1200


def test_empty_venus_without_first_battery_charges():
    d = decide(_inputs(surplus_mean=900.0, surplus_instant=900.0, primary_soc=None, primary_power=None, venus_soc=5.0), Params(has_primary=False), State())
    assert d.target_mode == "charge" and d.command == "charge"


def test_empty_venus_without_surplus_still_reports_the_protection():
    d = decide(_inputs(surplus_mean=-700.0, surplus_instant=-700.0, primary_soc=10.0, venus_soc=12.0), Params(), State())
    assert d.target_mode == "stop" and d.reason == "venus_soc_protect"


def _idle(**over) -> Inputs:
    # the case of issue #2: 510 W surplus, first battery at 4 % and in standby
    return _inputs(**{**dict(surplus_mean=510.0, surplus_instant=510.0, primary_soc=4.0, primary_power=0.0, venus_soc=40.0), **over})


def test_idle_first_battery_needs_confirmation():
    p = Params(charge_reserve_w=0)
    s = State()
    for tick in range(1, 6):
        d = decide(_idle(), p, s)
        s = d.state
        assert d.target_mode == "stop" and s.primary_idle_count == tick
    d = decide(_idle(), p, s)
    assert d.target_mode == "charge" and d.reason == "charge_primary_idle"
    assert d.command == "charge" and d.power == 500


def test_idle_charge_holds_while_the_first_battery_stays_idle():
    p = Params(charge_reserve_w=0)
    d = decide(_idle(venus_state="charging", venus_ac=-500.0, surplus_ex_venus_mean=510.0), p, State(last_charge_power=500, last_charge_target=500, primary_idle_count=6))
    assert d.target_mode == "charge" and d.command is None


def test_first_battery_charging_again_ends_the_idle_charge():
    p = Params(charge_reserve_w=0)
    d = decide(_idle(venus_state="charging", venus_ac=-500.0, surplus_ex_venus_mean=510.0, primary_power=-300.0), p, State(last_charge_power=500, last_charge_target=500, primary_idle_count=10))
    assert d.state.primary_idle_count == 0
    assert d.target_mode == "stop" and d.command == "standby"


def test_first_battery_taking_the_surplus_is_not_idle():
    p = Params(charge_reserve_w=0)
    s = State()
    for _ in range(8):
        d = decide(_idle(primary_power=-450.0), p, s)
        s = d.state
    assert d.target_mode == "stop" and s.primary_idle_count == 0
