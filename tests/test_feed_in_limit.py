"""Feed-in limit at the plug: presets, the capped discharge command and the
safeguard against AC measured above the command."""
from __future__ import annotations

from custom_components.venus_surplus.const import feed_in_limit_w
from custom_components.venus_surplus.engine import Inputs, Params, State, decide


def _inputs(**over) -> Inputs:
    base = dict(
        surplus_mean=-1500.0, surplus_instant=-1500.0, surplus_ex_venus_mean=None, venus_soc=60.0, venus_ac=0.0, venus_pv=0.0,
        venus_state="standby", venus_capacity_kwh=5.12, primary_power=None, primary_soc=None,
        forecast_today_kwh=0.0, forecast_remaining_kwh=0.0, sun_hours_left=0.0,
    )
    base.update(over)
    return Inputs(**base)


def test_presets():
    assert feed_in_limit_w("none", 800) == 0
    assert feed_in_limit_w(None, None) == 0
    assert feed_in_limit_w("ch_600", 800) == 600
    assert feed_in_limit_w("de_800", 300) == 800
    assert feed_in_limit_w("custom", 700) == 700
    assert feed_in_limit_w("custom", None) == 0


def test_without_limit_the_device_limit_applies():
    d = decide(_inputs(), Params(has_primary=False), State())
    assert d.command == "discharge" and d.power == 1000
    assert d.values["discharge_feed_in_cap_w"] == 1000


def test_limit_caps_the_discharge_command():
    # the controller lowers the device limit to the feed-in limit
    p = Params(has_primary=False, discharge_limit_w=600, feed_in_limit_w=600)
    d = decide(_inputs(), p, State())
    assert d.command == "discharge" and d.power == 600


def test_own_pv_does_not_lower_the_start():
    # the command is the AC setpoint: PV on the MPPTs goes into the pack
    p = Params(has_primary=False, has_venus_pv=True, discharge_limit_w=600, feed_in_limit_w=600)
    d = decide(_inputs(venus_pv=500.0), p, State())
    assert d.command == "discharge" and d.power == 600
    assert d.values["feed_in_extra_w"] == 0


def test_measured_extra_steps_the_command_down():
    # commanded 600 W, the Venus delivers 750 W: PV comes on top
    p = Params(has_primary=False, has_venus_pv=True, discharge_limit_w=600, feed_in_limit_w=600)
    d = decide(_inputs(venus_state="discharging", venus_ac=750.0, venus_pv=150.0), p, State(last_discharge_power=600))
    assert d.command == "discharge" and d.power == 450  # 600 W limit minus the 150 W that came on top


def test_stable_once_below_the_limit():
    p = Params(has_primary=False, has_venus_pv=True, discharge_limit_w=600, feed_in_limit_w=600)
    d = decide(_inputs(venus_state="discharging", venus_ac=600.0, venus_pv=150.0), p, State(last_discharge_power=450))
    assert d.command is None and d.target_mode == "discharge"
    assert d.state.last_discharge_power == 450
    assert d.values["feed_in_exceeded"] is False


def test_measurement_noise_is_not_taken_as_pv():
    p = Params(has_primary=False, discharge_limit_w=600, feed_in_limit_w=600)
    d = decide(_inputs(venus_state="discharging", venus_ac=630.0), p, State(last_discharge_power=600))
    assert d.command is None and d.state.last_discharge_power == 600


def test_much_pv_keeps_the_minimum_command_and_flags_it():
    # never stand by because of the limit: the PV would only charge the Venus
    p = Params(has_primary=False, has_venus_pv=True, discharge_limit_w=600, feed_in_limit_w=600)
    d = decide(_inputs(venus_state="discharging", venus_ac=800.0, venus_pv=600.0), p, State(last_discharge_power=200))
    assert d.target_mode == "discharge" and d.state.last_discharge_power == 200
    assert d.values["discharge_feed_in_cap_w"] == 200
    assert d.values["feed_in_exceeded"] is True


def test_ac_at_the_command_with_much_pv_is_left_alone():
    p = Params(has_primary=False, has_venus_pv=True, discharge_limit_w=600, feed_in_limit_w=600)
    d = decide(_inputs(venus_state="discharging", venus_ac=590.0, venus_pv=500.0), p, State(last_discharge_power=600))
    assert d.command is None and d.state.last_discharge_power == 600
    assert d.values["feed_in_exceeded"] is False
