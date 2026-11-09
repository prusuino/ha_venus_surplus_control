"""Switches: manual override (pauses the master) and dry run (decide and
log, but write nothing to the Venus)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import VenusController
from .entity import VenusEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c: VenusController = entry.runtime_data
    async_add_entities([SettingSwitch(c, "manual_override", "mdi:hand-back-right"), SettingSwitch(c, "dry_run", "mdi:test-tube")])


class SettingSwitch(VenusEntity, SwitchEntity):
    def __init__(self, c: VenusController, key: str, icon: str) -> None:
        super().__init__(c, key)
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.controller.settings, self._key))

    async def async_turn_on(self, **kwargs) -> None:
        await self.controller.async_set_setting(self._key, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.controller.async_set_setting(self._key, False)
