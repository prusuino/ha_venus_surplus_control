"""Sensors: what the controller decided and the values behind it."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import VenusController
from .entity import VenusEntity

TARGET_MODES = ["charge", "discharge", "stop", "no_data", "paused", "unknown"]
REASONS = ["charge_ok", "charge_parallel", "charge_primary_idle", "discharge_ok", "direct_pv_use", "venus_soc_protect", "cross_trip", "no_condition", "data_not_ready", "manual_override", "manual_charge", "manual_discharge", "manual_discharge_target", "manual_standby", "target_soc_reached", "unknown"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    c: VenusController = entry.runtime_data
    async_add_entities(
        [
            TargetModeSensor(c),
            ReasonSensor(c),
            DecisionSensor(c),
            PowerSensor(c, "surplus_mean", lambda c: c.status.surplus_mean),
            PowerSensor(c, "surplus_without_venus_mean", lambda c: c.status.surplus_ex_venus_mean),
            PowerSensor(c, "charge_headroom", lambda c: c.status.values.get("headroom_w")),
            PowerSensor(c, "house_demand", lambda c: c.status.values.get("house_need_w")),
            PowerSensor(c, "charge_command", lambda c: c.state.last_charge_power),
            PowerSensor(c, "discharge_command", lambda c: c.state.last_discharge_power),
            CounterSensor(c, "watchdog_restores", lambda c: c.status.watchdog_restores),
            CounterSensor(c, "dry_run_commands", lambda c: c.status.dry_run_commands),
        ]
    )


class TargetModeSensor(VenusEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = TARGET_MODES
    _attr_icon = "mdi:state-machine"

    def __init__(self, c: VenusController) -> None:
        super().__init__(c, "target_mode")

    @property
    def native_value(self) -> str:
        return self.controller.status.target_mode if self.controller.status.target_mode in TARGET_MODES else "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        s = self.controller.status
        return {
            "reason": s.reason,
            "decided_at": s.decided_at.isoformat() if s.decided_at else None,
            "last_command": s.last_command,
            "last_command_power": s.last_command_power,
            "last_command_time": s.last_command_time.isoformat() if s.last_command_time else None,
            "dry_run": self.controller.settings.dry_run,
            **self.controller.card_sources(),
        }


class ReasonSensor(VenusEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = REASONS
    _attr_icon = "mdi:comment-question-outline"

    def __init__(self, c: VenusController) -> None:
        super().__init__(c, "reason")

    @property
    def native_value(self) -> str:
        r = self.controller.status.reason
        return r if r in REASONS else "unknown"


class DecisionSensor(VenusEntity, SensorEntity):
    """The last decision in words; the values behind it as attributes."""

    _attr_icon = "mdi:text-box-outline"

    def __init__(self, c: VenusController) -> None:
        super().__init__(c, "last_decision")

    @property
    def native_value(self) -> str:
        return (self.controller.status.text or "")[:255]

    @property
    def extra_state_attributes(self) -> dict:
        return dict(self.controller.status.values)


class PowerSensor(VenusEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, c: VenusController, key: str, getter) -> None:
        super().__init__(c, key)
        self._getter = getter

    @property
    def native_value(self) -> float | None:
        return self._getter(self.controller)


class CounterSensor(VenusEntity, SensorEntity):
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:counter"
    _attr_entity_registry_enabled_default = True

    def __init__(self, c: VenusController, key: str, getter) -> None:
        super().__init__(c, key)
        self._getter = getter

    @property
    def native_value(self) -> int:
        return int(self._getter(self.controller))
