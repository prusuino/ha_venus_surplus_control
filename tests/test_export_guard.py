"""The export guard of a Venus that is the only source is a setting (0-50 W)."""
from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import DOMAIN
from custom_components.venus_surplus.engine import Params, State, decide

from .test_charge_power import DATA, sun_timer
from .test_discharge_hold import _helping, _night


def _alone(guard: float) -> Params:
    return Params(has_primary=False, discharge_min_w=100, sole_export_guard_w=guard)


def test_the_default_is_10_w():
    d = decide(_night(237), Params(has_primary=False, discharge_min_w=100), State())
    assert d.power == 220 and d.values["discharge_reserve_w"] == 10


def test_without_a_guard_the_venus_goes_up_to_the_demand():
    assert decide(_night(237), _alone(0), State()).power == 230
    # never above the demand, also when it is a round number
    assert decide(_night(240), _alone(0), State()).power == 240


def test_a_larger_guard_leaves_more_to_the_grid():
    assert decide(_night(237), _alone(30), State()).power == 200
    assert decide(_night(900), _alone(50), State()).power == 850


def test_a_running_discharge_follows_the_guard():
    d = decide(_night(400), _alone(0), State())
    assert d.power == 400
    # the demand drops: the command comes down to it, not below
    d = decide(_night(300, venus_ac=400.0, state="discharging"), _alone(0), d.state)
    assert d.power == 300


def test_a_raised_guard_lowers_the_standing_command_at_once():
    d = decide(_night(237), _alone(0), State())
    assert d.power == 230
    # same guard: the command stands
    d = decide(_night(237, venus_ac=230.0, state="discharging"), _alone(0), d.state)
    assert d.command is None and d.state.last_discharge_power == 230
    # the guard is raised while the demand stays where it is
    d = decide(_night(237, venus_ac=230.0, state="discharging"), _alone(30), d.state)
    assert d.command == "discharge" and d.power == 200
    # and lowered again: up by the 30 W
    d = decide(_night(237, venus_ac=200.0, state="discharging"), _alone(0), d.state)
    assert d.command == "discharge" and d.power == 230


def test_next_to_a_delivering_first_battery_the_setting_has_no_effect():
    a = decide(_helping(220), Params(has_primary=True, discharge_min_w=100, sole_export_guard_w=0), State())
    b = decide(_helping(220), Params(has_primary=True, discharge_min_w=100, sole_export_guard_w=50), State())
    assert a.power == b.power == 150


@sun_timer
async def test_the_number_sets_the_guard_and_survives_a_reload(hass, enable_custom_integrations, expected_lingering_timers: bool) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    controller = entry.runtime_data
    assert controller.params().sole_export_guard_w == 10

    state = hass.states.get("number.venus_export_guard_venus_alone")
    assert state is not None and float(state.state) == 10
    await hass.services.async_call("number", "set_value", {"entity_id": "number.venus_export_guard_venus_alone", "value": 0}, blocking=True)
    assert controller.settings.export_guard_w == 0 and controller.params().sole_export_guard_w == 0

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.settings.export_guard_w == 0
