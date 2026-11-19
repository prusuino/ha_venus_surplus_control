"""A large load that switches on is served within two ticks, in both
directions: a Venus that charges takes its command back by what the grid
delivers, and a Venus that stands by starts to discharge without waiting for
the average or for the first battery. Small loads go the calm way as before."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, _ticks, decide


def _inp(**over) -> Inputs:
    base = dict(
        surplus_mean=0.0, surplus_instant=0.0, surplus_ex_venus_mean=0.0, venus_soc=60.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=5.12, primary_power=0.0, primary_soc=50.0,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=3.0,
    )
    base.update(over)
    return Inputs(**base)


P = Params(discharge_min_w=100)


# ---- charging: the grid must not feed the Venus ------------------------------

def _charging(instant: float, **over) -> Inputs:
    # the average still shows 1200 W of surplus without the Venus, which charges at 900 W
    base = dict(surplus_mean=300.0, surplus_instant=instant, surplus_ex_venus_mean=1200.0, venus_ac=-900.0, venus_state="charging", primary_soc=100.0)
    base.update(over)
    return _inp(**base)


def _charging_state() -> State:
    return State(last_charge_power=900, last_charge_target=900)


def test_import_while_charging_lowers_the_command_in_the_same_tick():
    # a 600 W load switches on, the full first battery does not cover it: 300 W come from the grid
    d = decide(_charging(-300.0), P, _charging_state())
    assert d.values["grid_import_w"] == 300
    # 900 - (300 + 50) = 550 W
    assert d.target_mode == "charge" and d.command == "charge" and d.power == 500
    assert d.state.import_cap_w == 550


def test_a_little_import_changes_nothing():
    d = decide(_charging(-80.0), P, _charging_state())
    assert d.target_mode == "charge" and d.command is None and d.state.import_cap_w < 0


def test_a_first_battery_that_covers_the_load_is_not_counted_twice():
    # the first battery delivers the 300 W: no import, the cross trim alone acts
    d = decide(_charging(-300.0, primary_power=300.0), P, _charging_state())
    assert d.values["grid_import_w"] == 0 and round(d.state.cross_trim_w) == 350


def test_the_trim_keeps_growing_while_the_import_stays():
    d = decide(_charging(-300.0), P, _charging_state())
    # the Venus now charges 500 W, and the grid still delivers 150 W
    d = decide(_charging(-150.0, venus_ac=-500.0), P, d.state)
    assert d.state.last_charge_power == 300


def test_a_command_far_below_the_average_is_capped_as_well():
    # 3000 W of surplus in the average, the Venus at its limit of 1000 W, 200 W of import
    d = decide(_charging(-200.0, surplus_ex_venus_mean=3000.0, venus_ac=-1000.0), P, State(last_charge_power=1000, last_charge_target=1000))
    assert d.command == "charge" and d.power == 700


def test_the_cap_rises_again_and_goes_away():
    d = decide(_charging(-300.0), P, _charging_state())
    powers = []
    for _ in range(8):
        d = decide(_charging(300.0, venus_ac=-float(d.state.last_charge_power)), P, d.state)
        powers.append(d.state.last_charge_power)
    assert powers == sorted(powers) and powers[-1] == 900 and d.state.import_cap_w < 0


def test_without_a_first_battery_the_import_counts_as_well():
    p = Params(discharge_min_w=100, has_primary=False)
    d = decide(_charging(-300.0, primary_power=None, primary_soc=None), p, _charging_state())
    assert d.command == "charge" and d.power == 500


def test_a_load_larger_than_the_surplus_stops_the_charge_at_once_and_the_discharge_follows():
    # seen on the test system: 3000 W switch on, 1500 W come from the grid while the average still shows sun
    d = decide(_charging(-1500.0), P, _charging_state())
    assert d.target_mode == "stop" and d.command == "standby" and d.state.fast_count == 1
    d = decide(_inp(surplus_mean=1000.0, surplus_instant=-600.0, surplus_ex_venus_mean=1000.0, primary_soc=100.0), P, d.state)
    assert d.command == "discharge" and d.values["fast_start"] is True


def test_no_charge_starts_on_the_average_while_the_grid_delivers():
    # the average still shows 1000 W of sun, but at this moment 300 W are imported
    d = decide(_inp(surplus_mean=1000.0, surplus_instant=-300.0, surplus_ex_venus_mean=1000.0, primary_soc=100.0), P, State())
    assert d.target_mode == "stop" and d.values["charge_command_w"] == 0
    # without the import it starts
    d = decide(_inp(surplus_mean=1000.0, surplus_instant=900.0, surplus_ex_venus_mean=1000.0, primary_soc=100.0), P, State())
    assert d.command == "charge"


# ---- standing by: a large load starts the discharge ---------------------------

def test_a_large_uncovered_load_starts_the_discharge_after_two_ticks():
    # the first battery is neither empty nor delivering, the average still shows sun
    load = dict(surplus_mean=500.0, surplus_instant=-1500.0, surplus_ex_venus_mean=500.0)
    d = decide(_inp(**load), P, State())
    assert d.target_mode == "stop" and d.state.fast_count == 1
    d = decide(_inp(**load), P, d.state)
    assert d.command == "discharge" and d.values["fast_start"] is True
    assert d.power == 1000  # straight to the limit


def test_a_running_fast_discharge_is_not_stopped_by_the_old_average():
    s = State(last_discharge_power=1000, fast_count=2)
    d = decide(_inp(surplus_mean=200.0, surplus_instant=-500.0, surplus_ex_venus_mean=200.0, venus_ac=1000.0, venus_state="discharging"), P, s)
    assert d.target_mode == "discharge"


def test_it_stops_when_the_load_is_gone_and_the_sun_is_back():
    s = State(last_discharge_power=1000, fast_count=2)
    d = decide(_inp(surplus_mean=600.0, surplus_instant=1600.0, surplus_ex_venus_mean=600.0, venus_ac=1000.0, venus_state="discharging"), P, s)
    assert d.target_mode != "discharge" and d.state.fast_count == 0


def test_a_load_the_first_battery_covers_does_not_take_the_fast_lane():
    # 450 W from the first battery, nothing from the grid: the calm rule (90 s) applies
    load = dict(surplus_mean=-450.0, surplus_instant=-450.0, surplus_ex_venus_mean=-450.0, primary_power=450.0)
    s = State()
    for _ in range(2):
        d = decide(_inp(**load), P, s)
        s = d.state
        assert d.target_mode == "stop" and s.fast_count == 0


def test_one_tick_of_a_large_load_is_not_enough():
    d = decide(_inp(surplus_instant=-1500.0), P, State())
    d = decide(_inp(surplus_instant=-100.0), P, d.state)
    assert d.target_mode == "stop" and d.state.fast_count == 0


def test_a_small_load_waits_as_before():
    load = dict(surplus_mean=-300.0, surplus_instant=-300.0, surplus_ex_venus_mean=-300.0)
    d = decide(_inp(**load), P, State())
    d = decide(_inp(**load), P, d.state)
    assert d.target_mode == "stop" and d.values["fast_start"] is False


def test_a_charging_first_battery_still_blocks():
    load = dict(surplus_instant=-1500.0, primary_power=-300.0)
    s = State()
    for _ in range(3):
        d = decide(_inp(**load), P, s)
        s = d.state
    assert d.target_mode == "stop"


# ---- the waits are times ------------------------------------------------------

def test_waits_are_seconds_not_ticks():
    assert _ticks(90, 15) == 6 and _ticks(90, 30) == 3 and _ticks(90, 60) == 2 and _ticks(90, 120) == 2


def test_a_paused_first_battery_takes_six_ticks_at_15_s():
    p = Params(discharge_min_w=100, tick_seconds=15)
    load = dict(surplus_mean=-240.0, surplus_instant=-240.0, surplus_ex_venus_mean=-240.0, sun_hours_left=0.0)
    s = State()
    for n in range(5):
        d = decide(_inp(**load), p, s)
        s = d.state
        assert d.target_mode == "stop", n
    assert decide(_inp(**load), p, s).command == "discharge"
