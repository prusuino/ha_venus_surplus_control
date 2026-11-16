"""While charging, a first battery that starts to discharge a little lowers
the charge command instead of stopping the Venus for a tick."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide


def _charging(**over) -> Inputs:
    # a good day ("Venus first"): both batteries charge in parallel, the
    # Venus at 1000 W; the averaged surplus is 1147 W
    base = dict(
        surplus_mean=147.0, surplus_instant=147.0, surplus_ex_venus_mean=1147.0, venus_soc=40.0, venus_ac=-1000.0, venus_pv=0.0,
        venus_state="charging", venus_capacity_kwh=5.12, primary_power=-300.0, primary_soc=26.0,
        forecast_today_kwh=100.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )
    base.update(over)
    return Inputs(**base)


def _state(**over) -> State:
    return State(**{**dict(last_charge_power=1000, last_charge_target=1000), **over})


def test_small_discharge_of_the_first_battery_lowers_the_command():
    # seen on a real system: the surplus fell, the first battery discharged 221 W into the Venus
    d = decide(_charging(primary_power=221.0), Params(), _state())
    assert d.target_mode == "charge" and d.reason == "charge_parallel"
    # 1147 - 200 reserve - (221 + 50) = 676 W
    assert d.command == "charge" and d.power == 600
    assert round(d.state.cross_trim_w) == 271


def test_the_command_comes_back_in_steps():
    p = Params()
    d = decide(_charging(primary_power=221.0), p, _state())
    powers = []
    for _ in range(8):
        d = decide(_charging(venus_ac=-float(d.state.last_charge_power), primary_power=-150.0), p, d.state)
        powers.append(d.state.last_charge_power)
    assert powers == sorted(powers) and powers[0] == 600 and powers[-1] == 800
    # 947 W of headroom: 900 W would need 950 W to step up
    assert d.state.cross_trim_w == 0


def test_discharge_that_stays_above_the_soft_limit_still_stops():
    p = Params()
    d = decide(_charging(primary_power=260.0), p, _state())
    assert d.target_mode == "charge"
    d = decide(_charging(primary_power=260.0), p, d.state)
    assert d.target_mode == "stop" and d.command == "standby"
    assert d.reason != "primary_first"


def test_large_discharge_stops_at_once():
    d = decide(_charging(primary_power=400.0), Params(), _state())
    assert d.target_mode == "stop" and d.command == "standby"
    assert d.reason != "primary_first"


def test_starting_is_as_strict_as_before():
    # from standby, a first battery that discharges more than 80 W keeps the Venus waiting
    d = decide(_charging(venus_state="standby", venus_ac=0.0, surplus_mean=1147.0, surplus_instant=1147.0, surplus_ex_venus_mean=None, primary_power=120.0), Params(), State())
    assert d.target_mode == "stop"


def test_nothing_is_held_back_without_a_discharge():
    d = decide(_charging(), Params(), _state())
    assert d.command is None and d.state.cross_trim_w == 0
