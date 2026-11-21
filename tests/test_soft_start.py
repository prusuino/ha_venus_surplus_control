"""Next to a first battery that is still charging, the Venus takes over step
by step instead of jumping to the whole surplus: that surplus is what the
first battery takes at this moment, and it needs time to give way."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide

SURPLUS = 1250.0  # PV minus house
PRIMARY_MAX = 1060.0  # what the first battery charges with when it gets all of it


def _tick(venus_charge: float, primary_charge: float, state: State, params: Params, soc: float = 5.0):
    """One tick of a plant with a first battery that charges `primary_charge`
    while the Venus charges `venus_charge`."""
    return decide(
        Inputs(
            surplus_mean=SURPLUS - venus_charge, surplus_instant=SURPLUS - venus_charge, surplus_ex_venus_mean=SURPLUS,
            venus_soc=14.0, venus_ac=-venus_charge, venus_pv=0.0,
            venus_state="charging" if venus_charge > 0 else "standby", venus_capacity_kwh=5.12,
            primary_power=-primary_charge, primary_soc=soc,
            forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
        ),
        params, state,
    )


def _low_threshold() -> Params:
    # "Venus charges from first battery SoC" set to 5 %
    return Params(soc_min_charge_start=5, soc_min_charge_hold=0)


def test_start_next_to_a_charging_first_battery_is_small():
    d = _tick(0.0, PRIMARY_MAX, State(), _low_threshold())
    assert d.target_mode == "charge" and d.reason == "charge_ok"
    assert d.command == "charge" and d.power == 200
    assert d.values["charge_soft_start"] is True


def test_charge_power_climbs_step_by_step_while_the_first_battery_gives_way():
    p, s = _low_threshold(), State()
    venus, powers = 0.0, []
    for _ in range(12):
        # the first battery follows the meter: it takes what the Venus leaves
        d = _tick(venus, min(PRIMARY_MAX, SURPLUS - venus), s, p)
        s = d.state
        assert d.target_mode == "charge", (powers, d.reason)
        if d.command == "charge":
            assert d.power - venus <= 200
            venus = float(d.power)
        powers.append(int(venus))
    assert powers[:5] == [200, 400, 600, 800, 1000]
    assert powers[-1] == 1000  # 1250 W surplus less the 200 W reserve, in 100 W steps


def test_a_first_battery_that_lags_a_tick_does_not_stop_the_charge():
    p, s = _low_threshold(), State()
    venus, before, powers = 0.0, 0.0, []
    for _ in range(40):
        # it still charges with what was right a tick ago: the difference comes from the grid
        d = _tick(venus, min(PRIMARY_MAX, SURPLUS - before), s, p)
        s = d.state
        assert d.target_mode == "charge", (powers, d.reason)
        before = venus
        if d.command == "charge":
            venus = float(d.power)
        powers.append(int(venus))
    assert max(powers) >= 900 and powers[-1] >= 800


def test_without_the_soft_start_the_same_plant_gets_the_whole_surplus_at_once():
    # the reference: this jump is what made the two batteries fight
    d = _tick(0.0, PRIMARY_MAX, State(), Params(soc_min_charge_start=5, soc_min_charge_hold=0, charge_soft_rise_w=5000))
    assert d.command == "charge" and d.power == 1000


def test_a_first_battery_that_takes_nothing_leaves_the_jump_as_it_was():
    d = _tick(0.0, 0.0, State(), Params(), soc=96.0)
    assert d.command == "charge" and d.power == 1000
    assert d.values["charge_soft_start"] is False


def test_what_the_first_battery_leaves_is_taken_at_once():
    # 3000 W surplus, the first battery at 90 % takes 1000 W: 1800 W are free
    d = decide(
        Inputs(
            surplus_mean=3000.0, surplus_instant=3000.0, surplus_ex_venus_mean=None, venus_soc=50.0, venus_ac=0.0, venus_pv=0.0,
            venus_state="standby", venus_capacity_kwh=5.12, primary_power=-1000.0, primary_soc=90.0,
            forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
        ),
        Params(), State(),
    )
    assert d.command == "charge" and d.power == 1200  # the AC charge limit
    assert d.values["charge_soft_start"] is True
