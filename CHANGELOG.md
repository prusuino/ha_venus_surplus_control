# Changelog

## 0.1.0 — 2026-11-08

First release. The controller logic of the YAML package ha-marstek-venus-surplus as an integration with a setup dialog:

- master decision every 30 s (charge from surplus, discharge against house demand, standby; cross-charging protection next to an inverter-coupled battery; "Venus first" on good solar days; hysteresis and confirmation counters)
- RS485 watchdog, discharge cap guard, Modbus self-heal
- dry run (default for new entries), manual override, manual buttons
- sensors, binary sensors, numbers, switches, buttons; diagnostics download; event `venus_surplus_command`
- English and German
