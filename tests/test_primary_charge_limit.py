"""A first battery that charges at its limit while more surplus stands than
it takes leaves the rest to the Venus, and only the rest."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide


def _inputs(**over) -> Inputs:
    # 3000 W surplus (PV minus house), the first battery at 40 % takes 2000 W
    base = dict(
        surplus_mean=3000.0, surplus_instant=3000.0, surplus_ex_venus_mean=None, venus_soc=50.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=5.12, primary_power=-2000.0, primary_soc=40.0,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )
    base.update(over)
    return Inputs(**base)


def _charging(**over) -> Inputs:
    return _inputs(**{**dict(venus_state="charging", venus_ac=-800.0, surplus_ex_venus_mean=3000.0), **over})


LATCHED = dict(last_charge_power=800, last_charge_target=800, primary_limit_count=6, primary_limit_ref=2000.0)


def test_steady_first_battery_with_surplus_left_is_at_its_limit():
    p, s = Params(), State()
    for _ in range(6):
        d = decide(_inputs(), p, s)
        s = d.state
        assert d.target_mode == "stop" and d.reason == "primary_first"
    d = decide(_inputs(), p, s)
    assert d.target_mode == "charge" and d.reason == "charge_primary_limited"
    # 3000 W surplus - 2000 W into the first battery - 200 W reserve
    assert d.command == "charge" and d.power == 800


def test_small_wobble_of_the_first_battery_still_counts_as_steady():
    p, s = Params(), State()
    for power in (-2000.0, -1960.0, -2040.0, -1990.0, -2030.0, -1970.0, -2010.0):
        d = decide(_inputs(primary_power=power), p, s)
        s = d.state
    assert d.reason == "charge_primary_limited"


def test_first_battery_still_ramping_up_is_not_at_its_limit():
    p, s = Params(), State()
    for power in (-500.0, -800.0, -1100.0, -1400.0, -1700.0, -2000.0, -2300.0, -2600.0):
        d = decide(_inputs(primary_power=power), p, s)
        s = d.state
        assert d.target_mode == "stop"


def test_first_battery_taking_all_the_surplus_is_not_at_its_limit():
    p, s = Params(), State()
    for _ in range(10):
        d = decide(_inputs(surplus_mean=1100.0, surplus_instant=1100.0, primary_power=-1100.0), p, s)
        s = d.state
    assert d.target_mode == "stop" and d.reason != "charge_primary_limited"
    assert s.primary_limit_count == 0


def test_too_little_left_does_not_start_the_venus():
    p, s = Params(), State()
    for _ in range(10):
        d = decide(_inputs(surplus_mean=2500.0, surplus_instant=2500.0), p, s)  # 300 W left
        s = d.state
    assert d.target_mode == "stop"


def test_limit_charge_holds_while_the_first_battery_stays_at_its_limit():
    d = decide(_charging(), Params(), State(**LATCHED))
    assert d.target_mode == "charge" and d.reason == "charge_primary_limited" and d.command is None


def test_limit_charge_follows_the_rest_up():
    d = decide(_charging(surplus_mean=3400.0, surplus_instant=3400.0, surplus_ex_venus_mean=3400.0), Params(), State(**LATCHED))
    assert d.command == "charge" and d.power == 1200


def test_first_battery_getting_less_ends_the_limit_charge():
    # the sun fades: the first battery gets less than before, so it is no
    # longer at a limit and must go first again
    d = decide(_charging(surplus_mean=2500.0, surplus_instant=2500.0, surplus_ex_venus_mean=2500.0, primary_power=-1700.0), Params(), State(**LATCHED))
    assert d.state.primary_limit_count == 0
    assert d.target_mode == "stop" and d.command == "standby"


def test_first_battery_taking_more_ends_the_limit_charge():
    d = decide(_charging(primary_power=-2400.0), Params(), State(**LATCHED))
    assert d.state.primary_limit_count == 0
    assert d.target_mode == "stop" and d.command == "standby"


def test_full_first_battery_still_gives_the_venus_the_whole_headroom():
    d = decide(_inputs(primary_soc=96.0, primary_power=-300.0, surplus_mean=1500.0, surplus_instant=1500.0), Params(), State())
    assert d.reason == "charge_ok" and d.power == 1200
