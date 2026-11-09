"""Constants of the Venus Surplus Control integration."""
from __future__ import annotations
import json
from pathlib import Path

from datetime import timedelta

DOMAIN = "venus_surplus"

# --- config entry data: the entities this controller reads and writes ---------
CONF_NAME = "name"
CONF_SURPLUS = "surplus_entity"  # PV production minus house consumption [W], surplus positive
CONF_SURPLUS_INVERT = "surplus_invert"  # the sensor is a grid meter with import positive
CONF_FORCE_MODE = "force_mode_entity"  # select: standby / charge / discharge
CONF_CHARGE_POWER = "charge_power_entity"  # number [W]
CONF_DISCHARGE_POWER = "discharge_power_entity"  # number [W]
CONF_RS485 = "rs485_entity"  # switch: RS485 control mode
CONF_VENUS_SOC = "venus_soc_entity"
CONF_VENUS_AC = "venus_ac_entity"  # AC power [W], positive = delivering into the house
CONF_VENUS_AC_INVERT = "venus_ac_invert"
CONF_VENUS_STATE = "venus_state_entity"  # inverter state sensor
CONF_VENUS_PV = "venus_pv_entities"  # MPPT power sensors (Venus A/D), optional
CONF_VENUS_CAPACITY = "venus_capacity_entity"  # total battery energy [kWh], optional
CONF_CONNECTION = "connection_entity"  # binary_sensor: Modbus connection, optional
CONF_MODBUS_ENTRY = "modbus_entry_id"  # config entry of the Modbus integration (self-heal), optional
CONF_PRIMARY_POWER = "primary_power_entity"  # first battery power [W], positive = discharging, optional
CONF_PRIMARY_POWER_INVERT = "primary_power_invert"
CONF_PRIMARY_SOC = "primary_soc_entity"  # optional
CONF_FORECAST_TODAY = "forecast_today_entity"  # kWh, optional
CONF_FORECAST_REMAINING = "forecast_remaining_entity"  # kWh, optional
CONF_FORECAST_FACTOR = "forecast_factor"  # dampening of the remaining forecast

# --- options: thresholds that are no entities ---------------------------------
CONF_AC_CHARGE_LIMIT = "ac_charge_limit_w"
CONF_TOTAL_CHARGE_LIMIT = "total_charge_limit_w"
CONF_DISCHARGE_LIMIT = "discharge_limit_w"
CONF_TICK_SECONDS = "tick_seconds"

DEFAULT_FORECAST_FACTOR = 0.8
DEFAULT_AC_CHARGE_LIMIT = 1200
DEFAULT_TOTAL_CHARGE_LIMIT = 1400
DEFAULT_DISCHARGE_LIMIT = 1000
DEFAULT_TICK_SECONDS = 30

# defaults of the adjustable number entities
DEFAULT_FIRST_FORECAST_KWH = 45.0
DEFAULT_PRIMARY_KWH = 10.0
DEFAULT_VENUS_KWH = 5.12
DEFAULT_BASE_LOAD_KW = 0.5
DEFAULT_DISCHARGE_CAP = 1000

MEAN_WINDOW = timedelta(minutes=3)
WATCHDOG_SECOND = 17
WATCHDOG_MINUTES = (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55)
CAP_GUARD_SECOND = 47
SELF_HEAL_SECOND = 41
SELF_HEAL_MINUTES = (1, 11, 21, 31, 41, 51)
SELF_HEAL_AFTER = timedelta(minutes=5)

MODE_CHARGE = "charge"
MODE_DISCHARGE = "discharge"
MODE_STANDBY = "standby"

# states of the inverter state sensor that mean charging / discharging
CHARGING_STATES = ("charging", "charge")
DISCHARGING_STATES = ("selling", "discharging", "discharge")

EVENT_COMMAND = f"{DOMAIN}_command"
LOGBOOK_NAME = "Venus Surplus"

STORAGE_VERSION = 1

# The integration's own version, shown on the service card. Read from the
# manifest so that a release never needs to touch two places.
VERSION: str = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))["version"]
