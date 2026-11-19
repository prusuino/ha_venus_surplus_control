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
    # A Venus at 100 % that takes nothing is full: the charge command is
    # dropped after a few ticks and comes back below the resume value. One
    # that still takes power at a displayed 100 % keeps its command.
    venus_full_soc: float = 100
    venus_full_resume_soc: float = 98
    venus_full_confirm_ticks: int = 4
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
    proj_forecast_start_factor: float = 1.1  # remaining forecast must cover what the first battery misses, with margin
    proj_forecast_hold_factor: float = 0.9
    primary_discharge_start_w: float = 500
    # Below that the Venus helps as well, once the first battery has been
    # delivering for a while: a house with a small base load never reaches
    # the value above, and the Venus would stand by fully charged until the
    # first battery is empty. The wait keeps a passing cloud from starting it.
    primary_help_start_w: float = 150
    primary_help_confirm_s: float = 90
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
    cross_trim_margin_w: float = 50  # taken off the charge command on top of what the first battery discharges
    cross_trim_decay_w: float = 50  # given back per tick once the first battery no longer discharges
    # The same for the grid: a load that switches on while the Venus charges
    # on the old average is drawn from the grid when no first battery covers
    # it. Import above this value caps the charge command at what it was,
    # less the import and a margin; the cap rises again per tick once the
    # grid no longer delivers, until the average is below it.
    import_trim_start_w: float = 100
    import_cap_margin_w: float = 50
    import_cap_rise_w: float = 100
    # A large load that nobody covers starts the discharge after two ticks,
    # without waiting for the average or for the first battery; while the
    # house needs that much, the average does not stop it either.
    fast_start_w: float = 400
    fast_start_confirm_ticks: int = 2
    charge_start_headroom_w: float = 400
    charge_hold_headroom_w: float = 80
    charge_low_headroom_ticks: int = 3
    charge_downshift_margin_w: float = 120
    charge_upshift_margin_w: float = 150
    charge_step_w: int = 100
    charge_min_w: int = 100
    discharge_min_w: int = 200
    discharge_step_w: int = 50
    # How far the discharge power may rise in one tick. The power itself stays
    # on the fine steps above; only the climb is faster, so that a kettle is
    # served before it is done. Coming down needs no limit: the export guard
    # cuts the power in one step.
    discharge_up_step_w: int = 50
    # The Venus as the only source: no first battery, or one that is empty or
    # at rest. Nobody else covers what the Venus leaves, so every watt it holds
    # back is imported. The command then moves in fine steps with a small
    # export guard (a setting: what a house needs depends on its loads and
    # its meter); a rise smaller than the dead band is not worth a write.
    sole_discharge_step_w: int = 10
    sole_export_guard_w: float = 10
    sole_deadband_w: int = 10
    venus_pv_direct_use_min_w: float = 80
    pv_unknown_hold_ticks: int = 4
    primary_idle_confirm_ticks: int = 6
    primary_limit_confirm_ticks: int = 6  # first battery charges at a steady power while surplus is left
    primary_limit_tolerance_w: float = 100
    primary_limit_tolerance_share: float = 0.1
    primary_rest_confirm_s: float = 90  # first battery delivers nothing although the house imports
    # The two waits above are times, not ticks: with a tick of 15 s they are
    # six ticks, with 30 s three. Never less than two ticks.
    tick_seconds: int = 30


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
    cross_trim_w: float = 0.0  # held back from the charge command because the first battery discharged
    import_cap_w: float = -1.0  # charge power the grid import allows; negative = no cap
    sole_guard_w: float = -1.0  # export guard the standing command was decided with; negative = unknown
    pv_low_count: int = 0
    primary_idle_count: int = 0
    primary_limit_count: int = 0  # ticks the first battery has charged at a steady power with surplus left
    primary_limit_ref: float = 0.0  # that steady power [W]
    primary_rest_count: int = 0  # ticks the first battery has delivered nothing while the house imports
    primary_help_count: int = 0  # ticks the first battery has been delivering a small load
    fast_count: int = 0  # ticks a large load has stood that nobody covers
    full_count: int = 0  # ticks the Venus has stood at 100 % without taking anything
    full_latched: bool = False
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


def _ticks(seconds: float, tick_seconds: int) -> int:
    """A wait in seconds as a number of ticks, at least two."""
    return max(2, -(-int(seconds) // max(1, int(tick_seconds))))


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
    # What the grid delivers at this moment: the surplus as measured (the
    # Venus counts as a load in it) plus what the first battery adds or
    # takes. Behind a grid meter that is the meter itself.
    grid_import = max(0.0, -(d_raw + (primary_w if p.has_primary else 0.0)))
    fast_now = house_need >= p.fast_start_w and (mode == "discharge" or grid_import >= p.fast_start_w)
    s.fast_count = min(10, s.fast_count + 1) if fast_now else 0
    fast = s.fast_count >= p.fast_start_confirm_ticks

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
    # The projection assumes the surplus of this moment until sunset. In
    # autumn and winter it does not last: with a forecast, what is left of
    # the day after the house must still fill the first battery, otherwise
    # the Venus would only take away what the first battery needs.
    fc_for_primary = rest_fc - house_rest
    proj_fc_start = rest_fc <= 0 or fc_for_primary >= primary_missing * p.proj_forecast_start_factor
    proj_fc_hold = rest_fc <= 0 or fc_for_primary >= primary_missing * p.proj_forecast_hold_factor
    proj_start = (
        p.has_primary
        and proj_fc_start
        and pv_corr >= p.proj_start_surplus_w
        and primary_soc < 98
        and ms_missing >= 1.0
        and i.sun_hours_left > 0
        and proj_primary_full_h <= 0.6 * i.sun_hours_left
        and (i.sun_hours_left - proj_primary_full_h) < proj_ms_fill_h
    )
    proj_hold = i.sun_hours_left > 0 and primary_soc < 99 and proj_fc_hold
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
        and primary_discharge <= (p.block_charge_hard_w if mode == "charge" else p.parallel_primary_discharge_max_w)
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

    # ---- first battery at its charge limit ---------------------------------
    # The surplus is PV minus house, so it includes what the first battery
    # takes. A first battery that charges at a steady power for several ticks
    # while more surplus stands than it takes is at its limit (rated power,
    # cold or nearly full cells): the rest would be exported, so the Venus may
    # have it, and only that rest. The reference is the highest steady power
    # seen; once the first battery takes clearly more or less than that, it is
    # not at a limit any more, the count starts over and it goes first again.
    left_after_primary = max(0.0, pv_corr - primary_charge - p.charge_reserve_w)
    limit_left_thr = p.charge_hold_headroom_w if mode == "charge" else p.charge_start_headroom_w
    limit_tol = max(p.primary_limit_tolerance_w, p.primary_limit_tolerance_share * s.primary_limit_ref)
    if not (p.has_primary and primary_charge > p.primary_absorbing_start_w and left_after_primary >= limit_left_thr):
        s.primary_limit_count, s.primary_limit_ref = 0, 0.0
    elif s.primary_limit_ref > 0 and abs(primary_charge - s.primary_limit_ref) <= limit_tol:
        s.primary_limit_count = min(10, s.primary_limit_count + 1)
        s.primary_limit_ref = max(s.primary_limit_ref, primary_charge)
    else:
        s.primary_limit_count, s.primary_limit_ref = 0, primary_charge
    primary_limited = s.primary_limit_count >= p.primary_limit_confirm_ticks
    soc_thr = p.soc_min_charge_hold if mode == "charge" else p.soc_min_charge_start
    charge_soc_allowed = primary_soc >= soc_thr
    # Charging on this rule alone leaves the first battery its share.
    limited_only = primary_limited and not charge_soc_allowed and not charge_allowed_parallel
    charge_headroom = left_after_primary if limited_only else headroom
    # The command follows the averaged surplus. When the surplus falls, the
    # Venus still charges on the old average for a moment and the first
    # battery starts to discharge into it. Stopping for that and starting
    # again a tick later goes back and forth, so the command is lowered by
    # what the first battery discharges plus a margin, and given back in
    # small steps once it no longer does. The cross-charging guards still
    # stop a discharge that is large or stays.
    import_over = grid_import if grid_import > p.import_trim_start_w else 0.0
    if mode == "charge" and s.last_charge_power > 0:
        if primary_discharge > 0:
            s.cross_trim_w = min(float(p.ac_charge_limit_w), s.cross_trim_w + primary_discharge + p.cross_trim_margin_w)
        else:
            s.cross_trim_w = max(0.0, s.cross_trim_w - p.cross_trim_decay_w)
    else:
        s.cross_trim_w = 0.0
    charge_headroom = max(0.0, charge_headroom - s.cross_trim_w)
    # Import while charging: the command is capped at what it was, less the
    # import. The cap is a power, not a part of the average, so it holds
    # while the average still comes down and is gone once that is below it.
    if mode == "charge" and s.last_charge_power > 0:
        if import_over > 0:
            base = s.import_cap_w if s.import_cap_w >= 0 else float(s.last_charge_power)
            s.import_cap_w = max(0.0, min(base, float(s.last_charge_power)) - import_over - p.import_cap_margin_w)
        elif s.import_cap_w >= 0:
            s.import_cap_w += p.import_cap_rise_w
            if s.import_cap_w >= charge_headroom:
                s.import_cap_w = -1.0
    else:
        s.import_cap_w = -1.0
    if s.import_cap_w >= 0:
        charge_headroom = min(charge_headroom, s.import_cap_w)

    # ---- charge target with hysteresis ------------------------------------
    raw = min(p.ac_charge_limit_w, _floor_step(charge_headroom, 100))
    last_t = s.last_charge_target
    if mode != "charge":
        # no start on the average alone while the grid delivers at this moment
        target_charge = raw if raw >= p.charge_start_headroom_w and import_over == 0 else 0
    else:
        if charge_headroom < p.charge_hold_headroom_w and (import_over > 0 or s.low_headroom_count >= p.charge_low_headroom_ticks - 1):
            # measured import is a fact, not a dip of the average: no waiting
            target_charge = 0
        elif charge_headroom < p.charge_hold_headroom_w:
            target_charge = last_t
        elif last_t <= 0:
            target_charge = raw if raw >= p.charge_start_headroom_w else 0
        elif raw > last_t and charge_headroom >= last_t + p.charge_upshift_margin_w:
            target_charge = raw
        elif raw < last_t and charge_headroom < last_t - p.charge_downshift_margin_w:
            target_charge = raw if raw >= 200 else (200 if charge_headroom >= p.charge_hold_headroom_w else 0)
        else:
            target_charge = last_t

    remaining = max(0.0, p.total_charge_limit_w - ms_pv)
    cmd_raw = min(float(target_charge), remaining)
    if pv_unknown:
        cmd_raw = min(cmd_raw, float(s.last_charge_power))
    rounded = _floor_step(cmd_raw, p.charge_step_w)
    charge_cmd = 0 if rounded < p.charge_min_w else min(p.ac_charge_limit_w, rounded)

    # ---- discharge target with hysteresis -----------------------------------
    lim, mn = p.discharge_limit_w, p.discharge_min_w
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

    # The same at night: a first battery that neither charges nor discharges
    # while the house imports (paused, in standby, at a limit) is not going
    # to deliver. Waiting for it would leave a charged Venus standing by.
    primary_rest_now = p.has_primary and primary_charge == 0 and primary_discharge == 0 and house_need >= mn and pv_corr < p.pv_block_discharge_w
    s.primary_rest_count = min(10, s.primary_rest_count + 1) if primary_rest_now else 0
    primary_rest = s.primary_rest_count >= _ticks(p.primary_rest_confirm_s, p.tick_seconds)
    primary_help_now = p.has_primary and primary_discharge >= p.primary_help_start_w and pv_corr < p.pv_block_discharge_w
    s.primary_help_count = min(10, s.primary_help_count + 1) if primary_help_now else 0
    primary_help = s.primary_help_count >= _ticks(p.primary_help_confirm_s, p.tick_seconds)
    # Two batteries cover the house together: the Venus stays a step below
    # the demand and the first battery, which follows the meter, takes the
    # rest. A Venus that is the only source follows the demand closely instead.
    sole_source = (not p.has_primary) or primary_soc <= primary_empty_soc or primary_rest
    if sole_source:
        export_guard = max(0.0, p.sole_export_guard_w)
        # a changed setting takes effect now, not at the next move of the demand
        guard_changed = s.sole_guard_w >= 0 and s.sole_guard_w != export_guard
        s.sole_guard_w = export_guard
        reserve = export_guard
        st = p.sole_discharge_step_w
    else:
        reserve = min(p.discharge_reserve_w, max(p.discharge_reserve_min_w, p.discharge_reserve_share * house_need))
        export_guard = min(p.discharge_export_guard_w, max(p.discharge_export_guard_min_w, p.discharge_export_guard_share * house_need))
        guard_changed = False
        st = p.discharge_step_w
    need = max(0.0, house_need - reserve)
    last_d = s.last_discharge_power
    hold_need = max(0.0, mn - p.discharge_hold_below_min_w)
    if mode != "discharge":
        requested = min(lim, max(mn, _floor_step(need + 40, st))) if need >= mn - 20 else 0
    else:
        up = min(lim, last_d + max(st, p.discharge_up_step_w), _floor_step(need + 40, st))
        if sole_source and up < last_d + p.sole_deadband_w and up < lim:
            up = last_d
        down = last_d - st
        if last_d >= mn and up > last_d:
            requested = up
        elif last_d > mn and need < down - 40:
            requested = max(mn, down)
        elif last_d >= mn and house_need < hold_need:
            requested = 0
        elif last_d >= mn:
            requested = last_d
        else:
            # The Venus still reports discharging, but no discharge command is
            # standing (handed back from manual, or a command of someone else):
            # that is a fresh start, straight to the demand, not a climb from
            # the minimum.
            requested = min(lim, max(mn, _floor_step(need + 40, st))) if need >= mn - 20 else 0
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
    if sole_source and mode == "discharge" and last_d >= mn:
        # No write for a few watts: a small rise is left out, and the command
        # stays where it is as long as it does not export.
        if last_d < target_discharge < last_d + p.sole_deadband_w:
            target_discharge = last_d
        elif not guard_changed and target_discharge < last_d <= min(user_cap, feed_in_cap) and last_d <= house_need and target_discharge >= mn:
            target_discharge = last_d

    direct_pv_use = ms_pv >= p.venus_pv_direct_use_min_w and safe_cap >= mn and pv_corr < p.pv_block_discharge_w and not block_discharge

    # The first battery goes first only while it takes the surplus. One that
    # takes nothing for several ticks although there is headroom (standby,
    # charge limit, fault) leaves the surplus to the grid: then the Venus may
    # have it. The moment the first battery charges or discharges again, the
    # count starts over and the normal rules apply.
    idle_headroom = p.charge_hold_headroom_w if mode == "charge" else p.charge_start_headroom_w
    primary_idle_now = p.has_primary and primary_charge == 0 and primary_discharge == 0 and headroom >= idle_headroom
    s.primary_idle_count = min(10, s.primary_idle_count + 1) if primary_idle_now else 0
    primary_idle = s.primary_idle_count >= p.primary_idle_confirm_ticks
    # A full Venus: at 100 % and taking nothing for a few ticks. The latch
    # holds until the SoC has dropped, so that the command does not come
    # and go at the top.
    s.full_count = min(10, s.full_count + 1) if (ms_soc_ctrl >= p.venus_full_soc and ms_import == 0) else 0
    if s.full_count >= p.venus_full_confirm_ticks:
        s.full_latched = True
    elif ms_soc_ctrl < p.venus_full_resume_soc:
        s.full_latched = False
    charge_wanted = (charge_soc_allowed or charge_allowed_parallel or primary_idle or primary_limited) and charge_cmd >= p.charge_min_w and ms_soc_ctrl < p.venus_soc_max_charge and not block_charge
    charge_ok = charge_wanted and not s.full_latched
    # There is surplus the Venus could take, and only the first battery's
    # turn keeps it waiting. This changes no decision, only the reason shown.
    waits_for_primary = (
        p.has_primary and not charge_wanted and not s.full_latched and charge_cmd >= p.charge_min_w and primary_discharge == 0
        and ms_soc_ctrl < p.venus_soc_max_charge and not block_charge
    )
    discharge_wanted = False
    if mode == "discharge":
        discharge_ok = ms_soc_ctrl > p.venus_soc_stop and (pv_corr < p.pv_block_discharge_w or fast) and target_discharge >= mn and not block_discharge
    else:
        discharge_wanted = (
            (pv_corr < p.pv_block_discharge_w or fast)
            and target_discharge >= mn
            and (primary_discharge >= p.primary_discharge_start_w or primary_help or primary_soc <= primary_empty_soc or direct_pv_use or primary_rest or fast or not p.has_primary)
            and not block_discharge
        )
        discharge_ok = ms_soc_ctrl >= p.venus_soc_resume_discharge and discharge_wanted
    # The Venus would discharge, but it stands below the level from which a
    # discharge starts again (often at its own floor, where it goes to standby
    # by itself): the reason names the low SoC, not "no condition".
    held_by_soc = mode != "discharge" and ms_soc_ctrl < p.venus_soc_resume_discharge and discharge_wanted
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
        elif primary_limited:
            reason = "charge_primary_limited"
        else:
            reason = "charge_primary_idle"
    elif ms_soc_ctrl <= p.venus_soc_stop:
        target_mode, reason = "stop", "primary_first" if waits_for_primary else "venus_soc_protect"
    elif discharge_ok:
        target_mode = "discharge"
        if direct_pv_use and mode != "discharge":
            reason = "direct_pv_use"
        elif mode != "discharge" and primary_rest and primary_discharge < p.primary_discharge_start_w and primary_soc > primary_empty_soc:
            reason = "discharge_primary_idle"
        else:
            reason = "discharge_ok"
    elif charge_wanted and s.full_latched:
        target_mode, reason = "stop", "venus_full"
    else:
        target_mode, reason = "stop", "primary_first" if waits_for_primary else ("venus_soc_protect" if held_by_soc else "no_condition")

    # ---- counters ---------------------------------------------------------
    s.low_headroom_count = min(10, s.low_headroom_count + 1) if (mode == "charge" and charge_headroom < p.charge_hold_headroom_w) else 0
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
    elif target_mode == "stop" and (mode != "stop" or s.last_charge_power > 0 or s.last_discharge_power > 0):
        # also when the Venus already stands by on its own (a full battery
        # does): the forced mode and the power would otherwise stay in its
        # registers, and it would start again by itself
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
        "primary_limited": primary_limited,
        "primary_limit_count": s.primary_limit_count,
        "left_after_primary_w": round(left_after_primary),
        "primary_rest": primary_rest,
        "primary_help": primary_help,
        "grid_import_w": round(grid_import),
        "fast_start": fast,
        "venus_full": s.full_latched,
        "discharge_reserve_w": round(reserve),
        "sole_source": sole_source,
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
        "cross_trim_w": round(s.cross_trim_w),
        "import_cap_w": round(s.import_cap_w),
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
