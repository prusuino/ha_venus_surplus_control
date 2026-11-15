"""The RS485 watchdog: restores control mode and command, and runs at once
when the Venus comes back instead of waiting for its five-minute tick."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import CONF_CONNECTION, DOMAIN
from custom_components.venus_surplus.controller import VenusController

from .test_repairs import DATA, _set_readings


def _controller(hass) -> VenusController:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**DATA, CONF_CONNECTION: "binary_sensor.venus_modbus"})
    entry.add_to_hass(hass)
    controller = VenusController(hass, entry)
    controller.settings.dry_run = False
    controller._call = AsyncMock()
    return controller


def _event(old: str | None, new: str | None, entity_id: str = "switch.venus_rs485") -> SimpleNamespace:
    def state(value):
        return None if value is None else State(entity_id, value)

    return SimpleNamespace(data={"old_state": state(old), "new_state": state(new)})


def _writes(calls: AsyncMock) -> list[tuple]:
    return [(c.args[0], c.args[1], c.args[2].get("value", c.args[2].get("option"))) for c in calls.call_args_list if c.args[0] != "logbook"]


async def test_restarted_venus_gets_control_mode_and_command_back(hass: HomeAssistant, enable_custom_integrations, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    controller = _controller(hass)
    controller.state.last_charge_power = controller.state.last_charge_target = 1200
    _set_readings(hass, "2000", "16", "0", "standby")
    hass.states.async_set("switch.venus_rs485", "off")  # the restart switched it off
    hass.states.async_set("select.venus_force_mode", "charge")
    hass.states.async_set("number.venus_charge_power", "1200")

    await controller._watchdog(force=True)
    assert _writes(controller._call) == [("switch", "turn_on", None), ("number", "set_value", 1200), ("select", "select_option", "charge")]
    assert controller.status.watchdog_restores == 1
    await controller.async_stop()


async def test_watchdog_runs_at_once_when_the_venus_is_back(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller._watchdog = AsyncMock()

    # dropped by the firmware, and found off after a restart or a lost connection
    for old in ("on", "unavailable", "unknown", None):
        controller._watchdog.reset_mock()
        controller._rs485_changed(_event(old, "off"))
        await hass.async_block_till_done()
        controller._watchdog.assert_called_once_with(force=True, delay=15)
    # nothing to do when it stays off, comes on or goes away
    controller._watchdog.reset_mock()
    for old, new in (("off", "off"), ("off", "on"), ("on", "unavailable"), ("unavailable", "on")):
        controller._rs485_changed(_event(old, new))
    await hass.async_block_till_done()
    controller._watchdog.assert_not_called()

    # the Modbus connection returns
    for old in ("off", "unavailable"):
        controller._watchdog.reset_mock()
        controller._connection_changed(_event(old, "on", "binary_sensor.venus_modbus"))
        await hass.async_block_till_done()
        controller._watchdog.assert_called_once_with(force=True, delay=15)
    controller._watchdog.reset_mock()
    for old, new in (("on", "off"), ("on", "on"), (None, "on")):
        controller._connection_changed(_event(old, new, "binary_sensor.venus_modbus"))
    await hass.async_block_till_done()
    controller._watchdog.assert_not_called()

    # connection and control mode report within moments of each other: one run
    async def _slow(**kwargs) -> None:  # the real watchdog waits before it looks
        await asyncio.sleep(0)

    controller._watchdog = AsyncMock(side_effect=_slow)
    controller._connection_changed(_event("off", "on", "binary_sensor.venus_modbus"))
    controller._rs485_changed(_event("unavailable", "off"))
    await hass.async_block_till_done()
    controller._watchdog.assert_called_once_with(force=True, delay=15)
    await controller.async_stop()


async def test_cell_temperatures_are_found_through_the_modbus_entry(hass: HomeAssistant, enable_custom_integrations) -> None:
    from homeassistant.helpers import entity_registry as er

    from custom_components.venus_surplus.const import CONF_MODBUS_ENTRY

    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**DATA, CONF_MODBUS_ENTRY: "modbusentry"})
    entry.add_to_hass(hass)
    controller = VenusController(hass, entry)
    assert controller.cell_temperatures() == (None, None)  # the sensors do not exist

    registry = er.async_get(hass)
    low = registry.async_get_or_create("sensor", "marstek_modbus", "modbusentry_min_cell_temperature", suggested_object_id="venus_min_cell")
    high = registry.async_get_or_create("sensor", "marstek_modbus", "modbusentry_max_cell_temperature", suggested_object_id="venus_max_cell")
    assert controller.cell_temperatures() == (None, None)  # disabled or without a value yet
    hass.states.async_set(low.entity_id, "9.8")
    hass.states.async_set(high.entity_id, "unavailable")
    assert controller.cell_temperatures() == (9.8, None)
    hass.states.async_set("sensor.venus_soc", "23")
    assert controller.quality_state() == "collecting"

    other = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_other", title="Other", data=DATA)  # no Modbus entry set
    other.add_to_hass(hass)
    assert VenusController(hass, other).cell_temperatures() == (None, None)
    await controller.async_stop()
