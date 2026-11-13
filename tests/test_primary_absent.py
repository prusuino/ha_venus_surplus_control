"""First battery switched off: with the option set, the controller carries on
with the Venus alone once the readings have been missing for five minutes."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import CONF_PRIMARY_MISSING_ALONE, CONF_PRIMARY_POWER, CONF_PRIMARY_SOC, DOMAIN
from custom_components.venus_surplus.controller import PRIMARY_ABSENT_AFTER, VenusController

from .test_repairs import DATA

PRIMARY = {CONF_PRIMARY_POWER: "sensor.first_power", CONF_PRIMARY_SOC: "sensor.first_soc"}


def _controller(hass, **extra) -> VenusController:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**DATA, **PRIMARY, **extra})
    entry.add_to_hass(hass)
    # plenty of surplus, Venus half full and idle
    hass.states.async_set("sensor.pv_surplus", "1500")
    hass.states.async_set("sensor.venus_soc", "50")
    hass.states.async_set("sensor.venus_ac_power", "0")
    hass.states.async_set("sensor.venus_state", "standby")
    hass.states.async_set("sensor.first_power", "unavailable")
    hass.states.async_set("sensor.first_soc", "unavailable")
    return VenusController(hass, entry)


async def _run(controller, minutes, monkeypatch):
    """Tick once now and once `minutes` later."""
    start = dt_util.utcnow()
    await controller._tick(start)
    monkeypatch.setattr(dt_util, "utcnow", lambda: start + timedelta(minutes=minutes))
    await controller._tick(dt_util.utcnow())


async def test_without_the_option_the_controller_waits(hass: HomeAssistant, enable_custom_integrations, monkeypatch) -> None:
    controller = _controller(hass)
    await _run(controller, 30, monkeypatch)
    assert controller.status.target_mode == "no_data"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"primary_missing_{controller.entry.entry_id}") is None
    await controller.async_stop()


async def test_with_the_option_the_venus_carries_on_alone(hass: HomeAssistant, enable_custom_integrations, monkeypatch) -> None:
    controller = _controller(hass, **{CONF_PRIMARY_MISSING_ALONE: True})
    registry = ir.async_get(hass)
    start = dt_util.utcnow()

    # the first minutes are a grace period: a short outage changes nothing
    await controller._tick(start)
    assert controller.status.target_mode == "no_data"
    monkeypatch.setattr(dt_util, "utcnow", lambda: start + PRIMARY_ABSENT_AFTER - timedelta(seconds=30))
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "no_data"

    # after five minutes the Venus charges from the surplus by itself
    monkeypatch.setattr(dt_util, "utcnow", lambda: start + PRIMARY_ABSENT_AFTER + timedelta(seconds=30))
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "charge"
    assert controller.status.values["first_battery_readings_missing"] is True
    issue = registry.async_get_issue(DOMAIN, f"primary_missing_{controller.entry.entry_id}")
    assert issue is not None and issue.translation_placeholders == {"entities": "sensor.first_power, sensor.first_soc"}

    # the readings return: the first battery counts again at once
    hass.states.async_set("sensor.first_power", "0")
    hass.states.async_set("sensor.first_soc", "40")
    await controller._tick(dt_util.utcnow())
    assert "first_battery_readings_missing" not in controller.status.values
    assert registry.async_get_issue(DOMAIN, f"primary_missing_{controller.entry.entry_id}") is None

    # and a new outage starts a new grace period
    hass.states.async_set("sensor.first_soc", "unavailable")
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "no_data"
    await controller.async_stop()
