"""Repair notice: readings incomplete for ten ticks name the missing
entities; complete readings withdraw the notice."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import (
    CONF_CHARGE_POWER,
    CONF_DISCHARGE_POWER,
    CONF_FORCE_MODE,
    CONF_NAME,
    CONF_RS485,
    CONF_SURPLUS,
    CONF_VENUS_AC,
    CONF_VENUS_SOC,
    CONF_VENUS_STATE,
    DOMAIN,
)
from custom_components.venus_surplus.controller import NO_DATA_ISSUE_TICKS, VenusController

DATA = {
    CONF_NAME: "Venus", CONF_SURPLUS: "sensor.pv_surplus", CONF_FORCE_MODE: "select.venus_force_mode", CONF_CHARGE_POWER: "number.venus_charge_power",
    CONF_DISCHARGE_POWER: "number.venus_discharge_power", CONF_RS485: "switch.venus_rs485", CONF_VENUS_SOC: "sensor.venus_soc",
    CONF_VENUS_AC: "sensor.venus_ac_power", CONF_VENUS_STATE: "sensor.venus_state",
}


def _set_readings(hass, surplus, soc, ac, state):
    hass.states.async_set("sensor.pv_surplus", surplus)
    hass.states.async_set("sensor.venus_soc", soc)
    hass.states.async_set("sensor.venus_ac_power", ac)
    hass.states.async_set("sensor.venus_state", state)


async def test_incomplete_readings_are_named_after_ten_ticks(hass: HomeAssistant, enable_custom_integrations) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=DATA)
    entry.add_to_hass(hass)
    controller = VenusController(hass, entry)
    _set_readings(hass, "1200", "unavailable", "0", "standby")
    assert controller.missing_inputs() == ["sensor.venus_soc"]
    registry = ir.async_get(hass)
    for n in range(NO_DATA_ISSUE_TICKS):
        await controller._tick(dt_util.utcnow())
        issue = registry.async_get_issue(DOMAIN, f"inputs_missing_{entry.entry_id}")
        assert (issue is not None) is (n == NO_DATA_ISSUE_TICKS - 1), f"after tick {n + 1}"
    assert issue.translation_placeholders == {"entities": "sensor.venus_soc"}
    assert controller.status.target_mode == "no_data"

    _set_readings(hass, "1200", "55", "0", "standby")
    assert controller.missing_inputs() == []
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode != "no_data"
    assert registry.async_get_issue(DOMAIN, f"inputs_missing_{entry.entry_id}") is None
    await controller.async_stop()
