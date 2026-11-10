![Venus Surplus Control](readme_header.png)

# Venus Surplus Control

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/prusuino/ha_venus_surplus_control)](https://github.com/prusuino/ha_venus_surplus_control/releases)
[![Validate](https://github.com/prusuino/ha_venus_surplus_control/actions/workflows/validate.yml/badge.svg)](https://github.com/prusuino/ha_venus_surplus_control/actions/workflows/validate.yml)
[![Tests](https://github.com/prusuino/ha_venus_surplus_control/actions/workflows/tests.yml/badge.svg)](https://github.com/prusuino/ha_venus_surplus_control/actions/workflows/tests.yml)
[![Home Assistant](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprusuino%2Fha_venus_surplus_control%2Fmain%2Fhacs.json&query=%24.homeassistant&label=Home%20Assistant&suffix=%2B&color=41BDF5)](https://www.home-assistant.io/)
[![Quality scale](https://img.shields.io/badge/Quality%20Scale-Bronze-cd7f32.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
<a href="https://www.buymeacoffee.com/prusuino"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="20"></a>

A Home Assistant integration that runs a **Marstek Venus** battery from your PV surplus, next to an existing inverter-coupled battery or alone. No YAML: you pick your entities in the setup dialog, the controller does the rest.

## Highlights

- **Charge from real surplus only** – AC charging follows the surplus headroom in 100 W steps, capped so that AC charge plus the Venus' own PV stay below the device limit. While your first battery (BYD, Pylontech, …) is still absorbing the surplus, the Venus waits; on a good solar day ("Venus first") it may start early in parallel because both will fill up anyway.
- **Discharge against house demand only** – 200–1000 W in steps with hysteresis, an export guard that steps down before the house would export, and only while the first battery is already delivering or empty.
- **Standby otherwise** – and an immediate stop when the first battery suddenly works against the Venus (cross-charging). The two batteries never charge each other.
- **RS485 watchdog** – the Venus firmware drops the RS485 control mode and resets its power registers on restarts, app or cloud access. The watchdog restores the control mode and the last command.
- **Discharge cap** – a ceiling you set from the dashboard that every command respects and that is enforced again when the app or a firmware reset raises the register.
- **Modbus self-heal** – reloads the Marstek Venus Modbus integration after a long connection loss.
- **Dry run** – new entries start in dry run: the controller decides and writes every command it *would* send to the logbook, but touches nothing. Switch it off when the decisions look right.
- **Manual buttons** – charge, discharge, stop and back to auto.
- **Diagnostics** – target mode, reason and the decision in words, every value behind it as attributes, a diagnostics download, and a logbook line for every command with its reasons.

This is the logic of the YAML package [ha-marstek-venus-surplus](https://github.com/prusuino/ha-marstek-venus-surplus), which has run on my Venus A next to an inverter-coupled battery since summer 2026, rebuilt as an integration so that it needs no YAML and no helpers.

## Requirements

- A Marstek Venus (A, C, D or E) reachable over Modbus TCP and the **[Marstek Venus Modbus](https://github.com/ViperRNMC/marstek_venus_modbus)** integration by ViperRNMC. This integration uses its *Force Mode* select (options standby / charge / discharge), the *Set charge power* and *Set discharge power* numbers, the *RS485 control mode* switch, SoC, AC power and inverter state. The Venus accepts one Modbus client; do not run a second tool against it.
- A power sensor giving **PV production minus house consumption** in W (surplus positive), or a grid meter (tick "import positive" in the setup).
- Optional: power and SoC of your first battery, a PV forecast for today and the remaining day in kWh (for example Solcast), the Venus' MPPT power sensors (A/D), its total capacity, the Modbus connection sensor.
- Home Assistant 2025.4 or newer.

## Installation

Through the **Marketplace** (Settings → Marketplace → Add from link → `prusuino/ha_venus_surplus_control`, category Integration) or HACS as a custom repository, then restart Home Assistant. Manual: copy `custom_components/venus_surplus` into your `custom_components` folder.

## Setup

Settings → Devices & services → Add integration → **Venus Surplus Control**.

1. **Required**: a name, your surplus sensor, and the seven Venus entities (Force Mode, two power numbers, RS485 switch, SoC, AC power, inverter state). Check the sign of the AC power sensor: positive must mean the Venus is *delivering* into the house; tick the invert box otherwise.
2. **Optional**: the Venus' MPPT sensors and capacity, your first battery's power (positive = discharging; tick invert if yours is the other way round) and SoC, the forecasts, the Modbus connection sensor and the Modbus config entry (for the self-heal reload), and the device limits (AC charge 1200 W, total 1400 W, discharge 1000 W for a Venus A – raise them for a D or E).

Everything can be changed later under **Configure**.

## Entities

![Example dashboard with the decision and its reason, the measurements, the coordination with the primary battery, the controls and the limits](docs/dashboard.png)

| Entity | Meaning |
|---|---|
| `sensor.<name>_target_mode` | charge / discharge / standby / no data / paused, with the reason, the last command and the dry-run flag as attributes |
| `sensor.<name>_reason` | why: surplus with first battery full, parallel charging, house demand, own PV used directly, Venus SoC protection, cross-charging trip, no condition, incomplete data, manual |
| `sensor.<name>_last_decision` | the decision in words; every value behind it (surplus, headroom, house demand, first battery, forecast, latches, counters) as attributes |
| `sensor.<name>_surplus_3_min_mean`, `…_surplus_without_venus_3_min_mean` | what the controller decides on |
| `sensor.<name>_charge_headroom`, `…_house_demand` | surplus minus reserve; grid import corrected for the Venus |
| `sensor.<name>_charge_command`, `…_discharge_command` | the last commanded power |
| `sensor.<name>_watchdog_restores`, `…_dry_run_commands` | counters |
| `binary_sensor.<name>_charging`, `…_discharging`, `…_venus_first`, `…_parallel_charging_allowed`, `…_cross_charging_block` | states for your automations |
| `switch.<name>_manual_override` | pauses the controller |
| `switch.<name>_dry_run` | decide and log only |
| `number.<name>_discharge_cap` | ceiling for the discharge power |
| `number.<name>_venus_first_from_forecast` | today's forecast (kWh) from which the Venus may charge in parallel early (default 45) |
| `number.<name>_first_battery_capacity`, `…_venus_capacity_fallback`, `…_house_base_load` | for the remaining-forecast rule |
| `button.<name>_manual_charge`, `…_manual_discharge`, `…_manual_stop`, `…_back_to_auto` | manual control |

Every command also fires the event `venus_surplus_command` with `command`, `power`, `reason` and `dry_run`.

## How it decides

Every 30 seconds (adjustable) the controller takes a sample of the surplus and of the surplus with the Venus' own AC flow taken out, keeps three minutes of samples and decides on their means:

1. **Protect** – Venus SoC ≤ 12 %: standby. First battery discharging > 500 W while the Venus charges (or charging while it discharges): standby ("cross trip").
2. **Charge** if the AC command would be ≥ 100 W and either the first battery is ≥ 85 % (80 % to hold) or parallel charging is allowed: surplus ≥ 1200 W and headroom ≥ 500 W on an ordinary day (600 / 400 W when "Venus first"), the first battery not discharging more than 80 W and, on an ordinary day, not absorbing more than 200 W (500 W to hold). Charging is blocked while the first battery discharges more than 150 W (200 W to hold, confirmed over two ticks; 350 W immediately). Power: headroom minus 200 W reserve, floored to 100 W, start from 400 W, hold down to 80 W for three ticks, step up only 250 W above the current target, step down only 120 W below it; minus the Venus' own PV against the total limit.
3. **Discharge** if the house imports and the surplus mean is below 100 W, the Venus is above 15 % (12 % to hold), the first battery delivers ≥ 500 W or is ≤ 12 %, and the first battery is not charging more than 100 W. Power: import minus 120 W reserve, 200–1000 W in 100 W steps, one step per tick up (40 W above the next step) or down (40 W below the previous one), never above the export guard (import minus 60 W) or the discharge cap.
4. **Standby** otherwise.

"Venus first" is true when today's forecast is above the threshold, when the remaining forecast covers both batteries plus the house until sunset with 20 % margin and there is real surplus now (≥ 2500 W), or when a projection from the current surplus shows the first battery full long before sunset while the Venus would not make it. The two latter latch until sunset.

Missing input values for two consecutive ticks put the Venus into standby.

## Dry run and first days

Leave **dry run** on for a day or two. The logbook (filter "Venus Surplus") shows every command with its reasons; `sensor.<name>_last_decision` shows the values. When the decisions match what you expect, switch dry run off. The controller then writes its standing decision to the Venus right away.

## Repairs

When the controller has had no complete readings for about five minutes (an entity of the Venus or the surplus sensor missing or unavailable), a notice under **Settings → Repairs** names the entities concerned; it disappears as soon as the readings are complete again.

## Removal

1. Switch **dry run** on or put the Venus into standby yourself first if a command is running: the integration sends no final command when it is removed.
2. **Settings → Devices & services → Venus Surplus Control**, open the entry's menu (⋮) and choose **Delete**. The entities, their history, the device and the persisted controller state go with the entry.
3. Remove the integration itself in the **Marketplace** (or HACS; it was added from a link), then restart Home Assistant. With a manual installation, delete `custom_components/venus_surplus` instead. The Marstek Venus Modbus integration is not affected.

## Quality scale

The integration declares **Bronze** on the [Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/): a config flow with tests, unique ids for every entity, brand images, installation and removal instructions, a connection check before an entry is created, no duplicate entries, runtime data on the config entry, and the other Bronze rules. The tier is self-assessed, as it is for every custom integration; the per-rule status, including what is still open for Silver and Gold, is in `custom_components/venus_surplus/quality_scale.yaml`.

## Disclaimer

Provided **as-is, without any warranty**. The integration writes charge and discharge commands to a battery. Wrong sensors, signs or thresholds can cost energy or battery life. Keep the manual override within reach. Not affiliated with Marstek; all product names belong to their owners.

## License

MIT – see [LICENSE](LICENSE).

## Related projects

More of my Home Assistant projects:

- [ha-marstek-venus-surplus](https://github.com/prusuino/ha-marstek-venus-surplus) — the same logic as a YAML package
- [Swiss Meteo](https://github.com/prusuino/ha_swiss_meteo) — MeteoSwiss open data: local forecast, live station values, official warnings, pollen, radar, station history and dashboard cards
- [Swiss Solar Reference Price](https://github.com/prusuino/ha_swiss_solar_reference_price) — Swiss solar feed-in reference market price
- [Swiss Electricity Price](https://github.com/prusuino/ha_swiss_electricity_price) — official ElCom electricity tariffs for your municipality

## Support

<a href="https://www.buymeacoffee.com/prusuino"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="41"></a>
