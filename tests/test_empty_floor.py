"""A Venus at its own floor delivers nothing although a discharge command
stands: the command is taken back and comes again once it has charged."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide, state_from_dict, state_to_dict


def _inputs(**over) -> Inputs:
    base = dict(
        surplus_mean=-900.0, surplus_instant=-900.0, surplus_ex_venus_mean=None, venus_soc=15.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=8.32, primary_power=0.0, primary_soc=10.0,
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


def test_unanswered_discharge_at_the_floor_is_taken_back():
    d = decide(_inputs(), Params(), State())
    assert d.target_mode == "discharge" and d.command == "discharge"  # 15 % is the resume value: it tries
    d = _run(d.state, 3)
    assert d.target_mode == "discharge"  # not yet: three ticks without an answer
    d = decide(_inputs(), Params(), d.state)
    assert d.target_mode == "stop" and d.reason == "venus_soc_protect" and d.command == "standby"
    assert d.values["venus_empty"] is True and d.state.last_discharge_power == 0
    d = decide(_inputs(), Params(), d.state)
    assert d.target_mode == "stop" and d.reason == "venus_soc_protect" and d.command is None  # once is enough


def test_the_latch_holds_until_the_venus_has_charged():
    d = _run(State(), 5)
    assert d.state.empty_latched and d.state.empty_soc == 15.0
    d = _run(d.state, 6, venus_soc=16.9)
    assert d.target_mode == "stop" and d.reason == "venus_soc_protect"
    d = decide(_inputs(venus_soc=17.0), Params(), d.state)
    assert d.target_mode == "discharge" and d.command == "discharge" and d.state.empty_latched is False


def test_a_venus_that_delivers_is_not_latched():
    d = _run(State(), 12, venus_state="discharging", venus_ac=700.0)
    assert d.target_mode == "discharge" and d.state.empty_latched is False


def test_a_silent_venus_with_a_high_soc_is_not_called_empty():
    # that is a fault, not an empty battery: the quality sensor and the repair issue report it
    d = _run(State(), 12, venus_soc=60.0)
    assert d.target_mode == "discharge" and d.state.empty_latched is False


def test_an_empty_venus_still_charges():
    d = _run(State(), 5)
    assert d.state.empty_latched
    d = decide(_inputs(surplus_mean=1500.0, surplus_instant=1500.0, primary_soc=96.0), Params(), d.state)
    assert d.target_mode == "charge" and d.command == "charge"


def test_latch_survives_a_restart():
    d = _run(State(), 5)
    restored = state_from_dict(state_to_dict(d.state))
    assert restored.empty_latched is True and restored.empty_soc == 15.0
    assert state_from_dict({"last_charge_power": 0}).empty_latched is False
