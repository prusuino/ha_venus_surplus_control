# Changelog

## 0.5.0 — 2026-11-12

- **The first battery's "empty" can follow its reserve.** New optional input *First battery: reserve* under Configure (a sensor, a number or a number helper). With it, the Venus takes over from the first battery at the reserve plus 3 points instead of the fixed 12 % (never below 12 %), so it keeps working when you raise the reserve on your inverter, for example in winter. While the reading is unavailable the last value is kept. Without the input nothing changes.
- **Discharge to a target SoC.** The new button `button.<name>_discharge_to_target_soc` discharges the Venus at the discharge cap until it is at `number.<name>_target_soc` (5–100 %, default 50), then puts it into standby and leaves the manual override on. `binary_sensor.<name>_discharging_to_target_soc` shows the run; the event `venus_surplus_command` fires with the reason `target_soc_reached` at the end.
- Setups without a first battery work as before: the reserve input is not needed there, and the target discharge is only a button.

## 0.4.0 — 2026-11-12

- **Fixed: the charge power stayed low after a load peak.** On a Venus without MPPT sensors the charge power could go down but never up again while charging: after a washing machine or kettle had pushed it down, it stayed there until charging stopped and started anew. It now follows the surplus up again. With MPPT sensors a zero reading holds the power back for four ticks only; a reading that stays low is believed. Reported by @VIMVa (#1).
- **Charge reserve is adjustable.** The new number `number.<name>_charge_reserve` (0–500 W, default 200 W as before) sets how much surplus the Venus leaves alone while charging. Lower it to use more of a small surplus.
- **Steps up sooner.** The charge power goes one 100 W step up once the headroom is 150 W above the current target (250 W before), so less surplus stays unused after a dip.

## 0.3.0 — 2026-11-09

- **Version on the service card.** The integration's version now appears on its service card under Settings → Devices & services, where the entities are listed.
- **Repair notice.** Readings that stay incomplete for about five minutes raise a notice under Settings → Repairs naming the missing or unavailable entities; it withdraws itself. No change to entities or configuration.

## 0.2.0 — 2026-11-09

- **Quality scale Bronze.** The integration keeps its controller in the config entry's runtime data, the README gained removal instructions and a quality-scale section, and the manifest declares the **bronze** tier. A test suite (decision engine: readiness, charge, parallel wait, discharge, SoC protection, cross-trip, persisted state; config flow with both steps, one entry per Venus and the options flow) runs on every push. No change to entities or configuration.

## 0.1.0 — 2026-11-08

First release. The controller logic of the YAML package ha-marstek-venus-surplus as an integration with a setup dialog:

- master decision every 30 s (charge from surplus, discharge against house demand, standby; cross-charging protection next to an inverter-coupled battery; "Venus first" on good solar days; hysteresis and confirmation counters)
- RS485 watchdog, discharge cap guard, Modbus self-heal
- dry run (default for new entries), manual override, manual buttons
- sensors, binary sensors, numbers, switches, buttons; diagnostics download; event `venus_surplus_command`
- English and German
