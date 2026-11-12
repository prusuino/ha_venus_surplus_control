"""Buttons: manual charge / discharge / discharge to the target SoC / stop
(switch the override on) and back to auto."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import VenusController
from .entity import VenusEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c: VenusController = entry.runtime_data
    async_add_entities(
        [
            ManualButton(c, "manual_charge", "charge", "mdi:battery-charging-high"),
            ManualButton(c, "manual_discharge", "discharge", "mdi:battery-arrow-down"),
            TargetButton(c),
            ManualButton(c, "manual_stop", "stop", "mdi:stop-circle-outline"),
            ManualButton(c, "back_to_auto", "auto", "mdi:autorenew"),
        ]
    )


class ManualButton(VenusEntity, ButtonEntity):
    def __init__(self, c: VenusController, key: str, action: str, icon: str) -> None:
        super().__init__(c, key)
        self._action = action
        self._attr_icon = icon

    async def async_press(self) -> None:
        await self.controller.async_manual(self._action)


class TargetButton(VenusEntity, ButtonEntity):
    """Discharge until the Venus is at `number.<name>_target_soc`."""

    _attr_icon = "mdi:battery-arrow-down-outline"

    def __init__(self, c: VenusController) -> None:
        super().__init__(c, "discharge_to_target")

    async def async_press(self) -> None:
        await self.controller.async_discharge_to_target()
