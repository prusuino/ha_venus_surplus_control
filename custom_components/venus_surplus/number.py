"""Numbers: the thresholds you may want to tune from the dashboard."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import VenusController
from .entity import VenusEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c: VenusController = entry.runtime_data
    limit = c.discharge_limit_w  # the device limit, or the feed-in limit if lower
    cfg = EntityCategory.CONFIG  # set once: shown under "Configuration" on the device page
    async_add_entities(
        [
            SettingNumber(c, "discharge_cap_w", 200, limit, 100, UnitOfPower.WATT, "mdi:battery-arrow-down-outline", NumberDeviceClass.POWER),
            SettingNumber(c, "target_soc", 12, 100, 1, PERCENTAGE, "mdi:battery-arrow-down", None),
            SettingNumber(c, "charge_start_w", 100, 1500, 50, UnitOfPower.WATT, "mdi:battery-charging-low", NumberDeviceClass.POWER, category=cfg),
            SettingNumber(c, "charge_reserve_w", 0, 500, 10, UnitOfPower.WATT, "mdi:battery-arrow-up-outline", NumberDeviceClass.POWER, category=cfg),
            SettingNumber(c, "primary_first_soc", 0, 100, 5, PERCENTAGE, "mdi:battery-sync", None, category=cfg),
            SettingNumber(c, "first_forecast_kwh", 0, 200, 1, UnitOfEnergy.KILO_WATT_HOUR, "mdi:weather-sunny", None, category=cfg),
            SettingNumber(c, "primary_capacity_kwh", 0, 100, 0.1, UnitOfEnergy.KILO_WATT_HOUR, "mdi:battery-high", None, category=cfg),
            SettingNumber(c, "venus_capacity_kwh", 0, 50, 0.01, UnitOfEnergy.KILO_WATT_HOUR, "mdi:battery", None, category=cfg),
            # stored in kW (as before), shown in W like the other power settings
            SettingNumber(c, "house_base_load_kw", 0, 5000, 50, UnitOfPower.WATT, "mdi:home-lightning-bolt", NumberDeviceClass.POWER, scale=1000, category=cfg),
        ]
    )


class SettingNumber(VenusEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(self, c: VenusController, key: str, mn: float, mx: float, step: float, unit: str, icon: str, device_class: NumberDeviceClass | None, scale: float = 1, category: EntityCategory | None = None) -> None:
        super().__init__(c, key)
        self._attr_entity_category = category
        self._scale = scale  # shown value = stored value x scale
        self._attr_native_min_value = mn
        self._attr_native_max_value = mx
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class

    @property
    def native_value(self) -> float:
        return round(float(getattr(self.controller.settings, self._key)) * self._scale, 2)

    async def async_set_native_value(self, value: float) -> None:
        value = value / self._scale
        v: float | int = int(value) if self._key in ("discharge_cap_w", "charge_reserve_w", "charge_start_w", "primary_first_soc", "target_soc") else round(value, 2)
        await self.controller.async_set_setting(self._key, v)
