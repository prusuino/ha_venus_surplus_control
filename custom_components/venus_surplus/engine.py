"""The decision engine: pure Python, no Home Assistant imports, so it can
be tested on a desk.

Every tick it gets the current readings (`Inputs`), the adjustable
parameters (`Params`), the state carried from tick to tick (`State`) and
returns a `Decision`: the target mode, the command to send (if any), the
reason and a diagnostics dictionary. The rules are the ones of the
long-running YAML package this integration grew out of:

* charge the Venus over AC only from real surplus, and only while the
  first (inverter-coupled) battery is not taking the surplus itself –
  or on a good solar day, when both will fill up anyway ("Venus first");
* discharge only against grid import while the first battery is already
  delivering or empty; step power with hysteresis; never export;
* stand by otherwise; trip to standby when the first battery suddenly
  works against the Venus (cross-charging);
* filter noise and sensor glitches, confirm low-headroom and cross
  conditions over several ticks before acting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime


@dataclass
class Inputs:
    """Readings of one tick. Power in W, energy in kWh, SoC in %."""

    surplus_mean: float | None  # mean of PV minus house over the averaging window
    surplus_instant: float | None
    surplus_ex_venus_mean: float | None  # mean with the Venus' AC flow taken out
    venus_soc: float | None
    venus_ac: float | None  # positive = delivering into the house
    venus_pv: float  # own MPPT production (0 for C/E)
    venus_state: str | None  # inverter state, lower case
    venus_capacity_kwh: float | None
    primary_power: float | None  # positive = discharging; None if no first battery
    primary_soc: float | None  # None if no first battery
    forecast_today_kwh: float  # 0 without forecast
    forecast_remaining_kwh: float  # dampened, 0 without forecast
    sun_hours_left: float  # hours until sunset, 0 at night
    primary_reserve_soc: float | None = None  # reserve (minimum SoC) of the first battery, if configured


@dataclass
class Params:
    """Adjustable parameters (entities / options)."""

    ac_charge_limit_w: int = 1200
    total_charge_limit_w: int = 1400
    discharge_limit_w: int = 1000
    discharge_cap_w: int = 1000
    feed_in_limit_w: int = 0  # AC the Venus may deliver into the house, 0 = none
    first_forecast_kwh: float = 45.0
    primary_capacity_kwh: float = 10.0
    venus_capacity_fallback_kwh: float = 5.12
    house_base_load_kw: float = 0.5
    charge_reserve_w: float = 200  # surplus the Venus leaves alone
    has_primary: bool = True
    has_venus_pv: bool = False  # MPPT sensors are configured (Venus A/D)
    has_primary_reserve: bool = False  # a reserve input of the first battery is configured

    # fixed rule constants
    noise_venus_ac_w: float = 40
    noise_primary_w: float = 80
    noise_venus_pv_w: float = 20
    soc_min_charge_start: float = 85
    soc_min_charge_hold: float = 80
    venus_soc_max_charge: float = 100.1
    parallel_min_surplus_first_w: float = 600
    parallel_min_surplus_w: float = 1200
    parallel_min_headroom_first_w: float = 400
    parallel_min_headroom_w: float = 500
    parallel_primary_discharge_max_w: float = 80
    primary_absorbing_start_w: float = 200
    primary_absorbing_hold_w: float = 500
    rest_start_surplus_w: float = 2500
    proj_start_surplus_w: float = 3000
    proj_venus_rate_kw: float = 1.0
    primary_discharge_start_w: float = 500
    primary_soc_empty_bypass: float = 12
    primary_reserve_margin: float = 3
    venus_soc_resume_discharge: float = 15
    venus_soc_stop: float = 12
    pv_block_discharge_w: float = 100
    # What the Venus leaves to the grid while discharging, so that a load
    # switching off does not turn into export. Both grow with the house
    # demand up to the values here: 120 W off a demand of 220 W would leave
    # more than half of a small house to the grid.
    discharge_reserve_w: float = 120
    discharge_reserve_share: float = 0.2
    discharge_reserve_min_w: float = 40
    discharge_export_guard_w: float = 60
    discharge_export_guard_share: float = 0.1
    discharge_export_guard_min_w: float = 30
    # A running discharge at the minimum power keeps going until the house
    # needs this much less than the minimum. Starting needs the minimum plus
    # about 100 W; stopping 60 W above the minimum already made the Venus
    # switch on and off with every fridge cycle in a house with a small base
    # load. In that band up to this many W are exported instead.
    discharge_hold_below_min_w: float = 40
    block_charge_start_w: float = 150
    block_charge_hold_w: float = 200
    block_charge_hard_w: float = 350
    block_charge_confirm_ticks: int = 2
    block_discharge_w: float = 100
    cross_trip_w: float = 500
    charge_start_headroom_w: float = 400
    charge_hold_headroom_w: float = 80
    charge_low_headroom_ticks: int = 3
    charge_downshift_margin_w: float = 120
    charge_upshift_margin_w: float = 150
    charge_step_w: int = 100
    charge_min_w: int = 100
    discharge_min_w: int = 200
    discharge_step_w: int = 50
    venus_pv_direct_use_min_w: float = 80
    pv_unknown_hold_ticks: int = 4
    primary_idle_confirm_ticks: int = 6
    primary_rest_confirm_ticks: int = 6  # first battery delivers nothing although the house imports


@dataclass
class State:
    """Carried from tick to tick; persisted by the controller."""

    last_charge_power: int = 0  # last AC charge command [W]
    last_charge_target: int = 0  # gross target before the total limit
    last_discharge_power: int = 0
    last_valid_dc_pv: float = 0.0
    bad_data_count: int = 0
    low_headroom_count: int = 0
    cross_count: int = 0
    pv_low_count: int = 0
    primary_idle_count: int = 0
    primary_rest_count: int = 0  # ticks the first battery has delivered nothing while the house imports
    last_primary_reserve: float | None = None
    rest_latched: bool = False
    proj_latched: bool = False

    def expected_mode(self) -> str:
        if self.last_charge_power > 0:
            return "charge"
        if self.last_discharge_power > 0:
            return "discharge"
        return "standby"


@dataclass
class Decision:
    target_mode: str  # charge | discharge | stop | no_data
    reason: str
    command: str | None  # charge | discharge | standby | None (nothing to send)
    power: int  # W of the command (0 for standby)
    state: State
    text: str
    values: dict = field(default_factory=dict)


def _floor_step(value: float, step: int) -> int:
    return int(value // step) * step if value > 0 else 0


def current_mode(state_text: str | None) -> str:
    s = (state_text or "").lower().strip()
    if s in ("charging", "charge"):
        return "charge"
    if s in ("selling", "discharging", "discharge"):
        return "discharge"
    return "stop"


def data_ready(i: Inputs, p: Params) -> bool:
    if i.surplus_mean is None or i.surplus_instant is None or i.venus_soc is None or i.venus_ac is None:
        return False
    if (i.venus_state or "").lower().strip() in ("", "unknown", "unavailable", "none"):
        return False
    if p.has_primary and (i.primary_power is None or i.primary_soc is None):
        return False
    return True


def decide(i: Inputs, p: Params, s: State) -> Decision:
    """One tick."""
    s = replace(s)  # work on a copy
    if not data_ready(i, p):
        s.bad_data_count = min(10, s.bad_data_count + 1)
        cmd = None
        if s.bad_data_count >= 2:
            s.last_charge_power = s.last_charge_target = s.last_discharge_power = 0
            cmd = "standby"
        return Decision("no_data", "data_not_ready", cmd, 0, s, f"No decision: input values incomplete (bad ticks {s.bad_data_count}).", {"bad_data_count": s.bad_data_count})
    s.bad_data_count = 0

    mode = current_mode(i.venus_state)
    pv_raw = i.surplus_mean or 0.0
    d_raw = i.surplus_instant or 0.0
    primary_w = i.primary_power or 0.0
    primary_soc = i.primary_soc if i.primary_soc is not None else 100.0
    ms_soc = i.venus_soc or 0.0
    ms_soc_ctrl = round(ms_soc, 1)
    ms_grid = i.venus_ac or 0.0

    # Venus' own PV with noise filter and glitch bridging. The MPPT reading
    # can drop to zero for a moment while the Venus charges: a known value is
    # bridged, and without one the charge power is not raised for a few
    # ticks. A reading that stays low is believed, and a Venus without MPPT
    # sensors has nothing to wait for.
    ms_pv_filtered = 0.0 if abs(i.venus_pv) < p.noise_venus_pv_w else i.venus_pv
    pv_low = p.has_venus_pv and mode == "charge" and s.last_charge_power > 0 and ms_pv_filtered < 50
    pv_glitch = pv_low and s.last_valid_dc_pv >= 100
    pv_unknown = pv_low and s.last_valid_dc_pv < 100 and s.pv_low_count < p.pv_unknown_hold_ticks
    ms_pv = s.last_valid_dc_pv if pv_glitch else ms_pv_filtered

    primary_discharge = primary_w if primary_w > p.noise_primary_w else 0.0
    primary_charge = -primary_w if primary_w < -p.noise_primary_w else 0.0
    ms_export = ms_grid if ms_grid > p.noise_venus_ac_w else 0.0
    ms_import = -ms_grid if ms_grid < -p.noise_venus_ac_w else 0.0

    pv_corr = i.surplus_ex_venus_mean if i.surplus_ex_venus_mean is not None else pv_raw - ms_export + ms_import
    d_corr = d_raw - ms_export + ms_import
    house_need = max(0.0, -d_corr)

    headroom = max(0.0, pv_corr - p.charge_reserve_w)

    # ---- "Venus first" --------------------------------------------------
    primary_missing = p.primary_capacity_kwh * max(0.0, 100 - primary_soc) / 100 if p.has_primary else 0.0
    ms_capacity = i.venus_capacity_kwh if i.venus_capacity_kwh else p.venus_capacity_fallback_kwh
    ms_missing = ms_capacity * max(0.0, 100 - ms_soc) / 100 / 0.9
    house_rest = i.sun_hours_left * p.house_base_load_kw
    rest_need = (primary_missing + ms_missing + house_rest) * 1.2
    rest_fc = i.forecast_remaining_kwh
    rest_start = rest_fc > 0 and rest_fc >= rest_need and pv_corr >= p.rest_start_surplus_w
    rest_hold = i.sun_hours_left > 0 and rest_fc > 0 and rest_fc >= rest_need / 1.2
    rest_ok = rest_start or (s.rest_latched and rest_hold)

    r = pv_corr / 1000
    proj_primary_full_h = (primary_missing / r) if r > 0.1 else 99.0
    proj_ms_fill_h = ms_missing / p.proj_venus_rate_kw
    proj_start = (
        p.has_primary
        and pv_corr >= p.proj_start_surplus_w
        and primary_soc < 98
        and ms_missing >= 1.0
        and i.sun_hours_left > 0
        and proj_primary_full_h <= 0.6 * i.sun_hours_left
        and (i.sun_hours_left - proj_primary_full_h) < proj_ms_fill_h
    )
    proj_hold = i.sun_hours_left > 0 and primary_soc < 99
    proj_ok = proj_start or (s.proj_latched and proj_hold)
    s.rest_latched = bool(rest_ok)
    s.proj_latched = bool(proj_ok)

    venus_first = i.forecast_today_kwh >= p.first_forecast_kwh or rest_ok or proj_ok
    if not p.has_primary:
        venus_first = True  # nothing to hold back for
    min_surplus = p.parallel_min_surplus_first_w if venus_first else p.parallel_min_surplus_w
    min_headroom = p.parallel_min_headroom_first_w if venus_first else p.parallel_min_headroom_w
    absorbing_thr = p.primary_absorbing_hold_w if mode == "charge" else p.primary_absorbing_start_w
    primary_absorbing = primary_charge > absorbing_thr
    charge_allowed_parallel = (
        pv_corr >= min_surplus
        and headroom >= min_headroom
        and primary_discharge <= p.parallel_primary_discharge_max_w
        and (venus_first or not primary_absorbing)
    )

    # ---- cross-charging guards -------------------------------------------
    soft_limit = p.block_charge_hold_w if mode == "charge" else p.block_charge_start_w
    block_charge_soft = primary_discharge > soft_limit
    block_charge_hard = mode == "charge" and primary_discharge > p.block_charge_hard_w
    if mode == "charge":
        block_charge = block_charge_hard or (block_charge_soft and s.cross_count >= p.block_charge_confirm_ticks - 1)
    else:
        block_charge = block_charge_soft
    block_discharge = primary_charge > p.block_discharge_w

    # ---- charge target with hysteresis ------------------------------------
    raw = min(p.ac_charge_limit_w, _floor_step(headroom, 100))
    last_t = s.last_charge_target
    if mode != "charge":
        target_charge = raw if raw >= p.charge_start_headroom_w else 0
    else:
        if headroom < p.charge_hold_headroom_w and s.low_headroom_count >= p.charge_low_headroom_ticks - 1:
            target_charge = 0
        elif headroom < p.charge_hold_headroom_w:
            target_charge = last_t
        elif last_t <= 0:
            target_charge = raw if raw >= p.charge_start_headroom_w else 0
        elif raw > last_t and headroom >= last_t + p.charge_upshift_margin_w:
            target_charge = raw
        elif raw < last_t and headroom < last_t - p.charge_downshift_margin_w:
            target_charge = raw if raw >= 200 else (200 if headroom >= p.charge_hold_headroom_w else 0)
        else:
            target_charge = last_t

    remaining = max(0.0, p.total_charge_limit_w - ms_pv)
    cmd_raw = min(float(target_charge), remaining)
    if pv_unknown:
        cmd_raw = min(cmd_raw, float(s.last_charge_power))
    rounded = _floor_step(cmd_raw, p.charge_step_w)
    charge_cmd = 0 if rounded < p.charge_min_w else min(p.ac_charge_limit_w, rounded)

    # ---- discharge target with hysteresis -----------------------------------
    reserve = min(p.discharge_reserve_w, max(p.discharge_reserve_min_w, p.discharge_reserve_share * house_need))
    export_guard = min(p.discharge_export_guard_w, max(p.discharge_export_guard_min_w, p.discharge_export_guard_share * house_need))
    need = max(0.0, house_need - reserve)
    lim, mn, st = p.discharge_limit_w, p.discharge_min_w, p.discharge_step_w
    last_d = s.last_discharge_power
    hold_need = max(0.0, mn - p.discharge_hold_below_min_w)
    if mode != "discharge":
        requested = min(lim, max(mn, _floor_step(need + 40, st))) if need >= mn - 20 else 0
    else:
        up = min(lim, last_d + st)
        down = last_d - st
        if last_d >= mn and up > last_d and need >= up - 40:
            requested = up
        elif last_d > mn and need < down - 40:
            requested = max(mn, down)
        elif last_d >= mn and house_need < hold_need:
            requested = 0
        elif last_d >= mn:
            requested = last_d
        else:
            requested = mn if need >= mn - 20 else 0
    safe_raw = max(0.0, house_need - export_guard)
    if safe_raw >= mn:
        safe_cap = min(lim, _floor_step(safe_raw, st))
    elif mode == "discharge" and last_d >= mn and house_need >= hold_need:
        safe_cap = mn  # hold the minimum instead of stopping, see discharge_hold_below_min_w
    else:
        safe_cap = 0
    user_cap = max(mn, min(lim, _floor_step(p.discharge_cap_w, st)))
    # Feed-in limit at the plug: the AC the Venus delivers, not just the
    # command. The command is the AC setpoint (a Venus A with 500 W on its
    # MPPTs delivered 983 W at a 1000 W command; the PV went into the pack),
    # so the limit caps the command. As a safeguard, AC measured above the
    # command while discharging (beyond the noise) is taken off. The cap never
    # goes below the minimum command: standing by would only send the PV into
    # the Venus' own battery while the house imports. Without a limit: no cap.
    feed_in_cap = lim
    feed_in_extra = 0.0
    if p.feed_in_limit_w > 0:
        if mode == "discharge" and last_d > 0:
            over = ms_grid - last_d
            feed_in_extra = over if over > p.noise_venus_ac_w else 0.0
        feed_in_cap = min(lim, max(mn, _floor_step(p.feed_in_limit_w - feed_in_extra, st)))
    feed_in_exceeded = p.feed_in_limit_w > 0 and mode == "discharge" and ms_grid > p.feed_in_limit_w + p.noise_venus_ac_w
    target_discharge = min(requested, safe_cap, user_cap, feed_in_cap)

    direct_pv_use = ms_pv >= p.venus_pv_direct_use_min_w and safe_cap >= mn and pv_corr < p.pv_block_discharge_w and not block_discharge

    # The first battery counts as empty at its reserve: the inverter stops
    # discharging it there, so waiting for it to deliver would wait all
    # night. With a reserve input the threshold follows it (plus a margin,
    # never below the fixed value); a reading that drops out keeps the last one.
    if p.has_primary_reserve:
        if i.primary_reserve_soc is not None and 0 <= i.primary_reserve_soc <= 100:
            s.last_primary_reserve = float(i.primary_reserve_soc)
    else:
        s.last_primary_reserve = None
    primary_empty_soc = p.primary_soc_empty_bypass
    if s.last_primary_reserve is not None:
        primary_empty_soc = max(primary_empty_soc, s.last_primary_reserve + p.primary_reserve_margin)

    soc_thr = p.soc_min_charge_hold if mode == "charge" else p.soc_min_charge_start
    charge_soc_allowed = primary_soc >= soc_thr
    # The first battery goes first only while it takes the surplus. One that
    # takes nothing for several ticks although there is headroom (standby,
    # charge limit, fault) leaves the surplus to the grid: then the Venus may
    # have it. The moment the first battery charges or discharges again, the
    # count starts over and the normal rules apply.
    idle_headroom = p.charge_hold_headroom_w if mode == "charge" else p.charge_start_headroom_w
    primary_idle_now = p.has_primary and primary_charge == 0 and primary_discharge == 0 and headroom >= idle_headroom
    s.primary_idle_count = min(10, s.primary_idle_count + 1) if primary_idle_now else 0
    primary_idle = s.primary_idle_count >= p.primary_idle_confirm_ticks
    # The same at night: a first battery that neither charges nor discharges
    # while the house imports (paused, in standby, at a limit) is not going
    # to deliver. Waiting for it would leave a charged Venus standing by.
    primary_rest_now = p.has_primary and primary_charge == 0 and primary_discharge == 0 and house_need >= mn and pv_corr < p.pv_block_discharge_w
    s.primary_rest_count = min(10, s.primary_rest_count + 1) if primary_rest_now else 0
    primary_rest = s.primary_rest_count >= p.primary_rest_confirm_ticks
    charge_ok = (charge_soc_allowed or charge_allowed_parallel or primary_idle) and charge_cmd >= p.charge_min_w and ms_soc_ctrl < p.venus_soc_max_charge and not block_charge
    if mode == "discharge":
        discharge_ok = ms_soc_ctrl > p.venus_soc_stop and pv_corr < p.pv_block_discharge_w and target_discharge >= mn and not block_discharge
    else:
        discharge_ok = (
            ms_soc_ctrl >= p.venus_soc_resume_discharge
            and pv_corr < p.pv_block_discharge_w
            and target_discharge >= mn
            and (primary_discharge >= p.primary_discharge_start_w or primary_soc <= primary_empty_soc or direct_pv_use or primary_rest or not p.has_primary)
            and not block_discharge
        )
    cross_trip = (mode == "charge" and primary_discharge > p.cross_trip_w) or (mode == "discharge" and primary_charge > p.cross_trip_w)

    # The SoC protection only keeps the Venus from discharging; an empty Venus
    # must still be allowed to charge, so charging is decided first.
    if cross_trip:
        target_mode, reason = "stop", "cross_trip"
    elif charge_ok:
        target_mode = "charge"
        if charge_soc_allowed:
            reason = "charge_ok"
        elif charge_allowed_parallel:
            reason = "charge_parallel"
        else:
            reason = "charge_primary_idle"
    elif ms_soc_ctrl <= p.venus_soc_stop:
        target_mode, reason = "stop", "venus_soc_protect"
    elif discharge_ok:
        target_mode = "discharge"
        if direct_pv_use and mode != "discharge":
            reason = "direct_pv_use"
        elif mode != "discharge" and primary_rest and primary_discharge < p.primary_discharge_start_w and primary_soc > primary_empty_soc:
            reason = "discharge_primary_idle"
        else:
            reason = "discharge_ok"
    else:
        target_mode, reason = "stop", "no_condition"

    # ---- counters ---------------------------------------------------------
    s.low_headroom_count = min(10, s.low_headroom_count + 1) if (mode == "charge" and headroom < p.charge_hold_headroom_w) else 0
    s.cross_count = min(10, s.cross_count + 1) if (mode == "charge" and block_charge_soft and not block_charge_hard) else 0
    s.pv_low_count = min(10, s.pv_low_count + 1) if pv_low else 0
    if ms_pv_filtered >= 50:
        s.last_valid_dc_pv = round(ms_pv_filtered)

    # ---- command ----------------------------------------------------------
    command: str | None = None
    power = 0
    if target_mode == "charge" and charge_cmd >= p.charge_min_w and (mode != "charge" or s.last_charge_power != charge_cmd):
        command, power = "charge", charge_cmd
        s.last_charge_power, s.last_charge_target, s.last_discharge_power = charge_cmd, target_charge, 0
    elif target_mode == "discharge" and target_discharge >= mn and (mode != "discharge" or s.last_discharge_power != target_discharge):
        command, power = "discharge", target_discharge
        s.last_discharge_power, s.last_charge_power, s.last_charge_target = target_discharge, 0, 0
    elif target_mode == "stop" and mode != "stop":
        command = "standby"
        s.last_charge_power = s.last_charge_target = s.last_discharge_power = 0

    if target_mode == "charge":
        text = f"Charge {charge_cmd} W: headroom {headroom:.0f} W, primary SoC {primary_soc:.0f} %, primary dis {primary_discharge:.0f} W / chg {primary_charge:.0f} W, parallel={charge_allowed_parallel}."
    elif target_mode == "discharge":
        text = f"Discharge {target_discharge} W: house need {house_need:.0f} W, surplus {pv_corr:.0f} W, Venus SoC {ms_soc:.1f} %."
    else:
        text = f"Stop: charge cmd {charge_cmd} W, headroom {headroom:.0f} W, primary SoC {primary_soc:.0f} %, primary dis {primary_discharge:.0f} W / chg {primary_charge:.0f} W, parallel={charge_allowed_parallel}."

    values = {
        "surplus_corr_w": round(pv_corr),
        "surplus_instant_corr_w": round(d_corr),
        "house_need_w": round(house_need),
        "headroom_w": round(headroom),
        "charge_reserve_w": round(p.charge_reserve_w),
        "venus_pv_w": round(ms_pv),
        "primary_discharge_w": round(primary_discharge),
        "primary_charge_w": round(primary_charge),
        "primary_empty_below_soc": round(primary_empty_soc, 1),
        "parallel_allowed": charge_allowed_parallel,
        "primary_idle": primary_idle,
        "primary_rest": primary_rest,
        "discharge_reserve_w": round(reserve),
        "primary_idle_count": s.primary_idle_count,
        "venus_first": venus_first,
        "forecast_today_kwh": round(i.forecast_today_kwh, 1),
        "forecast_remaining_kwh": round(rest_fc, 1),
        "rest_need_kwh": round(rest_need, 1),
        "rest_latched": s.rest_latched,
        "projection_latched": s.proj_latched,
        "proj_primary_full_h": round(proj_primary_full_h, 1),
        "proj_venus_fill_h": round(proj_ms_fill_h, 1),
        "sun_hours_left": round(i.sun_hours_left, 1),
        "charge_target_w": target_charge,
        "charge_command_w": charge_cmd,
        "discharge_requested_w": requested,
        "discharge_safe_cap_w": safe_cap,
        "discharge_target_w": target_discharge,
        "feed_in_limit_w": p.feed_in_limit_w,
        "discharge_feed_in_cap_w": feed_in_cap,
        "feed_in_extra_w": round(feed_in_extra),
        "feed_in_exceeded": feed_in_exceeded,
        "low_headroom_count": s.low_headroom_count,
        "cross_count": s.cross_count,
        "block_charge": block_charge,
        "block_discharge": block_discharge,
        "cross_trip": cross_trip,
        "pv_glitch": pv_glitch,
        "pv_unknown": pv_unknown,
        "current_mode": mode,
    }
    return Decision(target_mode, reason, command, power, s, text, values)


def state_to_dict(s: State) -> dict:
    return asdict(s)


def state_from_dict(d: dict | None) -> State:
    if not d:
        return State()
    known = {k: v for k, v in d.items() if k in State.__dataclass_fields__}
    return State(**known)
