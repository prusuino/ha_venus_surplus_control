"""A grid meter as surplus sensor shows what is left after the first battery.
The controller takes the first battery's own flow out, so that it sees the
house demand while that battery covers it, and the full surplus while it
absorbs the sun."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import CONF_PRIMARY_POWER, CONF_PRIMARY_SOC, CONF_SURPLUS_INVERT, DOMAIN
from custom_components.venus_surplus.controller import VenusController

from .test_repairs import DATA, _set_readings


def _controller(hass, **extra) -> VenusController:
    data = {**DATA, CONF_SURPLUS_INVERT: True, CONF_PRIMARY_POWER: "sensor.first_power", CONF_PRIMARY_SOC: "sensor.first_soc", **extra}
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=data)
    entry.add_to_hass(hass)
    return VenusController(hass, entry)


async def test_the_house_demand_is_seen_while_the_first_battery_covers_it(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    _set_readings(hass, "5", "80", "0", "standby")  # the meter: next to nothing, the first battery holds it there
    hass.states.async_set("sensor.first_power", "250")  # ... by delivering 250 W
    hass.states.async_set("sensor.first_soc", "60")
    inputs = controller.inputs(dt_util.utcnow())
    assert inputs.surplus_instant == -255 and inputs.primary_power == 250
    await controller.async_stop()


async def test_the_full_surplus_is_seen_while_the_first_battery_absorbs_it(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    _set_readings(hass, "-300", "50", "0", "standby")  # 300 W exported
    hass.states.async_set("sensor.first_power", "-2500")  # and 2500 W into the first battery
    hass.states.async_set("sensor.first_soc", "60")
    assert controller.inputs(dt_util.utcnow()).surplus_instant == 2800
    await controller.async_stop()


async def test_without_a_first_battery_reading_the_meter_is_taken_as_it_is(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    _set_readings(hass, "400", "50", "0", "standby")
    hass.states.async_set("sensor.first_power", "unavailable")
    hass.states.async_set("sensor.first_soc", "60")
    assert controller.inputs(dt_util.utcnow()).surplus_instant == -400
    await controller.async_stop()


async def test_a_surplus_sensor_that_is_no_meter_is_not_touched(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass, **{CONF_SURPLUS_INVERT: False})
    _set_readings(hass, "-255", "80", "0", "standby")  # PV minus consumption already says it all
    hass.states.async_set("sensor.first_power", "250")
    hass.states.async_set("sensor.first_soc", "60")
    assert controller.inputs(dt_util.utcnow()).surplus_instant == -255
    await controller.async_stop()
