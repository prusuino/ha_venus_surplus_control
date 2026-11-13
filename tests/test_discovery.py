"""Setup: the Venus entities of the Marstek Venus Modbus integration are
suggested in the forms and can be changed."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.venus_surplus.config_flow import discover_venus
from custom_components.venus_surplus.const import (
    CONF_CHARGE_POWER,
    CONF_CONNECTION,
    CONF_DISCHARGE_POWER,
    CONF_FORCE_MODE,
    CONF_MODBUS_ENTRY,
    CONF_NAME,
    CONF_RS485,
    CONF_SURPLUS,
    CONF_VENUS_AC,
    CONF_VENUS_CAPACITY,
    CONF_VENUS_PV,
    CONF_VENUS_SOC,
    CONF_VENUS_STATE,
    DOMAIN,
)

KEYS = [
    ("select", "force_mode"), ("number", "set_charge_power"), ("number", "set_discharge_power"), ("switch", "rs485_control_mode"),
    ("sensor", "battery_soc"), ("sensor", "ac_power"), ("sensor", "inverter_state"), ("sensor", "battery_total_energy"),
    ("binary_sensor", "modbus_connection"), ("sensor", "mppt1_power"), ("sensor", "mppt2_power"), ("sensor", "mppt3_power"), ("sensor", "battery_voltage"),
]


@pytest.fixture(autouse=True)
def no_controller(hass: HomeAssistant):
    mock_component(hass, "sun")
    with patch("custom_components.venus_surplus.async_setup_entry", return_value=True):
        yield


def _modbus_venus(hass: HomeAssistant, name: str) -> MockConfigEntry:
    """A Venus as the Modbus integration registers it; MPPT 3 is disabled."""
    entry = MockConfigEntry(domain="marstek_modbus", title=name)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for domain, key in KEYS:
        registry.async_get_or_create(
            domain, "marstek_modbus", f"{entry.entry_id}_{key}", config_entry=entry, suggested_object_id=f"{name}_{key}",
            disabled_by=er.RegistryEntryDisabler.INTEGRATION if key == "mppt3_power" else None,
        )
    return entry


def _defaults(result) -> dict:
    out = {}
    for key in result["data_schema"].schema:
        if key.description and "suggested_value" in key.description:
            out[str(key)] = key.description["suggested_value"]
        elif getattr(key, "default", None) is not None and callable(key.default):
            try:
                out[str(key)] = key.default()
            except TypeError:
                pass
    return out


async def test_nothing_found_leaves_the_form_empty(hass: HomeAssistant, enable_custom_integrations) -> None:
    assert discover_venus(hass) == {}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert CONF_FORCE_MODE not in {k: v for k, v in _defaults(result).items() if v}


async def test_the_venus_entities_are_suggested_and_can_be_changed(hass: HomeAssistant, enable_custom_integrations) -> None:
    modbus = _modbus_venus(hass, "venus")
    found = discover_venus(hass)
    assert found == {
        CONF_FORCE_MODE: "select.venus_force_mode",
        CONF_CHARGE_POWER: "number.venus_set_charge_power",
        CONF_DISCHARGE_POWER: "number.venus_set_discharge_power",
        CONF_RS485: "switch.venus_rs485_control_mode",
        CONF_VENUS_SOC: "sensor.venus_battery_soc",
        CONF_VENUS_AC: "sensor.venus_ac_power",
        CONF_VENUS_STATE: "sensor.venus_inverter_state",
        CONF_VENUS_CAPACITY: "sensor.venus_battery_total_energy",
        CONF_CONNECTION: "binary_sensor.venus_modbus_connection",
        CONF_VENUS_PV: ["sensor.venus_mppt1_power", "sensor.venus_mppt2_power"],  # the disabled input is left out
        CONF_MODBUS_ENTRY: modbus.entry_id,
    }

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    first = _defaults(result)
    assert first[CONF_FORCE_MODE] == "select.venus_force_mode" and first[CONF_VENUS_SOC] == "sensor.venus_battery_soc"

    # the user keeps the suggestions but picks another AC power sensor
    required = {k: first[k] for k in (CONF_FORCE_MODE, CONF_CHARGE_POWER, CONF_DISCHARGE_POWER, CONF_RS485, CONF_VENUS_SOC, CONF_VENUS_STATE)}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Venus", CONF_SURPLUS: "sensor.pv_surplus", CONF_VENUS_AC: "sensor.my_own_ac_power", **required}
    )
    assert result["step_id"] == "optional"
    second = _defaults(result)
    assert second[CONF_VENUS_PV] == ["sensor.venus_mppt1_power", "sensor.venus_mppt2_power"]
    assert second[CONF_MODBUS_ENTRY] == modbus.entry_id

    # ... and removes the suggested capacity sensor: a suggestion left out stays out
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_VENUS_PV: second[CONF_VENUS_PV], CONF_CONNECTION: second[CONF_CONNECTION], CONF_MODBUS_ENTRY: modbus.entry_id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_VENUS_AC] == "sensor.my_own_ac_power"
    assert CONF_VENUS_CAPACITY not in result["data"]
    assert result["data"][CONF_VENUS_PV] == ["sensor.venus_mppt1_power", "sensor.venus_mppt2_power"]


async def test_a_second_venus_is_suggested_once_the_first_has_a_controller(hass: HomeAssistant, enable_custom_integrations) -> None:
    _modbus_venus(hass, "venus")
    second = _modbus_venus(hass, "garage")
    MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", data={CONF_FORCE_MODE: "select.venus_force_mode"}).add_to_hass(hass)
    found = discover_venus(hass)
    assert found[CONF_FORCE_MODE] == "select.garage_force_mode" and found[CONF_MODBUS_ENTRY] == second.entry_id
