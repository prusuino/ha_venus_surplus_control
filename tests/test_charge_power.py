"""Charge power over several ticks: it follows the surplus down and up
again, with and without the Venus' own PV sensors, and the adjustable
charge reserve reaches the engine and survives a restart."""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import (
    CONF_CHARGE_POWER,
    CONF_DISCHARGE_POWER,
    CONF_FORCE_MODE,
    CONF_NAME,
    CONF_RS485,
    CONF_SURPLUS,
    CONF_VENUS_AC,
    CONF_VENUS_PV,
    CONF_VENUS_SOC,
    CONF_VENUS_STATE,
    DOMAIN,
)
from custom_components.venus_surplus.engine import Inputs, Params, State, decide

DATA = {
    CONF_NAME: "Venus", CONF_SURPLUS: "sensor.pv_surplus", CONF_FORCE_MODE: "select.venus_force_mode", CONF_CHARGE_POWER: "number.venus_charge_power",
    CONF_DISCHARGE_POWER: "number.venus_discharge_power", CONF_RS485: "switch.venus_rs485", CONF_VENUS_SOC: "sensor.venus_soc",
    CONF_VENUS_AC: "sensor.venus_ac_power", CONF_VENUS_STATE: "sensor.venus_state",
}


def _run(params: Params, surplus: list[float], venus_pv: list[float] | None = None) -> list[int]:
    """Feed the surplus tick by tick; the Venus follows every command. Returns
    the commanded charge power after each tick."""
    state, venus_state, powers = State(), "standby", []
    for n, value in enumerate(surplus):
        inputs = Inputs(
            surplus_mean=value, surplus_instant=value, surplus_ex_venus_mean=value, venus_soc=82.0, venus_ac=0.0,
            venus_pv=venus_pv[n] if venus_pv else 0.0, venus_state=venus_state, venus_capacity_kwh=5.12,
            primary_power=0.0, primary_soc=100.0, forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=3.0,
        )
        decision = decide(inputs, params, state)
        state = decision.state
        if decision.command == "charge":
            venus_state = "charging"
        elif decision.command == "standby":
            venus_state = "standby"
        powers.append(state.last_charge_power)
    return powers


def test_charge_power_recovers_after_a_load_peak_without_own_pv():
    # A washing machine takes most of the surplus for a while, then stops.
    powers = _run(Params(), [1500, 1500, 600, 600, 1500, 1500])
    assert powers == [1200, 1200, 400, 400, 1200, 1200]


def test_unknown_own_pv_holds_the_power_for_four_ticks_only():
    # MPPT sensors are configured but have never shown production: the
    # power is not raised for four ticks, then the low reading is believed.
    surplus = [600] + [1500] * 6
    powers = _run(Params(has_venus_pv=True), surplus)
    assert powers == [400, 400, 400, 400, 400, 1200, 1200]


def test_own_pv_counts_against_the_total_limit():
    powers = _run(Params(has_venus_pv=True), [1500, 1500, 600, 1500], venus_pv=[300.0] * 4)
    assert powers == [1100, 1100, 400, 1100]  # 1400 W total minus 300 W own PV


def test_a_brief_zero_of_the_own_pv_is_bridged_with_the_last_value():
    powers = _run(Params(has_venus_pv=True), [1500, 1500, 1500], venus_pv=[300.0, 0.0, 300.0])
    assert powers == [1100, 1100, 1100]


def test_steps_up_150_w_above_the_current_target():
    # headroom = surplus minus 200 W reserve; target 400 W
    assert _run(Params(), [600, 740])[-1] == 400  # headroom 540: not yet
    assert _run(Params(), [600, 750])[-1] == 500  # headroom 550: one step up


def test_charge_reserve_sets_the_headroom():
    assert _run(Params(), [964])[-1] == 700  # 200 W reserve: headroom 764 W
    assert _run(Params(charge_reserve_w=50), [964])[-1] == 900
    assert _run(Params(charge_reserve_w=0), [964])[-1] == 900
    decision = decide(
        Inputs(
            surplus_mean=964.0, surplus_instant=964.0, surplus_ex_venus_mean=964.0, venus_soc=82.0, venus_ac=0.0, venus_pv=0.0,
            venus_state="standby", venus_capacity_kwh=5.12, primary_power=0.0, primary_soc=100.0,
            forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=3.0,
        ),
        Params(charge_reserve_w=50),
        State(),
    )
    assert decision.values["headroom_w"] == 914 and decision.values["charge_reserve_w"] == 50


# The dependency `sun` polls its entity; that timer outlives the test.
sun_timer = pytest.mark.parametrize("expected_lingering_timers", [True])


@sun_timer
async def test_charge_reserve_number_reaches_the_engine_and_is_stored(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    controller = entry.runtime_data
    assert controller.params().charge_reserve_w == 200 and controller.params().has_venus_pv is False

    state = hass.states.get("number.venus_charge_reserve")
    assert state is not None and float(state.state) == 200
    await hass.services.async_call("number", "set_value", {"entity_id": "number.venus_charge_reserve", "value": 50}, blocking=True)
    assert controller.settings.charge_reserve_w == 50 and controller.params().charge_reserve_w == 50

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.settings.charge_reserve_w == 50


@sun_timer
async def test_configured_mppt_sensors_switch_the_pv_guard_on(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**DATA, CONF_VENUS_PV: ["sensor.venus_pv1"]})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.params().has_venus_pv is True
