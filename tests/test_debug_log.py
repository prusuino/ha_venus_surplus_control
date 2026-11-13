"""Debug log: one line per tick while debug logging is on, nothing otherwise."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import DOMAIN
from custom_components.venus_surplus.controller import VenusController

from .test_repairs import DATA, _set_readings

LOGGER = "custom_components.venus_surplus.controller"


async def test_each_tick_writes_one_debug_line(hass: HomeAssistant, enable_custom_integrations, caplog) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=DATA)
    entry.add_to_hass(hass)
    controller = VenusController(hass, entry)
    _set_readings(hass, "1500", "50", "0", "standby")

    caplog.set_level(logging.INFO, logger=LOGGER)
    await controller._tick(dt_util.utcnow())
    assert not [r for r in caplog.records if "tick |" in r.getMessage()]

    caplog.set_level(logging.DEBUG, logger=LOGGER)
    await controller._tick(dt_util.utcnow())
    lines = [r.getMessage() for r in caplog.records if "tick |" in r.getMessage()]
    assert len(lines) == 1
    assert "target=charge" in lines[0] and "reason=charge_ok" in lines[0] and "dry_run=True" in lines[0]
    assert "venus soc=50.0" in lines[0] and "headroom=1300" in lines[0]
    # numbers and flags only: no entity of the setup is named
    assert "sensor." not in lines[0] and "select." not in lines[0]
    await controller.async_stop()
