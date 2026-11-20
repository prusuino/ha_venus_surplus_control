"""The guards beside the master tick: the watchdog's mismatch checks, the
discharge cap guard, the Modbus self-heal, the issue counter and the
diagnostics download."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import CONF_CONNECTION, CONF_MODBUS_ENTRY, DOMAIN, SELF_HEAL_AFTER
from custom_components.venus_surplus.controller import VenusController
from custom_components.venus_surplus.diagnostics import async_get_config_entry_diagnostics
from custom_components.venus_surplus.issues import IssueReporter, async_clear_entry_issues

from .test_repairs import DATA, _set_readings
from .test_watchdog import _writes


def _controller(hass, **extra) -> VenusController:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**DATA, **extra})
    entry.add_to_hass(hass)
    controller = VenusController(hass, entry)
    controller.settings.dry_run = False
    controller._call = AsyncMock()
    return controller


def _logged(calls: AsyncMock) -> list[str]:
    return [c.args[2]["message"] for c in calls.call_args_list if c.args[0] == "logbook"]


async def test_watchdog_leaves_a_venus_alone_that_cannot_be_reached_or_was_just_written(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller.state.last_charge_power = 800
    hass.states.async_set("select.venus_force_mode", "standby")  # differs from the charge command
    for found in (None, "unavailable"):
        if found:
            hass.states.async_set("switch.venus_rs485", found)
        await controller._watchdog(force=False)
    hass.states.async_set("switch.venus_rs485", "on")
    controller._last_master_run = dt_util.utcnow()  # the master wrote a moment ago
    await controller._watchdog(force=False)
    await controller._watchdog_tick(dt_util.utcnow())
    assert _writes(controller._call) == []
    assert controller.status.watchdog_restores == 0

    controller._last_master_run = dt_util.utcnow() - timedelta(seconds=30)
    await controller._watchdog(force=False)
    assert _writes(controller._call) == [("number", "set_value", 800), ("select", "select_option", "charge")]
    assert controller.status.watchdog_restores == 1
    await controller.async_stop()


async def test_watchdog_restores_a_changed_register_and_a_lost_standby(hass: HomeAssistant, enable_custom_integrations, monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    controller = _controller(hass)
    hass.states.async_set("switch.venus_rs485", "on")

    # discharging: the register no longer holds the commanded power
    controller.state.last_discharge_power = 300
    hass.states.async_set("select.venus_force_mode", "discharge")
    hass.states.async_set("number.venus_discharge_power", "500")
    await controller._watchdog(force=True, delay=15)
    assert _writes(controller._call) == [("number", "set_value", 300), ("select", "select_option", "discharge")]
    assert asyncio.sleep.await_args_list[0].args == (15,)

    # nothing differs: nothing is written
    controller._call.reset_mock()
    hass.states.async_set("number.venus_discharge_power", "300")
    await controller._watchdog(force=True)
    assert _writes(controller._call) == []

    # standing by, and the control mode was dropped: switch it on, send standby
    controller._call.reset_mock()
    controller.state.last_discharge_power = 0
    hass.states.async_set("switch.venus_rs485", "off")
    await controller._watchdog(force=True)
    assert _writes(controller._call) == [("switch", "turn_on", None), ("select", "select_option", "standby")]
    assert controller.status.watchdog_restores == 2
    await controller.async_stop()


async def test_watchdog_sees_a_venus_that_does_something_else_under_manual_override(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller.settings.manual_override = True
    controller.state.last_charge_power = 600
    hass.states.async_set("switch.venus_rs485", "on")
    hass.states.async_set("select.venus_force_mode", "charge")
    hass.states.async_set("number.venus_charge_power", "600")
    _set_readings(hass, "900", "40", "0", "standby")
    await controller._watchdog(force=True)
    assert _writes(controller._call) == []  # the status has only just changed

    with patch("custom_components.venus_surplus.controller.dt_util.utcnow", return_value=dt_util.utcnow() + timedelta(minutes=5)):
        await controller._watchdog(force=True)
    assert _writes(controller._call) == [("number", "set_value", 600), ("select", "select_option", "charge")]
    await controller.async_stop()


async def test_watchdog_only_reports_in_a_dry_run(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller.settings.dry_run = True
    controller.state.last_charge_power = 800
    hass.states.async_set("switch.venus_rs485", "off")
    hass.states.async_set("select.venus_force_mode", "charge")
    await controller._watchdog(force=True)
    assert _writes(controller._call) == []
    assert controller.status.watchdog_restores == 0
    assert _logged(controller._call)[0].startswith("-> DRY RUN WATCHDOG | rs485_lost=True")
    await controller.async_stop()


async def test_cap_guard_lowers_register_and_remembered_power(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller.settings.discharge_cap_w = 400

    await controller._cap_guard()  # no register value
    hass.states.async_set("number.venus_discharge_power", "300")
    controller.state.last_discharge_power = 300
    await controller._cap_guard_tick(dt_util.utcnow())  # all within the cap
    assert _writes(controller._call) == []
    assert controller.status.cap_enforced == 0

    # only the remembered power is above the cap
    controller.state.last_discharge_power = 800
    await controller._cap_guard()
    assert controller.state.last_discharge_power == 400
    assert _writes(controller._call) == []
    assert controller.status.cap_enforced == 1

    # the register was raised from outside
    hass.states.async_set("number.venus_discharge_power", "800")
    controller.state.last_discharge_power = 800
    await controller._cap_guard()
    assert controller.state.last_discharge_power == 400
    assert _writes(controller._call) == [("number", "set_value", 400)]
    assert controller.status.cap_enforced == 2

    # a dry run names it and writes nothing
    controller._call.reset_mock()
    controller.settings.dry_run = True
    await controller._cap_guard()
    assert _writes(controller._call) == []
    assert _logged(controller._call) == ["-> DRY RUN DISCHARGE CAP | register=800W > cap 400W"]
    assert controller.status.cap_enforced == 2
    await controller.async_stop()


async def test_cap_guard_runs_when_the_register_changes(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller._cap_guard = AsyncMock()
    controller._tick = AsyncMock()
    hass.states.async_set("switch.venus_rs485", "on")
    await controller.async_start()
    hass.states.async_set("number.venus_discharge_power", "700")
    await hass.async_block_till_done()
    controller._cap_guard.assert_awaited_once()
    await controller.async_stop()


async def test_self_heal_reloads_modbus_after_a_long_loss(hass: HomeAssistant, enable_custom_integrations, caplog) -> None:
    controller = _controller(hass, **{CONF_CONNECTION: "binary_sensor.venus_modbus", CONF_MODBUS_ENTRY: "modbusentry"})
    now = dt_util.utcnow()
    with patch.object(hass.config_entries, "async_reload", AsyncMock()) as reload:
        await controller._self_heal_tick(now)  # the sensor does not exist
        hass.states.async_set("binary_sensor.venus_modbus", "on")
        await controller._self_heal_tick(now)
        hass.states.async_set("binary_sensor.venus_modbus", "off")
        await controller._self_heal_tick(now)  # lost a moment ago
        reload.assert_not_awaited()

        later = now + SELF_HEAL_AFTER + timedelta(seconds=30)
        with patch("custom_components.venus_surplus.controller.dt_util.utcnow", return_value=later):
            controller.settings.dry_run = True
            await controller._self_heal_tick(later)
            reload.assert_not_awaited()
            assert _logged(controller._call) == ["-> DRY RUN MODBUS SELF-HEAL | would reload the Modbus integration"]

            controller.settings.dry_run = False
            await controller._self_heal_tick(later)
            reload.assert_awaited_once_with("modbusentry")
            assert controller.status.self_heals == 1

            reload.side_effect = RuntimeError("gone")
            await controller._self_heal_tick(later)
            assert controller.status.self_heals == 2
            assert "Reload of the Modbus config entry failed: gone" in caplog.text
    await controller.async_stop()


async def test_a_failure_becomes_an_issue_after_several_in_a_row(hass: HomeAssistant) -> None:
    registry = ir.async_get(hass)
    issues = IssueReporter(hass, "entry1", after=3)
    for n in range(3):
        issues.failure("inputs_missing", {"entities": "sensor.a"})
        assert (registry.async_get_issue(DOMAIN, "inputs_missing_entry1") is not None) is (n == 2)
    issues.clear("inputs_missing")
    assert registry.async_get_issue(DOMAIN, "inputs_missing_entry1") is None
    issues.clear("inputs_missing")  # nothing open: nothing to do

    issues.failure("inputs_missing", {"entities": "sensor.b"}, after=1, suffix="b")
    assert registry.async_get_issue(DOMAIN, "inputs_missing_b_entry1").translation_placeholders == {"entities": "sensor.b"}
    IssueReporter(hass, "entry2").raise_now("surplus_silent", {"entity": "sensor.s", "minutes": 12})
    async_clear_entry_issues(hass, "entry1")
    assert registry.async_get_issue(DOMAIN, "inputs_missing_b_entry1") is None
    assert registry.async_get_issue(DOMAIN, "surplus_silent_entry2") is not None


async def test_diagnostics_hold_settings_decision_and_readings(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller.entry.runtime_data = controller
    _set_readings(hass, "1200", "55", "0", "standby")
    hass.states.async_set("switch.venus_rs485", "on")
    await controller._tick(dt_util.utcnow())

    diagnostics = await async_get_config_entry_diagnostics(hass, controller.entry)
    assert diagnostics["entry"]["data"] == controller.entry.data
    assert diagnostics["settings"]["dry_run"] is False
    assert diagnostics["status"]["target_mode"] == controller.status.target_mode
    assert diagnostics["status"]["decided_at"] is not None
    assert diagnostics["status"]["control_quality"] == controller.quality_state()
    assert diagnostics["readings"]["sensor.venus_soc"]["state"] == "55"
    assert diagnostics["readings"]["select.venus_force_mode"] is None  # configured, without a state
    assert "Venus" not in diagnostics["readings"]  # the name is not an entity
    await controller.async_stop()
