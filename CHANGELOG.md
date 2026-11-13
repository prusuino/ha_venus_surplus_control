# Changelog

## 0.8.6 — 2026-11-13

- **French and Italian.** The setup forms, the entity names, the reasons and the repair notices are now translated into French and Italian, next to English and German. The card already was.

## 0.8.5 — 2026-11-13

- **Calmer discharging with a small base load.** Discharging starts at about 300 W of house demand and used to stop again below 260 W. In a house whose base load sits around that, every fridge cycle switched the Venus on and off. A discharge running at the minimum of 200 W now keeps going until the house needs less than 160 W; in that band up to 40 W are exported. Starting, the steps above 200 W and the export guard for them are unchanged.
- **The controller learns your night load.** While the sun is down the surplus sensor shows nothing but the house; the controller takes what the house typically draws from the last seven nights (new diagnostic sensor *Learned night load*). A house below 300 W gets a minimum discharge power of 100 W instead of 200 W, so that the Venus serves it at night instead of standing by with a charged battery. Above 300 W, and until the first full night, nothing changes.
- **Minimum discharge power can be set by hand.** New number under *Configuration* on the device page: 0 = automatic as above (default), or 100–500 W.

## 0.8.4 — 2026-11-13

- **A debug log worth downloading.** With *Enable debug logging* on the integration's page switched on, the controller writes one line per tick: what it read, what it decided and why. Switch it off again and Home Assistant offers the log as a download. Numbers and flags only, no entity names; nothing is written while debug logging is off.

## 0.8.3 — 2026-11-13

- **The setup finds your Venus.** The entities of the Marstek Venus Modbus integration (Force Mode, the two power numbers, RS485 switch, SoC, AC power, inverter state, MPPT inputs, capacity, connection sensor and the Modbus entry) are filled in when you add the integration, whatever they are called in your language. They are suggestions: change or remove any of them before you save. With more than one Venus, the first one without a controller is suggested. Existing entries are not touched.

## 0.8.2 — 2026-11-13

- **A first battery that is switched off no longer stops the Venus.** New option under Configure, *Carry on without the first battery when its readings are missing* (off by default): after 5 minutes without power or SoC readings of the first battery, the controller runs the Venus alone and says so in a repair notice; when the readings return, the first battery counts again. Without the option nothing changes: the controller waits in standby.

## 0.8.1 — 2026-11-13

- **Card: MPPT inputs stay once they have delivered.** An input that has delivered power once keeps its bar on the card and reads 0 W in the night, instead of disappearing until the next morning. Inputs with nothing connected stay hidden. The controller remembers which inputs have delivered, across restarts.

## 0.8.0 — 2026-11-13

- **A dashboard card.** The integration ships the card *Venus Surplus* (`custom:venus-surplus-card`): state of charge as a gauge, charge and discharge power, energy in the battery, what the controller is doing and why with the commanded power, and a chart of the last hours. A first battery stands next to the Venus with its own SoC and power, and the Venus' own PV appears by itself, one bar per MPPT input, as soon as an input delivers. It is pointed at the *Target mode* sensor, whose attributes now name the Venus entities of the setup. Registering the card as a dashboard resource is a one-time step, see the README.
- **README: running the Venus without a first battery.** A new section under Setup says which fields to leave empty, how the Venus then charges and discharges, and which settings have no effect.

## 0.7.0 — 2026-11-13

- **Three more values are adjustable.** *Charge from surplus of* (headroom from which charging starts, default 400 W as before), *Reaction* (calm, normal or fast: the surplus is averaged over 5, 3 or 1 minute; normal is the 3 minutes used so far) and *Venus charges from first battery SoC* (default 85 % as before; 0 = the Venus never waits for the first battery). Without a change the behaviour stays the same. Asked for by @VIMVa (#2).
- **A tidier device page.** The values you set once are now under *Configuration*; *Controls* keeps the buttons, the two switches, *Maximum discharge power* and *Manual discharge target SoC*.
- **Names that say what happens.** *Discharge cap* is *Maximum discharge power*, *Charge reserve* is *Charging buffer*, *Venus first from forecast* is *Charge in parallel from daily forecast*, *Target SoC* is *Manual discharge target SoC* and its button *Manual discharge to target SoC* (the pair is for discharging by hand, the automatic control does not use it), the surplus sensors are *Surplus (mean)*. *House base load* is entered in W instead of kW (the stored value carries over). Existing entries keep their entity IDs.
- **More help.** More fields under Configure explain themselves. The README has two new sections: "Which setting does what" as a quick table, and "Settings in detail", which describes every setting on the device page and under Configure: what it does, why it is there, an example and when to change it.

## 0.6.1 — 2026-11-13

- **Fixed: an empty Venus did not charge.** At 12 % or below the SoC protection stopped everything, charging included, and the reason read "Venus SoC too low". A Venus with its own PV got out of this by itself in the morning; one without stayed empty. The protection now only blocks discharging. Reported by @VIMVa (#2).
- **A first battery that takes nothing leaves the surplus to the Venus.** If the first battery neither charges nor discharges for six ticks (three minutes at the default interval) although there is at least 400 W of headroom, for example because it is in standby or limited, the Venus charges from that surplus whatever the first battery's SoC. As soon as the first battery charges or discharges again, the usual rules apply. New reason `charge_primary_idle`.

## 0.6.0 — 2026-11-13

- **Feed-in limit at the plug.** New setting under Configure: *None*, *600 W* (common limit in Switzerland), *800 W* (Germany, Austria) or your own value. The discharge command, the discharge cap and the manual buttons stay below it; a discharge cap set higher is lowered at the next start. The command is what the Venus delivers at the plug; its own PV goes into the battery, not on top. As a safeguard, AC measured above the command while discharging is taken off the command, but never below 200 W and never into standby; `feed_in_exceeded` in the diagnostics shows when the AC delivery is still above the limit. Charging is not limited. Without a choice nothing changes.

## 0.5.0 — 2026-11-12

- **The first battery's "empty" can follow its reserve.** New optional input *First battery: reserve* under Configure (a sensor, a number or a number helper). With it, the Venus takes over from the first battery at the reserve plus 3 points instead of the fixed 12 % (never below 12 %), so it keeps working when you raise the reserve on your inverter, for example in winter. While the reading is unavailable the last value is kept. Without the input nothing changes.
- **Discharge to a target SoC.** The new button `button.<name>_discharge_to_target_soc` discharges the Venus at the discharge cap until it is at `number.<name>_target_soc` (12–100 %, default 50), then puts it into standby and leaves the manual override on. `binary_sensor.<name>_discharging_to_target_soc` shows the run; the event `venus_surplus_command` fires with the reason `target_soc_reached` at the end.
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
