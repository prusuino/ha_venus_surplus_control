"""The projection ("the first battery is full long before sunset") extends
the surplus of this moment to sunset. With a forecast, the rest of the day
must really fill the first battery."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide

P = Params(primary_capacity_kwh=12.8)


def _inputs(**over) -> Inputs:
    # noon in November: 3500 W surplus now, first battery at 34 %, 4.6 h of sun left
    base = dict(
        surplus_mean=3500.0, surplus_instant=3500.0, surplus_ex_venus_mean=None, venus_soc=29.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=8.32, primary_power=-3300.0, primary_soc=34.0,
        forecast_today_kwh=14.8, forecast_remaining_kwh=5.6, sun_hours_left=4.6,
    )
    base.update(over)
    return Inputs(**base)


def test_projection_does_not_start_when_the_forecast_cannot_fill_the_first_battery():
    # seen on a real system: 5.6 kWh left today, the first battery misses 8.4 kWh
    d = decide(_inputs(), P, State())
    assert d.state.proj_latched is False
    assert d.target_mode == "stop" and d.reason == "primary_first"


def test_projection_starts_when_the_forecast_covers_the_first_battery():
    # 8.4 kWh missing, 2.3 kWh for the house: 12 kWh is enough with margin
    d = decide(_inputs(forecast_remaining_kwh=12.0), P, State())
    assert d.state.proj_latched is True
    assert d.target_mode == "charge" and d.reason == "charge_parallel"


def test_latched_projection_is_released_when_the_forecast_falls_short():
    d = decide(_inputs(), P, State(proj_latched=True))
    assert d.state.proj_latched is False and d.target_mode == "stop"


def test_latched_projection_holds_with_a_little_less_than_needed_to_start():
    # 8.45 kWh missing: start needs 9.3 + 2.3, hold 7.6 + 2.3
    d = decide(_inputs(forecast_remaining_kwh=10.5), P, State(proj_latched=True))
    assert d.state.proj_latched is True
    d = decide(_inputs(forecast_remaining_kwh=10.5), P, State())
    assert d.state.proj_latched is False


def test_without_a_forecast_the_projection_works_as_before():
    d = decide(_inputs(forecast_today_kwh=0.0, forecast_remaining_kwh=0.0), P, State())
    assert d.state.proj_latched is True
