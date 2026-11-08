"""Numbers: the thresholds you may want to tune from the dashboard."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_DISCHARGE_LIMIT, DEFAULT_DISCHARGE_LIMIT, DOMAIN
from .controller import VenusController
from .entity import VenusEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c: VenusController = hass.data[DOMAIN][entry.entry_id]
    limit = int(entry.options.get(CONF_DISCHARGE_LIMIT, entry.data.get(CONF_DISCHARGE_LIMIT, DEFAULT_DISCHARGE_LIMIT)))
    async_add_entities(
        [
            SettingNumber(c, "discharge_cap_w", 200, limit, 100, UnitOfPower.WATT, "mdi:battery-arrow-down-outline", NumberDeviceClass.POWER),
            SettingNumber(c, "first_forecast_kwh", 0, 200, 1, UnitOfEnergy.KILO_WATT_HOUR, "mdi:weather-sunny", None),
            SettingNumber(c, "primary_capacity_kwh", 0, 100, 0.1, UnitOfEnergy.KILO_WATT_HOUR, "mdi:battery-high", None),
            SettingNumber(c, "venus_capacity_kwh", 0, 50, 0.01, UnitOfEnergy.KILO_WATT_HOUR, "mdi:battery", None),
            SettingNumber(c, "house_base_load_kw", 0, 5, 0.1, "kW", "mdi:home-lightning-bolt", None),
        ]
    )


class SettingNumber(VenusEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, c: VenusController, key: str, mn: float, mx: float, step: float, unit: str, icon: str, device_class: NumberDeviceClass | None) -> None:
        super().__init__(c, key)
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class

    @property
    def native_value(self) -> float:
        return float(getattr(self.controller.settings, self._key))

    async def async_set_native_value(self, value: float) -> None:
        v: float | int = int(value) if self._key == "discharge_cap_w" else round(value, 2)
        await self.controller.async_set_setting(self._key, v)
