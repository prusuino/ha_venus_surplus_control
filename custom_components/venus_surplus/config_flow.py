"""Setup: pick the entities of your Venus and your house, no YAML."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AC_CHARGE_LIMIT,
    CONF_CHARGE_POWER,
    CONF_CONNECTION,
    CONF_DISCHARGE_LIMIT,
    CONF_DISCHARGE_POWER,
    CONF_FORCE_MODE,
    CONF_FORECAST_FACTOR,
    CONF_FORECAST_REMAINING,
    CONF_FORECAST_TODAY,
    CONF_MODBUS_ENTRY,
    CONF_NAME,
    CONF_PRIMARY_POWER,
    CONF_PRIMARY_POWER_INVERT,
    CONF_PRIMARY_SOC,
    CONF_RS485,
    CONF_SURPLUS,
    CONF_SURPLUS_INVERT,
    CONF_TICK_SECONDS,
    CONF_TOTAL_CHARGE_LIMIT,
    CONF_VENUS_AC,
    CONF_VENUS_AC_INVERT,
    CONF_VENUS_CAPACITY,
    CONF_VENUS_PV,
    CONF_VENUS_SOC,
    CONF_VENUS_STATE,
    DEFAULT_AC_CHARGE_LIMIT,
    DEFAULT_DISCHARGE_LIMIT,
    DEFAULT_FORECAST_FACTOR,
    DEFAULT_TICK_SECONDS,
    DEFAULT_TOTAL_CHARGE_LIMIT,
    DOMAIN,
)

_SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
_SENSOR_OPT = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _entity(domain: str, multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain, multiple=multiple))


def _required_schema(defaults: dict[str, Any]) -> vol.Schema:
    d = defaults.get
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=d(CONF_NAME, "Venus")): selector.TextSelector(),
            vol.Required(CONF_SURPLUS, default=d(CONF_SURPLUS)): _entity("sensor"),
            vol.Required(CONF_SURPLUS_INVERT, default=bool(d(CONF_SURPLUS_INVERT, False))): selector.BooleanSelector(),
            vol.Required(CONF_FORCE_MODE, default=d(CONF_FORCE_MODE)): _entity("select"),
            vol.Required(CONF_CHARGE_POWER, default=d(CONF_CHARGE_POWER)): _entity("number"),
            vol.Required(CONF_DISCHARGE_POWER, default=d(CONF_DISCHARGE_POWER)): _entity("number"),
            vol.Required(CONF_RS485, default=d(CONF_RS485)): _entity("switch"),
            vol.Required(CONF_VENUS_SOC, default=d(CONF_VENUS_SOC)): _entity("sensor"),
            vol.Required(CONF_VENUS_AC, default=d(CONF_VENUS_AC)): _entity("sensor"),
            vol.Required(CONF_VENUS_AC_INVERT, default=bool(d(CONF_VENUS_AC_INVERT, False))): selector.BooleanSelector(),
            vol.Required(CONF_VENUS_STATE, default=d(CONF_VENUS_STATE)): _entity("sensor"),
        }
    )


def _optional_schema(defaults: dict[str, Any]) -> vol.Schema:
    d = defaults.get

    def opt(key: str, sel: Any) -> tuple:
        v = d(key)
        return (vol.Optional(key, description={"suggested_value": v}) if v is not None else vol.Optional(key)), sel

    schema: dict = {}
    for key, sel in (
        opt(CONF_VENUS_PV, _entity("sensor", multiple=True)),
        opt(CONF_VENUS_CAPACITY, _entity("sensor")),
        opt(CONF_PRIMARY_POWER, _entity("sensor")),
    ):
        schema[key] = sel
    schema[vol.Required(CONF_PRIMARY_POWER_INVERT, default=bool(d(CONF_PRIMARY_POWER_INVERT, False)))] = selector.BooleanSelector()
    for key, sel in (
        opt(CONF_PRIMARY_SOC, _entity("sensor")),
        opt(CONF_FORECAST_TODAY, _entity("sensor")),
        opt(CONF_FORECAST_REMAINING, _entity("sensor")),
    ):
        schema[key] = sel
    schema[vol.Required(CONF_FORECAST_FACTOR, default=float(d(CONF_FORECAST_FACTOR, DEFAULT_FORECAST_FACTOR)))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=0.3, max=1.2, step=0.05, mode=selector.NumberSelectorMode.BOX)
    )
    for key, sel in (
        opt(CONF_CONNECTION, _entity("binary_sensor")),
        opt(CONF_MODBUS_ENTRY, selector.ConfigEntrySelector(selector.ConfigEntrySelectorConfig(integration="marstek_modbus"))),
    ):
        schema[key] = sel
    schema[vol.Required(CONF_AC_CHARGE_LIMIT, default=int(d(CONF_AC_CHARGE_LIMIT, DEFAULT_AC_CHARGE_LIMIT)))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=100, max=5000, step=100, unit_of_measurement="W", mode=selector.NumberSelectorMode.BOX)
    )
    schema[vol.Required(CONF_TOTAL_CHARGE_LIMIT, default=int(d(CONF_TOTAL_CHARGE_LIMIT, DEFAULT_TOTAL_CHARGE_LIMIT)))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=100, max=5000, step=100, unit_of_measurement="W", mode=selector.NumberSelectorMode.BOX)
    )
    schema[vol.Required(CONF_DISCHARGE_LIMIT, default=int(d(CONF_DISCHARGE_LIMIT, DEFAULT_DISCHARGE_LIMIT)))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=200, max=5000, step=100, unit_of_measurement="W", mode=selector.NumberSelectorMode.BOX)
    )
    schema[vol.Required(CONF_TICK_SECONDS, default=int(d(CONF_TICK_SECONDS, DEFAULT_TICK_SECONDS)))] = selector.NumberSelector(
        selector.NumberSelectorConfig(min=15, max=120, step=5, unit_of_measurement="s", mode=selector.NumberSelectorMode.BOX)
    )
    return vol.Schema(schema)


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional selections so `None` never ends up in the entry."""
    out = {}
    for k, v in user_input.items():
        if v in (None, "", []):
            continue
        out[k] = v
    return out


class VenusSurplusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = _clean(user_input)
            return await self.async_step_optional()
        return self.async_show_form(step_id="user", data_schema=_required_schema(self._data), errors=errors)

    async def async_step_optional(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            data = {**self._data, **_clean(user_input)}
            for key in (CONF_SURPLUS_INVERT, CONF_VENUS_AC_INVERT, CONF_PRIMARY_POWER_INVERT):
                data[key] = bool(data.get(key, False))
            await self.async_set_unique_id(f"{DOMAIN}_{data[CONF_FORCE_MODE]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=data[CONF_NAME], data=data)
        return self.async_show_form(step_id="optional", data_schema=_optional_schema(self._data))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return VenusSurplusOptionsFlow()


class VenusSurplusOptionsFlow(config_entries.OptionsFlow):
    """Everything can be changed later: the required entities, the
    optional ones and the limits. Values land in options; the controller
    reads options first, then data."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data = _clean(user_input)
            return await self.async_step_optional()
        return self.async_show_form(step_id="init", data_schema=_required_schema(self._current()))

    async def async_step_optional(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            data = {**self._data, **_clean(user_input)}
            for key in (CONF_SURPLUS_INVERT, CONF_VENUS_AC_INVERT, CONF_PRIMARY_POWER_INVERT):
                data[key] = bool(data.get(key, False))
            # an optional entity removed in the form must disappear from the entry
            merged = dict(self.config_entry.options)
            for key in (CONF_VENUS_PV, CONF_VENUS_CAPACITY, CONF_PRIMARY_POWER, CONF_PRIMARY_SOC, CONF_FORECAST_TODAY, CONF_FORECAST_REMAINING, CONF_CONNECTION, CONF_MODBUS_ENTRY):
                merged.pop(key, None)
            merged.update(data)
            if any(key in self.config_entry.data and key not in data for key in (CONF_PRIMARY_POWER, CONF_PRIMARY_SOC, CONF_FORECAST_TODAY, CONF_FORECAST_REMAINING, CONF_VENUS_PV, CONF_VENUS_CAPACITY, CONF_CONNECTION, CONF_MODBUS_ENTRY)):
                new_data = {k: v for k, v in self.config_entry.data.items() if k in data or k not in (CONF_PRIMARY_POWER, CONF_PRIMARY_SOC, CONF_FORECAST_TODAY, CONF_FORECAST_REMAINING, CONF_VENUS_PV, CONF_VENUS_CAPACITY, CONF_CONNECTION, CONF_MODBUS_ENTRY)}
                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data=merged)
        return self.async_show_form(step_id="optional", data_schema=_optional_schema(self._current()))
