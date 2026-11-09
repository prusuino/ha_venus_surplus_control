"""The runtime around the decision engine: samples the inputs every tick,
decides, writes the commands to the Modbus entities (or only reports them
in dry run), restores the RS485 control mode and the last command when the
firmware drops them, enforces the discharge cap and reloads the Modbus
integration after a long connection loss."""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import engine
from .issues import IssueReporter
from .const import (
    CAP_GUARD_SECOND,
    CHARGING_STATES,
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
    DEFAULT_BASE_LOAD_KW,
    DEFAULT_DISCHARGE_CAP,
    DEFAULT_DISCHARGE_LIMIT,
    DEFAULT_FIRST_FORECAST_KWH,
    DEFAULT_FORECAST_FACTOR,
    DEFAULT_PRIMARY_KWH,
    DEFAULT_TICK_SECONDS,
    DEFAULT_TOTAL_CHARGE_LIMIT,
    DEFAULT_VENUS_KWH,
    DISCHARGING_STATES,
    DOMAIN,
    EVENT_COMMAND,
    LOGBOOK_NAME,
    MEAN_WINDOW,
    MODE_CHARGE,
    MODE_DISCHARGE,
    MODE_STANDBY,
    SELF_HEAL_AFTER,
    SELF_HEAL_MINUTES,
    SELF_HEAL_SECOND,
    STORAGE_VERSION,
    WATCHDOG_MINUTES,
    WATCHDOG_SECOND,
)

_LOGGER = logging.getLogger(__name__)


# After this many ticks without complete readings (5 minutes at the default
# tick) the missing inputs are named under Settings > Repairs.
NO_DATA_ISSUE_TICKS = 10


def signal_update(entry_id: str) -> str:
    return f"{DOMAIN}_{entry_id}_update"


@dataclass
class Settings:
    """The adjustable values held by the number / switch entities."""

    discharge_cap_w: int = DEFAULT_DISCHARGE_CAP
    first_forecast_kwh: float = DEFAULT_FIRST_FORECAST_KWH
    primary_capacity_kwh: float = DEFAULT_PRIMARY_KWH
    venus_capacity_kwh: float = DEFAULT_VENUS_KWH
    house_base_load_kw: float = DEFAULT_BASE_LOAD_KW
    manual_override: bool = False
    dry_run: bool = True  # new entries start in dry run


@dataclass
class Status:
    """What the entities show."""

    target_mode: str = "unknown"  # charge | discharge | stop | no_data | paused
    reason: str = "unknown"
    text: str = ""
    values: dict[str, Any] = field(default_factory=dict)
    last_command: str | None = None
    last_command_power: int = 0
    last_command_time: datetime | None = None
    decided_at: datetime | None = None
    surplus_mean: float | None = None
    surplus_ex_venus_mean: float | None = None
    watchdog_restores: int = 0
    cap_enforced: int = 0
    self_heals: int = 0
    dry_run_commands: int = 0


class VenusController:
    """One controller per config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.settings = Settings()
        self.status = Status()
        self.state = engine.State()
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.issues = IssueReporter(hass, entry.entry_id)
        self._samples: deque[tuple[datetime, float, float]] = deque()
        self._unsub: list[Callable[[], None]] = []
        self._last_master_run: datetime | None = None
        self._connection_lost_since: datetime | None = None

    # ------------------------------------------------------------------ config
    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def has_primary(self) -> bool:
        return bool(self._cfg(CONF_PRIMARY_POWER))

    @property
    def tick_seconds(self) -> int:
        return int(self._cfg(CONF_TICK_SECONDS, DEFAULT_TICK_SECONDS))

    def params(self) -> engine.Params:
        return engine.Params(
            ac_charge_limit_w=int(self._cfg(CONF_AC_CHARGE_LIMIT, DEFAULT_AC_CHARGE_LIMIT)),
            total_charge_limit_w=int(self._cfg(CONF_TOTAL_CHARGE_LIMIT, DEFAULT_TOTAL_CHARGE_LIMIT)),
            discharge_limit_w=int(self._cfg(CONF_DISCHARGE_LIMIT, DEFAULT_DISCHARGE_LIMIT)),
            discharge_cap_w=int(self.settings.discharge_cap_w),
            first_forecast_kwh=float(self.settings.first_forecast_kwh),
            primary_capacity_kwh=float(self.settings.primary_capacity_kwh),
            venus_capacity_fallback_kwh=float(self.settings.venus_capacity_kwh),
            house_base_load_kw=float(self.settings.house_base_load_kw),
            has_primary=self.has_primary,
        )

    # ------------------------------------------------------------------ lifecycle
    async def async_start(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self.state = engine.state_from_dict(data.get("state"))
            st = data.get("settings") or {}
            for k, v in st.items():
                if hasattr(self.settings, k):
                    setattr(self.settings, k, v)
            self.status.watchdog_restores = int(data.get("watchdog_restores", 0))
        self._unsub.append(async_track_time_interval(self.hass, self._tick, timedelta(seconds=self.tick_seconds)))
        self._unsub.append(async_track_time_change(self.hass, self._watchdog_tick, minute=list(WATCHDOG_MINUTES), second=WATCHDOG_SECOND))
        self._unsub.append(async_track_time_change(self.hass, self._cap_guard_tick, second=CAP_GUARD_SECOND))
        if self._cfg(CONF_CONNECTION) and self._cfg(CONF_MODBUS_ENTRY):
            self._unsub.append(async_track_time_change(self.hass, self._self_heal_tick, minute=list(SELF_HEAL_MINUTES), second=SELF_HEAL_SECOND))
        self._unsub.append(async_track_state_change_event(self.hass, [self._cfg(CONF_RS485)], self._rs485_changed))
        self._unsub.append(async_track_state_change_event(self.hass, [self._cfg(CONF_DISCHARGE_POWER)], self._discharge_register_changed))
        self.hass.async_create_task(self._tick(dt_util.utcnow()))

    async def async_stop(self) -> None:
        for u in self._unsub:
            u()
        self._unsub.clear()
        await self._save()

    async def _save(self) -> None:
        await self._store.async_save(
            {
                "state": engine.state_to_dict(self.state),
                "settings": {
                    "discharge_cap_w": self.settings.discharge_cap_w,
                    "first_forecast_kwh": self.settings.first_forecast_kwh,
                    "primary_capacity_kwh": self.settings.primary_capacity_kwh,
                    "venus_capacity_kwh": self.settings.venus_capacity_kwh,
                    "house_base_load_kw": self.settings.house_base_load_kw,
                    "manual_override": self.settings.manual_override,
                    "dry_run": self.settings.dry_run,
                },
                "watchdog_restores": self.status.watchdog_restores,
            }
        )

    async def async_set_setting(self, key: str, value: Any) -> None:
        setattr(self.settings, key, value)
        await self._save()
        self._notify()
        if key in ("manual_override", "discharge_cap_w"):
            await self._tick(dt_util.utcnow())

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    # ------------------------------------------------------------------ readings
    def missing_inputs(self) -> list[str]:
        """The configured entities the engine needs that have no usable
        state right now (missing, unknown or unavailable)."""
        keys = [CONF_SURPLUS, CONF_VENUS_SOC, CONF_VENUS_AC, CONF_VENUS_STATE]
        if self.has_primary:
            keys += [CONF_PRIMARY_POWER, CONF_PRIMARY_SOC]
        missing = []
        for key in keys:
            ent = self._cfg(key)
            if not ent:
                missing.append(key)
                continue
            st = self.hass.states.get(ent)
            if st is None or st.state in ("unknown", "unavailable", "", "none"):
                missing.append(ent)
        return missing

    def _num(self, key: str, invert_key: str | None = None) -> float | None:
        ent = self._cfg(key)
        if not ent:
            return None
        st = self.hass.states.get(ent)
        if st is None or st.state in ("unknown", "unavailable", "", "none"):
            return None
        try:
            v = float(st.state)
        except (TypeError, ValueError):
            return None
        if invert_key and self._cfg(invert_key):
            v = -v
        return v

    def _venus_pv(self) -> float:
        total = 0.0
        for ent in self._cfg(CONF_VENUS_PV) or []:
            st = self.hass.states.get(ent)
            try:
                total += float(st.state) if st else 0.0
            except (TypeError, ValueError):
                pass
        return total

    def _venus_state(self) -> str | None:
        st = self.hass.states.get(self._cfg(CONF_VENUS_STATE))
        return st.state.lower().strip() if st else None

    def _sun_hours_left(self) -> float:
        sun = self.hass.states.get("sun.sun")
        if sun is None or sun.state != "above_horizon":
            return 0.0
        ns = sun.attributes.get("next_setting")
        try:
            t = dt_util.parse_datetime(ns) if isinstance(ns, str) else None
        except (TypeError, ValueError):
            t = None
        if t is None:
            return 0.0
        return max(0.0, (t - dt_util.utcnow()).total_seconds() / 3600)

    def _sample(self, now: datetime) -> tuple[float | None, float | None, float | None]:
        """Take the 30-second sample and return (mean, mean without Venus, instant)."""
        surplus = self._num(CONF_SURPLUS, CONF_SURPLUS_INVERT)
        ms = self._num(CONF_VENUS_AC, CONF_VENUS_AC_INVERT)
        if surplus is not None:
            ms_c = ms if ms is not None and abs(ms) > 40 else 0.0
            self._samples.append((now, surplus, surplus - ms_c))
        cutoff = now - MEAN_WINDOW
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        if not self._samples:
            return None, None, surplus
        mean = sum(s[1] for s in self._samples) / len(self._samples)
        mean_ex = sum(s[2] for s in self._samples) / len(self._samples)
        return round(mean), round(mean_ex), surplus

    def inputs(self, now: datetime) -> engine.Inputs:
        mean, mean_ex, instant = self._sample(now)
        self.status.surplus_mean = mean
        self.status.surplus_ex_venus_mean = mean_ex
        factor = float(self._cfg(CONF_FORECAST_FACTOR, DEFAULT_FORECAST_FACTOR))
        return engine.Inputs(
            surplus_mean=mean,
            surplus_instant=instant,
            surplus_ex_venus_mean=mean_ex,
            venus_soc=self._num(CONF_VENUS_SOC),
            venus_ac=self._num(CONF_VENUS_AC, CONF_VENUS_AC_INVERT),
            venus_pv=self._venus_pv(),
            venus_state=self._venus_state(),
            venus_capacity_kwh=self._num(CONF_VENUS_CAPACITY),
            primary_power=self._num(CONF_PRIMARY_POWER, CONF_PRIMARY_POWER_INVERT),
            primary_soc=self._num(CONF_PRIMARY_SOC),
            forecast_today_kwh=self._num(CONF_FORECAST_TODAY) or 0.0,
            forecast_remaining_kwh=(self._num(CONF_FORECAST_REMAINING) or 0.0) * factor,
            sun_hours_left=self._sun_hours_left(),
        )

    # ------------------------------------------------------------------ master tick
    async def _tick(self, now: datetime) -> None:
        now = dt_util.utcnow()
        self._last_master_run = now
        inputs = self.inputs(now)
        if self.settings.manual_override:
            self.status.target_mode = "paused"
            self.status.reason = "manual_override"
            self.status.text = "Automation paused: manual override is on."
            self.status.decided_at = now
            self._notify()
            return
        decision = engine.decide(inputs, self.params(), self.state)
        if decision.target_mode == "no_data":
            if decision.state.bad_data_count >= NO_DATA_ISSUE_TICKS:
                self.issues.raise_now("inputs_missing", {"entities": ", ".join(self.missing_inputs()) or "?"})
        else:
            self.issues.clear("inputs_missing")
        changed_state = decision.state != self.state
        self.state = decision.state
        self.status.target_mode = decision.target_mode
        self.status.reason = decision.reason
        self.status.text = decision.text
        self.status.values = decision.values
        self.status.decided_at = now
        if decision.command:
            await self._execute(decision.command, decision.power, decision.reason, decision.values)
        if changed_state:
            await self._save()
        self._notify()

    async def _execute(self, command: str, power: int, reason: str, values: dict) -> None:
        """Write a command to the Venus: the state (helpers) is already
        updated by the engine; now the registers, power first, then mode."""
        self.status.last_command = command
        self.status.last_command_power = power
        self.status.last_command_time = dt_util.utcnow()
        summary = " | ".join(f"{k}={v}" for k, v in values.items() if k in ("surplus_corr_w", "headroom_w", "house_need_w", "primary_discharge_w", "primary_charge_w", "parallel_allowed", "venus_first"))
        if self.settings.dry_run:
            self.status.dry_run_commands += 1
            await self._log(f"-> DRY RUN {command.upper()} {power}W | reason={reason} | {summary}")
            self.hass.bus.async_fire(EVENT_COMMAND, {"entry_id": self.entry.entry_id, "command": command, "power": power, "reason": reason, "dry_run": True})
            return
        await self._write(command, power)
        await self._log(f"-> {command.upper()} {power}W | reason={reason} | {summary}")
        self.hass.bus.async_fire(EVENT_COMMAND, {"entry_id": self.entry.entry_id, "command": command, "power": power, "reason": reason, "dry_run": False})

    async def _write(self, command: str, power: int) -> None:
        if command == MODE_CHARGE:
            await self._call("number", "set_value", {"entity_id": self._cfg(CONF_CHARGE_POWER), "value": power})
            await self._call("select", "select_option", {"entity_id": self._cfg(CONF_FORCE_MODE), "option": MODE_CHARGE})
        elif command == MODE_DISCHARGE:
            await self._call("number", "set_value", {"entity_id": self._cfg(CONF_DISCHARGE_POWER), "value": power})
            await self._call("select", "select_option", {"entity_id": self._cfg(CONF_FORCE_MODE), "option": MODE_DISCHARGE})
        else:
            await self._call("select", "select_option", {"entity_id": self._cfg(CONF_FORCE_MODE), "option": MODE_STANDBY})

    async def _call(self, domain: str, service: str, data: dict) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except Exception as err:  # noqa: BLE001 - a failed Modbus write must not stop the controller
            _LOGGER.warning("%s.%s on %s failed: %s", domain, service, data.get("entity_id"), err)

    async def _log(self, message: str) -> None:
        _LOGGER.info("%s: %s", self.entry.title, message)
        await self._call("logbook", "log", {"name": LOGBOOK_NAME, "message": message})

    # ------------------------------------------------------------------ manual
    async def async_manual(self, action: str) -> None:
        """Buttons: charge / discharge / stop switch the override on and
        write the command; auto stops the Venus and hands back to the master."""
        p = self.params()
        if action == "auto":
            self.state.last_charge_power = self.state.last_charge_target = self.state.last_discharge_power = 0
            await self._save()
            if not self.settings.dry_run:
                await self._write(MODE_STANDBY, 0)
            self.settings.manual_override = False
            await self._save()
            await self._log("-> AUTO MODE | manual_override=off")
            self._notify()
            await self._tick(dt_util.utcnow())
            return
        self.settings.manual_override = True
        if action == "charge":
            power = p.ac_charge_limit_w
            self.state.last_charge_power, self.state.last_charge_target, self.state.last_discharge_power = power, power, 0
            cmd = MODE_CHARGE
        elif action == "discharge":
            power = min(600, max(p.discharge_min_w, min(p.discharge_limit_w, int(p.discharge_cap_w // 100) * 100)))
            self.state.last_discharge_power, self.state.last_charge_power, self.state.last_charge_target = power, 0, 0
            cmd = MODE_DISCHARGE
        else:
            power = 0
            self.state.last_charge_power = self.state.last_charge_target = self.state.last_discharge_power = 0
            cmd = MODE_STANDBY
        await self._save()
        if self.settings.dry_run:
            await self._log(f"-> DRY RUN MANUAL {cmd.upper()} {power}W | manual_override=on")
        else:
            await self._write(cmd, power)
            await self._log(f"-> MANUAL {cmd.upper()} {power}W | manual_override=on")
        self.status.target_mode = "paused"
        self.status.reason = f"manual_{cmd}"
        self.status.text = f"Manual: {cmd} {power} W. Override switched on."
        self.status.last_command, self.status.last_command_power, self.status.last_command_time = cmd, power, dt_util.utcnow()
        self._notify()

    # ------------------------------------------------------------------ watchdog
    @callback
    def _rs485_changed(self, event: Event[EventStateChangedData]) -> None:
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        if new is not None and old is not None and old.state == "on" and new.state == "off":
            self.hass.async_create_task(self._watchdog(force=True, delay=15))

    async def _watchdog_tick(self, now: datetime) -> None:
        await self._watchdog(force=False)

    def _reg(self, key: str) -> float | None:
        return self._num(key)

    async def _watchdog(self, force: bool, delay: int = 0) -> None:
        if delay:
            import asyncio

            await asyncio.sleep(delay)
        rs = self.hass.states.get(self._cfg(CONF_RS485))
        if rs is None or rs.state not in ("on", "off"):
            return  # Modbus connection down: a write would not arrive anyway
        if not force and self._last_master_run and (dt_util.utcnow() - self._last_master_run).total_seconds() < 10:
            return  # the master just wrote; helpers and registers may still differ
        expected = self.state.expected_mode()
        cap = max(200, min(self.params().discharge_limit_w, int(self.settings.discharge_cap_w // 100) * 100))
        last_charge = self.state.last_charge_power
        last_discharge = min(self.state.last_discharge_power, cap)
        rs485_lost = rs.state == "off"
        ch = self._reg(CONF_CHARGE_POWER)
        dc = self._reg(CONF_DISCHARGE_POWER)
        charge_mismatch = last_charge > 0 and ch is not None and int(ch) != last_charge
        discharge_mismatch = last_discharge > 0 and dc is not None and int(dc) != last_discharge
        sel = self.hass.states.get(self._cfg(CONF_FORCE_MODE))
        select_mismatch = expected in (MODE_CHARGE, MODE_DISCHARGE) and (sel is None or sel.state != expected)
        status_mismatch = False
        if expected in (MODE_CHARGE, MODE_DISCHARGE) and self.settings.manual_override:
            st = self.hass.states.get(self._cfg(CONF_VENUS_STATE))
            if st is not None and sel is not None and st.state not in ("unknown", "unavailable", "") and (dt_util.utcnow() - st.last_changed).total_seconds() > 60 and (dt_util.utcnow() - sel.last_changed).total_seconds() > 60:
                mode_now = engine.current_mode(st.state)
                status_mismatch = mode_now != ("charge" if expected == MODE_CHARGE else "discharge")
        if not (rs485_lost or charge_mismatch or discharge_mismatch or select_mismatch or status_mismatch):
            return
        if self.settings.dry_run:
            await self._log(f"-> DRY RUN WATCHDOG | rs485_lost={rs485_lost} charge_mismatch={charge_mismatch} discharge_mismatch={discharge_mismatch} mode_mismatch={select_mismatch or status_mismatch} | would restore {expected}")
            return
        if rs485_lost:
            await self._call("switch", "turn_on", {"entity_id": self._cfg(CONF_RS485)})
            import asyncio

            await asyncio.sleep(5)
        if expected == MODE_CHARGE:
            await self._write(MODE_CHARGE, last_charge)
        elif expected == MODE_DISCHARGE:
            await self._write(MODE_DISCHARGE, last_discharge)
        else:
            await self._write(MODE_STANDBY, 0)
        self.status.watchdog_restores += 1
        await self._save()
        await self._log(f"-> RS485 WATCHDOG RESTORE | rs485_lost={rs485_lost} | charge_mismatch={charge_mismatch} | discharge_mismatch={discharge_mismatch} | mode_mismatch={select_mismatch or status_mismatch} | restored={expected} {last_charge if expected == MODE_CHARGE else last_discharge}W | count={self.status.watchdog_restores}")
        self._notify()

    # ------------------------------------------------------------------ cap guard
    @callback
    def _discharge_register_changed(self, event: Event[EventStateChangedData]) -> None:
        self.hass.async_create_task(self._cap_guard())

    async def _cap_guard_tick(self, now: datetime) -> None:
        await self._cap_guard()

    async def _cap_guard(self) -> None:
        cap = max(200, min(self.params().discharge_limit_w, int(self.settings.discharge_cap_w // 100) * 100))
        reg = self._reg(CONF_DISCHARGE_POWER)
        helper = self.state.last_discharge_power
        if reg is None or (reg <= cap and helper <= cap):
            return
        if helper > cap:
            self.state.last_discharge_power = cap
            await self._save()
        if reg > cap:
            if self.settings.dry_run:
                await self._log(f"-> DRY RUN DISCHARGE CAP | register={reg:.0f}W > cap {cap}W")
                return
            await self._call("number", "set_value", {"entity_id": self._cfg(CONF_DISCHARGE_POWER), "value": cap})
        self.status.cap_enforced += 1
        await self._log(f"-> DISCHARGE CAP enforced | register={reg:.0f}W | helper={helper}W -> {cap}W")
        self._notify()

    # ------------------------------------------------------------------ self-heal
    async def _self_heal_tick(self, now: datetime) -> None:
        ent = self._cfg(CONF_CONNECTION)
        st = self.hass.states.get(ent)
        if st is not None and st.state == "on":
            self._connection_lost_since = None
            return
        since = st.last_changed if st is not None else None
        if since is None or (dt_util.utcnow() - since) < SELF_HEAL_AFTER:
            return
        if self.settings.dry_run:
            await self._log("-> DRY RUN MODBUS SELF-HEAL | would reload the Modbus integration")
            return
        self.status.self_heals += 1
        await self._log(f"-> MODBUS SELF-HEAL: reloading the Modbus integration | connection={st.state if st else 'missing'}")
        try:
            await self.hass.config_entries.async_reload(self._cfg(CONF_MODBUS_ENTRY))
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Reload of the Modbus config entry failed: %s", err)
        self._notify()
