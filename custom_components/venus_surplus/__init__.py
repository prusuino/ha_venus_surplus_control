"""Venus Surplus Control: runs a Marstek Venus from PV surplus over the
entities of the Marstek Venus Modbus integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .controller import VenusController
from .issues import async_clear_entry_issues

type VenusSurplusConfigEntry = ConfigEntry[VenusController]

PLATFORMS = ["sensor", "binary_sensor", "switch", "number", "select", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: VenusSurplusConfigEntry) -> bool:
    controller = VenusController(hass, entry)
    entry.runtime_data = controller
    await controller.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VenusSurplusConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    controller: VenusController | None = getattr(entry, "runtime_data", None)
    if controller is not None:
        await controller.async_stop()
    if ok:
        async_clear_entry_issues(hass, entry.entry_id)
    return ok
