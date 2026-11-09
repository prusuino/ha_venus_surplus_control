"""Common base: one device per controller, updates pushed by the controller."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, VERSION
from .controller import VenusController, signal_update


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        sw_version=VERSION,
        name=entry.title,
        manufacturer="Venus Surplus Control",
        model="Surplus controller",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://github.com/prusuino/ha_venus_surplus_control",
    )


class VenusEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: VenusController, key: str) -> None:
        self.controller = controller
        self._key = key
        self._attr_translation_key = key
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_device_info = device_info(controller.entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, signal_update(self.controller.entry.entry_id), self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()
