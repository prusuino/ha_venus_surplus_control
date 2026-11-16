"""Sensors: what the controller decided and the values behind it."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import VenusController
from .entity import VenusEntity
from .quality import STATES as QUALITY_STATES, WINDOW as QUALITY_WINDOW

TARGET_MODES = ["charge", "discharge", "stop", "no_data", "paused", "unknown"]
REASONS = ["charge_ok", "charge_parallel", "charge_primary_idle", "charge_primary_limited", "discharge_ok", "discharge_primary_idle", "direct_pv_use", "venus_soc_protect", "primary_first", "cross_trip", "venus_full", "no_condition", "data_not_ready", "manual_override", "manual_charge", "manual_discharge", "manual_discharge_target", "manual_standby", "target_soc_reached", "unknown"]


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
            NightLoadSensor(c),
            QualitySensor(c),
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


class NightLoadSensor(PowerSensor):
    """What the controller has learned about the house at night, and the
    minimum discharge power it takes from it."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:home-clock-outline"

    def __init__(self, c: VenusController) -> None:
        super().__init__(c, "night_load", lambda c: c.learned_night_load_w)

    @property
    def extra_state_attributes(self) -> dict:
        c = self.controller
        return {
            "nights": len(c._night_medians),
            "per_night_w": [round(v) for v in c._night_medians],
            "minimum_discharge_power_w": c.discharge_min_w,
            "minimum_discharge_power_automatic": int(c.settings.discharge_min_w) <= 0,
        }


class QualitySensor(VenusEntity, SensorEntity):
    """How well the control runs: steady, changing mode too often, or a
    Venus that does less than it was told."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = QUALITY_STATES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-bell-curve"

    def __init__(self, c: VenusController) -> None:
        super().__init__(c, "control_quality")

    @property
    def native_value(self) -> str:
        return self.controller.quality_state()

    @property
    def extra_state_attributes(self) -> dict:
        q = self.controller.quality
        return {
            "mode_changes": q.mode_changes,
            "window_minutes": round(QUALITY_WINDOW.total_seconds() / 60),
            "command_followed_percent": q.follow_percent,
            "cell_temperature_min": self.controller.cell_temperatures()[0],
            "cell_temperature_max": self.controller.cell_temperatures()[1],
            "surplus_longest_gap_seconds": round(self.controller.silence.longest_gap_s),
            "surplus_silence_limit_minutes": round(self.controller.silence.limit_s / 60) if self.controller.silence.ready else None,
            "dry_run": self.controller.settings.dry_run,
        }


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
