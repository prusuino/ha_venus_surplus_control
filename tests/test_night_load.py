"""The controller learns what the house draws at night (a diagnostic value);
the minimum discharge power is 100 W unless it is set by hand."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import DOMAIN
from custom_components.venus_surplus.controller import VenusController

from .test_repairs import DATA, _set_readings


def _controller(hass) -> VenusController:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=DATA)
    entry.add_to_hass(hass)
    return VenusController(hass, entry)


async def _night(hass, controller, house_w, ticks=300):
    """A night of `ticks` ticks (30 s each) with the house drawing house_w, then sunrise."""
    hass.states.async_set("sun.sun", "below_horizon")
    for n in range(ticks):
        _set_readings(hass, str(-(house_w + (40 if n % 2 else -40))), "50", "0", "standby")
        await controller._tick(dt_util.utcnow())
    hass.states.async_set("sun.sun", "above_horizon")
    await controller._tick(dt_util.utcnow())
    await hass.async_block_till_done()


async def test_nothing_learned_yet(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    assert controller.learned_night_load_w is None
    assert controller.discharge_min_w == 100
    await controller.async_stop()


async def test_a_night_is_learned_and_survives_a_restart(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    await _night(hass, controller, 240)
    assert controller.learned_night_load_w == 240
    assert controller.discharge_min_w == 100
    assert controller.params().discharge_min_w == 100

    # it survives a restart
    restarted = VenusController(hass, controller.entry)
    await restarted.async_start()
    assert restarted.learned_night_load_w == 240 and restarted.discharge_min_w == 100
    await restarted.async_stop()
    await controller.async_stop()
    await hass.async_block_till_done()


async def test_the_minimum_does_not_depend_on_the_night_load(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    await _night(hass, controller, 600)
    assert controller.learned_night_load_w == 600
    assert controller.discharge_min_w == 100
    await controller.async_stop()


async def test_a_short_night_is_not_counted(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    await _night(hass, controller, 240, ticks=60)  # half an hour, e.g. a restart before sunrise
    assert controller.learned_night_load_w is None
    await controller.async_stop()


async def test_the_venus_own_discharge_is_taken_out(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    hass.states.async_set("sun.sun", "below_horizon")
    for _ in range(300):
        # the house draws 500 W, the Venus delivers 400 W of it: the sensor shows -100 W
        _set_readings(hass, "-100", "50", "400", "discharging")
        await controller._tick(dt_util.utcnow())
    hass.states.async_set("sun.sun", "above_horizon")
    await controller._tick(dt_util.utcnow())
    assert controller.learned_night_load_w == 500
    await controller.async_stop()
    await hass.async_block_till_done()


async def test_a_value_set_by_hand_wins(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    await _night(hass, controller, 240)
    await controller.async_set_setting("discharge_min_w", 300)
    assert controller.discharge_min_w == 300
    await controller.async_set_setting("discharge_min_w", 0)
    assert controller.discharge_min_w == 100
    await controller.async_stop()
    await hass.async_block_till_done()
