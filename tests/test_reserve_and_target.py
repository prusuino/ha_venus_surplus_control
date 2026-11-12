"""The first battery's "empty" threshold follows an optional reserve input,
and the manual discharge down to a target SoC."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.venus_surplus.const import (
    CONF_CHARGE_POWER,
    CONF_DISCHARGE_POWER,
    CONF_FORCE_MODE,
    CONF_NAME,
    CONF_PRIMARY_POWER,
    CONF_PRIMARY_RESERVE,
    CONF_PRIMARY_SOC,
    CONF_RS485,
    CONF_SURPLUS,
    CONF_VENUS_AC,
    CONF_VENUS_SOC,
    CONF_VENUS_STATE,
    DOMAIN,
    EVENT_COMMAND,
)
from custom_components.venus_surplus.engine import Inputs, Params, State, decide, state_from_dict, state_to_dict

DATA = {
    CONF_NAME: "Venus", CONF_SURPLUS: "sensor.pv_surplus", CONF_FORCE_MODE: "select.venus_force_mode", CONF_CHARGE_POWER: "number.venus_charge_power",
    CONF_DISCHARGE_POWER: "number.venus_discharge_power", CONF_RS485: "switch.venus_rs485", CONF_VENUS_SOC: "sensor.venus_soc",
    CONF_VENUS_AC: "sensor.venus_ac_power", CONF_VENUS_STATE: "sensor.venus_state",
}


# ---------------------------------------------------------------- engine
def _night(primary_soc: float | None, reserve: float | None = None, primary_power: float | None = 0.0) -> Inputs:
    """The house imports 700 W at night and the first battery delivers nothing."""
    return Inputs(
        surplus_mean=-700.0, surplus_instant=-700.0, surplus_ex_venus_mean=None, venus_soc=60.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=5.12, primary_power=primary_power, primary_soc=primary_soc,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0, primary_reserve_soc=reserve,
    )


def test_without_a_reserve_input_the_first_battery_is_empty_at_12_percent():
    assert decide(_night(12.0), Params(), State()).target_mode == "discharge"
    waiting = decide(_night(13.0), Params(), State())
    assert waiting.target_mode == "stop" and waiting.values["primary_empty_below_soc"] == 12
    # a reading is ignored as long as no reserve input is configured
    assert decide(_night(18.0, reserve=20.0), Params(), State()).target_mode == "stop"


def test_the_empty_threshold_follows_the_reserve_plus_three_points():
    p = Params(has_primary_reserve=True)
    taking_over = decide(_night(23.0, reserve=20.0), p, State())
    assert taking_over.target_mode == "discharge" and taking_over.values["primary_empty_below_soc"] == 23
    assert decide(_night(24.0, reserve=20.0), p, State()).target_mode == "stop"


def test_the_empty_threshold_never_goes_below_12_percent():
    p = Params(has_primary_reserve=True)
    assert decide(_night(12.0, reserve=5.0), p, State()).target_mode == "discharge"
    assert decide(_night(13.0, reserve=5.0), p, State()).target_mode == "stop"


def test_a_reserve_reading_that_drops_out_keeps_the_last_value():
    p = Params(has_primary_reserve=True)
    first = decide(_night(40.0, reserve=20.0), p, State())
    assert first.state.last_primary_reserve == 20
    assert decide(_night(22.0, reserve=None), p, first.state).target_mode == "discharge"
    assert decide(_night(22.0, reserve=250.0), p, first.state).target_mode == "discharge"  # nonsense is no reading
    restored = state_from_dict(state_to_dict(first.state))
    assert restored.last_primary_reserve == 20


def test_a_reserve_input_that_never_delivered_leaves_the_fixed_12_percent():
    p = Params(has_primary_reserve=True)
    assert decide(_night(13.0, reserve=None), p, State()).target_mode == "stop"
    assert decide(_night(12.0, reserve=None), p, State()).target_mode == "discharge"


def test_removing_the_reserve_input_forgets_the_last_value():
    decision = decide(_night(22.0), Params(), State(last_primary_reserve=20.0))
    assert decision.target_mode == "stop" and decision.state.last_primary_reserve is None


def test_without_a_first_battery_the_reserve_plays_no_part():
    decision = decide(_night(None, primary_power=None), Params(has_primary=False), State())
    assert decision.target_mode == "discharge" and decision.reason == "discharge_ok"


# ---------------------------------------------------------------- controller
# The dependency `sun` polls its entity; that timer outlives the test.
sun_timer = pytest.mark.parametrize("expected_lingering_timers", [True])


async def _setup(hass: HomeAssistant, soc: str | None = "80", data: dict | None = None):
    if soc is not None:
        hass.states.async_set("sensor.venus_soc", soc)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=data or DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _live(controller) -> AsyncMock:
    """Leave the dry run and catch what would go to the Venus."""
    controller.settings.dry_run = False
    controller._call = AsyncMock()
    return controller._call


def _writes(calls: AsyncMock) -> list[tuple]:
    return [(c.args[0], c.args[1], c.args[2].get("value", c.args[2].get("option"))) for c in calls.call_args_list if c.args[0] != "logbook"]


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)


@sun_timer
async def test_reserve_input_reaches_the_engine_and_is_never_a_missing_input(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    data = {**DATA, CONF_PRIMARY_POWER: "sensor.battery_power", CONF_PRIMARY_SOC: "sensor.battery_soc", CONF_PRIMARY_RESERVE: "number.inverter_reserve"}
    entry = await _setup(hass, data=data)
    controller = entry.runtime_data
    assert controller.params().has_primary_reserve is True
    assert CONF_PRIMARY_RESERVE not in controller.missing_inputs()
    assert controller.inputs(dt_util.utcnow()).primary_reserve_soc is None
    hass.states.async_set("number.inverter_reserve", "20")
    assert controller.inputs(dt_util.utcnow()).primary_reserve_soc == 20


@sun_timer
async def test_target_soc_number_is_stored(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = await _setup(hass)
    assert entry.runtime_data.params().has_primary_reserve is False
    state = hass.states.get("number.venus_target_soc")
    assert state is not None and float(state.state) == 50
    await hass.services.async_call("number", "set_value", {"entity_id": "number.venus_target_soc", "value": 30}, blocking=True)
    assert entry.runtime_data.settings.target_soc == 30

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.settings.target_soc == 30


@sun_timer
async def test_discharges_to_the_target_then_stands_by_with_the_override_on(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = await _setup(hass)
    controller = entry.runtime_data
    controller.settings.target_soc = 30
    calls = _live(controller)
    events = async_capture_events(hass, EVENT_COMMAND)

    await _press(hass, "button.venus_discharge_to_target_soc")
    assert controller.settings.manual_override is True and controller.settings.discharge_target_active is True
    assert controller.state.last_discharge_power == 1000  # the discharge cap, kept by the watchdog
    assert _writes(calls) == [("number", "set_value", 1000), ("select", "select_option", "discharge")]
    assert controller.status.reason == "manual_discharge_target"
    assert hass.states.get("binary_sensor.venus_discharging_to_target_soc").state == "on"

    calls.reset_mock()
    hass.states.async_set("sensor.venus_soc", "31")
    await controller._tick(dt_util.utcnow())
    assert controller.settings.discharge_target_active is True and _writes(calls) == []
    assert controller.status.reason == "manual_discharge_target"

    hass.states.async_set("sensor.venus_soc", "30")
    await controller._tick(dt_util.utcnow())
    await hass.async_block_till_done()
    assert controller.settings.discharge_target_active is False
    assert controller.settings.manual_override is True  # otherwise the controller would discharge on
    assert controller.state.last_discharge_power == 0
    assert _writes(calls) == [("select", "select_option", "standby")]
    assert controller.status.reason == "target_soc_reached"
    assert [(e.data["command"], e.data["reason"], e.data["dry_run"]) for e in events] == [("standby", "target_soc_reached", False)]
    assert hass.states.get("binary_sensor.venus_discharging_to_target_soc").state == "off"

    calls.reset_mock()
    await controller._tick(dt_util.utcnow())
    assert _writes(calls) == [] and controller.status.reason == "target_soc_reached"  # still says why it stands by

    await _press(hass, "button.venus_back_to_auto")
    assert controller.settings.manual_override is False


@sun_timer
async def test_target_run_is_refused_at_or_below_the_target_and_without_a_reading(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = await _setup(hass, soc="50")
    controller = entry.runtime_data
    calls = _live(controller)
    with pytest.raises(HomeAssistantError) as err:
        await _press(hass, "button.venus_discharge_to_target_soc")
    assert err.value.translation_key == "target_reached"
    hass.states.async_set("sensor.venus_soc", "unavailable")
    with pytest.raises(HomeAssistantError) as err:
        await _press(hass, "button.venus_discharge_to_target_soc")
    assert err.value.translation_key == "soc_unknown"
    assert controller.settings.manual_override is False and controller.settings.discharge_target_active is False
    assert _writes(calls) == []


@sun_timer
async def test_target_run_is_cancelled_by_the_override_switch_and_by_other_buttons(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = await _setup(hass)
    controller = entry.runtime_data
    _live(controller)

    await _press(hass, "button.venus_discharge_to_target_soc")
    assert controller.settings.discharge_target_active is True
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.venus_manual_override"}, blocking=True)
    assert controller.settings.discharge_target_active is False and controller.settings.manual_override is False

    await _press(hass, "button.venus_discharge_to_target_soc")
    await _press(hass, "button.venus_manual_stop")
    assert controller.settings.discharge_target_active is False and controller.settings.manual_override is True
    assert controller.status.reason == "manual_standby"

    await _press(hass, "button.venus_discharge_to_target_soc")
    await _press(hass, "button.venus_manual_discharge")
    assert controller.settings.discharge_target_active is False
    assert controller.state.last_discharge_power == 600  # the plain manual button keeps its 600 W


@sun_timer
async def test_target_run_uses_the_discharge_cap_and_survives_a_reload(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = await _setup(hass)
    controller = entry.runtime_data
    controller.settings.discharge_cap_w = 450
    calls = _live(controller)
    await _press(hass, "button.venus_discharge_to_target_soc")
    assert _writes(calls)[0] == ("number", "set_value", 400)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.settings.discharge_target_active is True and entry.runtime_data.settings.manual_override is True


@sun_timer
async def test_target_run_in_dry_run_writes_nothing(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = await _setup(hass)
    controller = entry.runtime_data
    controller._call = AsyncMock()
    assert controller.settings.dry_run is True
    await _press(hass, "button.venus_discharge_to_target_soc")
    hass.states.async_set("sensor.venus_soc", "40")
    await controller._tick(dt_util.utcnow())
    assert controller.settings.discharge_target_active is False and controller.status.reason == "target_soc_reached"
    assert _writes(controller._call) == []
