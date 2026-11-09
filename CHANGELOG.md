# Changelog

## 0.3.0 — 2026-11-09

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
