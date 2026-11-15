"""A surplus sensor that is silent for far longer than it has ever been is not
believed; the limits stop at what the number entities take; a Venus that
ignores its command is named."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import CONF_AC_CHARGE_LIMIT, CONF_CONNECTION, CONF_DISCHARGE_LIMIT, DOMAIN
from custom_components.venus_surplus.controller import NOT_RESPONDING_ISSUE_TICKS, VenusController
from custom_components.venus_surplus.silence import MIN_LIMIT_S, OBSERVE_S, SilenceWatch

from .test_repairs import DATA, _set_readings

T0 = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- the watch
def _feed(w: SilenceWatch, start: datetime, seconds: int, every: int, tick: int = 30, day: str = "d1") -> datetime:
    """Run the watch for `seconds` behind a sensor that reports every `every` seconds."""
    now = start
    for n in range(0, seconds, tick):
        now = start + timedelta(seconds=n)
        reported = start + timedelta(seconds=(n // every) * every)
        assert w.update("sensor.s", reported, now, day, tick) is False, f"at {n} s"
    return now + timedelta(seconds=tick)


def test_nothing_is_judged_in_the_first_day():
    w = SilenceWatch()
    for n in range(0, 20 * 3600, 30):  # one report, then silence for 20 hours
        assert w.update("sensor.s", T0, T0 + timedelta(seconds=n), "d1", 30) is False
    assert not w.ready


def test_fast_sensor_is_silent_after_ten_minutes():
    w = SilenceWatch()
    now = _feed(w, T0, int(OBSERVE_S), every=30)
    assert w.ready and w.longest_gap_s == 30 and w.limit_s == MIN_LIMIT_S
    last = now - timedelta(seconds=30)
    assert w.update("sensor.s", last, last + timedelta(seconds=MIN_LIMIT_S - 30), "d1", 30) is False
    assert w.update("sensor.s", last, last + timedelta(seconds=MIN_LIMIT_S), "d1", 30) is True
    assert w.update("sensor.s", last + timedelta(seconds=MIN_LIMIT_S + 30), last + timedelta(seconds=MIN_LIMIT_S + 30), "d1", 30) is False


def test_sensor_that_reports_on_change_gets_a_limit_to_match():
    w = SilenceWatch()
    now = _feed(w, T0, int(OBSERVE_S), every=1500)  # quiet for 25 minutes at a time
    assert w.longest_gap_s == 1500 and w.limit_s == 4500
    last = now - timedelta(seconds=30)
    assert w.update("sensor.s", last, last + timedelta(seconds=4400), "d1", 30) is False
    assert w.update("sensor.s", last, last + timedelta(seconds=4500), "d1", 30) is True


def test_a_judged_silence_raises_the_limit_only_by_half():
    w = SilenceWatch()
    now = _feed(w, T0, int(OBSERVE_S), every=30)
    last = now - timedelta(seconds=30)
    assert w.update("sensor.s", last, last + timedelta(hours=5), "d1", 30) is True
    back = last + timedelta(hours=5, seconds=30)
    assert w.update("sensor.s", back, back, "d1", 30) is False
    assert w.limit_s == 1.5 * MIN_LIMIT_S  # not 15 hours


def test_days_roll_and_old_gaps_age_out():
    w = SilenceWatch()
    now = _feed(w, T0, int(OBSERVE_S), every=1500, day="d0")
    for d in range(1, 10):  # the first of these days still holds the gap at the change of rhythm
        now = _feed(w, now, 3600, every=30, day=f"d{d}")
    assert len(w.days) == 7 and w.longest_gap_s <= 60 and w.limit_s == MIN_LIMIT_S


def test_another_sensor_starts_over_and_the_state_survives_a_restart():
    w = SilenceWatch()
    _feed(w, T0, int(OBSERVE_S), every=1500)
    restored = SilenceWatch(w.to_dict())
    assert restored.ready and restored.limit_s == 4500 and restored.entity == "sensor.s"
    assert restored.update("sensor.other", T0, T0 + timedelta(days=3), "d9", 30) is False
    assert not restored.ready and restored.longest_gap_s == 0
    assert SilenceWatch({"days": "x", "entity": 5}).limit_s == MIN_LIMIT_S


# ---------------------------------------------------------------- controller
def _controller(hass, **extra) -> VenusController:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data={**DATA, **extra})
    entry.add_to_hass(hass)
    return VenusController(hass, entry)


async def test_silent_surplus_sensor_stops_the_controller(hass: HomeAssistant, enable_custom_integrations, monkeypatch) -> None:
    controller = _controller(hass)
    registry = ir.async_get(hass)
    issue_id = f"surplus_silent_{controller.entry.entry_id}"
    _set_readings(hass, "1500", "50", "0", "standby")
    start = dt_util.utcnow()
    await controller._tick(start)
    assert controller.status.target_mode == "charge"

    # in the first day silence is not judged
    monkeypatch.setattr(dt_util, "utcnow", lambda: start + timedelta(minutes=30))
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "charge" and controller.silence.ready is False

    # after it, a sensor known to report often counts as silent after 10 minutes
    controller.silence.observed_s = OBSERVE_S
    hass.states.async_set("sensor.pv_surplus", "1500", force_update=True)
    reported = hass.states.get("sensor.pv_surplus").last_reported
    monkeypatch.setattr(dt_util, "utcnow", lambda: reported + timedelta(seconds=MIN_LIMIT_S - 45))
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "charge"
    assert registry.async_get_issue(DOMAIN, issue_id) is None

    monkeypatch.setattr(dt_util, "utcnow", lambda: reported + timedelta(seconds=MIN_LIMIT_S + 45))
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "no_data" and controller.status.values["surplus_silent"] is True
    assert "sensor.pv_surplus" in controller.missing_inputs()
    issue = registry.async_get_issue(DOMAIN, issue_id)
    assert issue is not None and issue.translation_placeholders == {"entity": "sensor.pv_surplus", "minutes": "10"}
    await controller._tick(dt_util.utcnow())
    assert controller.state.last_charge_power == 0 and controller.status.last_command == "standby"

    # the same value reported again is a reading
    hass.states.async_set("sensor.pv_surplus", "1500", force_update=True)
    monkeypatch.setattr(dt_util, "utcnow", lambda: hass.states.get("sensor.pv_surplus").last_reported + timedelta(seconds=5))
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode != "no_data"
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    await controller.async_stop()


async def test_values_kept_over_a_lost_modbus_connection_are_not_believed(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass, **{CONF_CONNECTION: "binary_sensor.venus_modbus"})
    hass.states.async_set("binary_sensor.venus_modbus", "on")
    _set_readings(hass, "1500", "50", "0", "standby")
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "charge"

    # the Venus restarts: the sensors keep their last values, only the connection sensor tells
    _set_readings(hass, "1500", "50", "-1000", "charging")
    hass.states.async_set("binary_sensor.venus_modbus", "off")
    assert controller.venus_connected is False
    assert controller.missing_inputs() == ["binary_sensor.venus_modbus"]
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "no_data"
    await controller._tick(dt_util.utcnow())
    assert controller.state.last_charge_power == 0 and controller.status.last_command == "standby"

    hass.states.async_set("binary_sensor.venus_modbus", "on")
    _set_readings(hass, "1500", "50", "0", "standby")
    await controller._tick(dt_util.utcnow())
    assert controller.status.target_mode == "charge"
    # a connection sensor without a state decides nothing
    hass.states.async_set("binary_sensor.venus_modbus", "unavailable")
    assert controller.venus_connected is True
    await controller.async_stop()


async def test_limits_stop_at_what_the_number_entities_take(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass, **{CONF_AC_CHARGE_LIMIT: 2500, CONF_DISCHARGE_LIMIT: 2500})
    assert controller.params().ac_charge_limit_w == 2500 and controller.discharge_limit_w == 2500  # no entity yet: no cap
    hass.states.async_set("number.venus_charge_power", "0", {"min": 0, "max": 800})
    hass.states.async_set("number.venus_discharge_power", "0", {"min": 0, "max": 1500})
    assert controller.params().ac_charge_limit_w == 800 and controller.discharge_limit_w == 1500
    hass.states.async_set("number.venus_charge_power", "0", {"min": 0, "max": 100})  # a helper left at its default says nothing
    assert controller.params().ac_charge_limit_w == 2500
    await controller.async_stop()


async def test_venus_that_ignores_its_command_is_named(hass: HomeAssistant, enable_custom_integrations) -> None:
    controller = _controller(hass)
    controller.settings.dry_run = False
    hass.services.async_register("number", "set_value", lambda call: None)
    hass.services.async_register("select", "select_option", lambda call: None)
    hass.services.async_register("logbook", "log", lambda call: None)
    registry = ir.async_get(hass)
    issue_id = f"venus_not_responding_{controller.entry.entry_id}"
    _set_readings(hass, "1500", "50", "0", "standby")
    await controller._tick(dt_util.utcnow())
    assert controller.state.last_charge_power > 0
    _set_readings(hass, "1500", "50", "0", "charging")  # it says charging and takes nothing
    for n in range(NOT_RESPONDING_ISSUE_TICKS + 1):
        assert registry.async_get_issue(DOMAIN, issue_id) is None, f"tick {n}"
        await controller._tick(dt_util.utcnow())
    assert registry.async_get_issue(DOMAIN, issue_id) is not None
    assert controller.quality.state() == "not_responding"
    _set_readings(hass, "1500", "50", "-1000", "charging")
    await controller._tick(dt_util.utcnow())
    assert registry.async_get_issue(DOMAIN, issue_id) is None
    await controller.async_stop()
