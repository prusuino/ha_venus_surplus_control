"""Config flow tests: the two setup steps, cleaning of empty optional
fields, one entry per Venus and the options flow."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.venus_surplus.const import (
    CONF_AC_CHARGE_LIMIT,
    CONF_CHARGE_POWER,
    CONF_DISCHARGE_LIMIT,
    CONF_DISCHARGE_POWER,
    CONF_FORCE_MODE,
    CONF_FORECAST_FACTOR,
    CONF_NAME,
    CONF_PRIMARY_POWER,
    CONF_PRIMARY_POWER_INVERT,
    CONF_PRIMARY_RESERVE,
    CONF_PRIMARY_SOC,
    CONF_RS485,
    CONF_SURPLUS,
    CONF_SURPLUS_INVERT,
    CONF_TICK_SECONDS,
    CONF_TOTAL_CHARGE_LIMIT,
    CONF_VENUS_AC,
    CONF_VENUS_AC_INVERT,
    CONF_VENUS_PV,
    CONF_VENUS_SOC,
    CONF_VENUS_STATE,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def no_controller(hass: HomeAssistant):
    """The flow tests check the dialog only: the controller is not started and
    the sun dependency (whose entity keeps a timer) is marked as set up."""
    mock_component(hass, "sun")
    with patch("custom_components.venus_surplus.async_setup_entry", return_value=True):
        yield


REQUIRED = {
    CONF_NAME: "Venus", CONF_SURPLUS: "sensor.pv_surplus", CONF_SURPLUS_INVERT: False, CONF_FORCE_MODE: "select.venus_force_mode",
    CONF_CHARGE_POWER: "number.venus_charge_power", CONF_DISCHARGE_POWER: "number.venus_discharge_power", CONF_RS485: "switch.venus_rs485",
    CONF_VENUS_SOC: "sensor.venus_soc", CONF_VENUS_AC: "sensor.venus_ac_power", CONF_VENUS_AC_INVERT: True, CONF_VENUS_STATE: "sensor.venus_state",
}
OPTIONAL = {
    CONF_VENUS_PV: ["sensor.venus_pv_a", "sensor.venus_pv_d"], CONF_PRIMARY_POWER: "sensor.battery_power", CONF_PRIMARY_POWER_INVERT: False,
    CONF_FORECAST_FACTOR: 0.8, CONF_AC_CHARGE_LIMIT: 1200, CONF_TOTAL_CHARGE_LIMIT: 1400, CONF_DISCHARGE_LIMIT: 1000, CONF_TICK_SECONDS: 30,
}


async def test_setup_in_two_steps(hass: HomeAssistant, enable_custom_integrations) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], REQUIRED)
    assert result["step_id"] == "optional"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], OPTIONAL)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Venus"
    data = result["data"]
    assert data[CONF_FORCE_MODE] == "select.venus_force_mode"
    assert data[CONF_VENUS_AC_INVERT] is True and data[CONF_SURPLUS_INVERT] is False and data[CONF_PRIMARY_POWER_INVERT] is False
    assert data[CONF_VENUS_PV] == ["sensor.venus_pv_a", "sensor.venus_pv_d"]
    assert CONF_PRIMARY_SOC not in data  # an optional field left empty is not stored
    assert data[CONF_TICK_SECONDS] == 30
    assert result["result"].unique_id == f"{DOMAIN}_select.venus_force_mode"


async def test_one_entry_per_venus(hass: HomeAssistant, enable_custom_integrations) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**REQUIRED}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], REQUIRED)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], OPTIONAL)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_drops_a_removed_optional_entity(hass: HomeAssistant, enable_custom_integrations) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**REQUIRED, CONF_PRIMARY_POWER: "sensor.battery_power", CONF_PRIMARY_SOC: "sensor.battery_soc"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**REQUIRED, CONF_NAME: "Venus Keller"})
    assert result["step_id"] == "optional"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**OPTIONAL, CONF_AC_CHARGE_LIMIT: 800})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NAME] == "Venus Keller"
    assert entry.options[CONF_AC_CHARGE_LIMIT] == 800
    assert entry.options[CONF_PRIMARY_POWER] == "sensor.battery_power"
    assert CONF_PRIMARY_SOC not in entry.options
    assert CONF_PRIMARY_SOC not in entry.data  # removed in the form: gone from the entry as well


async def test_reserve_input_is_stored_and_can_be_removed(hass: HomeAssistant, enable_custom_integrations) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], REQUIRED)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**OPTIONAL, CONF_PRIMARY_SOC: "sensor.battery_soc", CONF_PRIMARY_RESERVE: "number.battery_reserve"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRIMARY_RESERVE] == "number.battery_reserve"  # a number or a helper is accepted, not only a sensor
    entry = result["result"]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], REQUIRED)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {**OPTIONAL, CONF_PRIMARY_SOC: "sensor.battery_soc"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PRIMARY_SOC] == "sensor.battery_soc"
    assert CONF_PRIMARY_RESERVE not in entry.options and CONF_PRIMARY_RESERVE not in entry.data
