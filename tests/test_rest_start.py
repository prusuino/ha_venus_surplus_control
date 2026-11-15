"""The surplus the remaining-forecast rule asks for is a setting."""
from __future__ import annotations

from custom_components.venus_surplus.engine import Inputs, Params, State, decide


def _day(surplus: float) -> Inputs:
    return Inputs(
        surplus_mean=surplus, surplus_instant=surplus, surplus_ex_venus_mean=None, venus_soc=40.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=5.12, primary_power=-100.0, primary_soc=60.0,
        forecast_today_kwh=10.0, forecast_remaining_kwh=40.0, sun_hours_left=5.0,
    )


def test_the_remaining_forecast_rule_needs_the_surplus_that_is_set():
    assert decide(_day(1800), Params(), State()).values["rest_latched"] is False  # default 2500 W
    assert decide(_day(1800), Params(rest_start_surplus_w=1500), State()).values["rest_latched"] is True
    assert decide(_day(2600), Params(), State()).values["rest_latched"] is True
