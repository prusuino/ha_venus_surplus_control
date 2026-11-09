"""Binary sensors: the states an automation wants to react to."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import VenusController
from .entity import VenusEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c: VenusController = entry.runtime_data
    async_add_entities(
        [
            FlagSensor(c, "venus_first", lambda c: c.status.values.get("venus_first"), "mdi:battery-arrow-up"),
            FlagSensor(c, "parallel_charging_allowed", lambda c: c.status.values.get("parallel_allowed"), "mdi:battery-plus-variant"),
            FlagSensor(c, "cross_charging_blocked", lambda c: c.status.values.get("cross_trip") or (c.status.values.get("block_charge") and c.status.values.get("headroom_w", 0) >= 400) or (c.status.values.get("block_discharge") and c.status.values.get("house_need_w", 0) >= 200), "mdi:swap-horizontal-circle-outline", None),
            FlagSensor(c, "charging", lambda c: c.status.target_mode == "charge", "mdi:battery-charging"),
            FlagSensor(c, "discharging", lambda c: c.status.target_mode == "discharge", "mdi:battery-arrow-down"),
        ]
    )


class FlagSensor(VenusEntity, BinarySensorEntity):
    def __init__(self, c: VenusController, key: str, getter, icon: str, device_class: BinarySensorDeviceClass | None = None) -> None:
        super().__init__(c, key)
        self._getter = getter
        self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        v = self._getter(self.controller)
        return None if v is None else bool(v)
