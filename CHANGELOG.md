# Changelog

## 0.9.4 — 2026-11-15

- **The Venus helps with a small load too.** It started discharging only once the first battery delivered 500 W or more. A house with a base load of 200–300 W never got there: the first battery carried the night alone and ran empty, while the Venus stood by fully charged and took over only afterwards, alone and without the first battery to cover what it leaves. Now the Venus also starts when the first battery has been delivering 150 W or more for six ticks. It takes most of the load, the first battery lasts longer and keeps regulating the meter. At 500 W and more it starts at once, as before. Suggested by the report of @VIMVa (#4).

## 0.9.3 — 2026-11-15

- **A Venus that is the only source follows the house demand closely.** The discharge power stayed a step below the demand: 50 W steps, a reserve and an export guard. Next to a first battery that is right, because the first battery follows the meter and covers the rest. With the first battery empty or at rest, or without one, nobody covers the rest: a house drawing 210 W got 150 W and imported 60 W, all night. In that case the Venus now moves in 10 W steps with an export guard of 5 % (10–30 W) and no reserve: 190 W for a house drawing 210 W, 870 W for one drawing 900 W. Next to a first battery that delivers, nothing changes. Tested on a real Venus A, which takes commands between the 50 W steps. Reported by @VIMVa (#4).

## 0.9.2 — 2026-11-15

- **A control mode that is already off at the start is restored at once.** The watchdog acted the moment the RS485 control mode went off, but not when it was off before the integration started (switched off in the app, or the Venus restarted in the meantime): the commands then went nowhere until the next five-minute run. The start now looks at the control mode and restores it within seconds.
- README: a Venus A takes about 1000 W from the grid whatever the charge command says, also in the manual mode of the Marstek app. The measured values and the right setting for *Maximum AC charge command* are described.

## 0.9.1 — 2026-11-15

- **The discharge power climbs faster.** When the house suddenly needed more, the power went up by 50 W per tick: from 400 to 1000 W took six minutes, longer than a kettle runs. How far it may rise per tick now follows *Reaction*: 50 W on *Calm* (as before), 100 W on *Normal*, 200 W on *Fast*. The power still sits on 50 W steps, and coming down is immediate as before. Measured on a real Venus A.

## 0.9.0 — 2026-11-15

- **A silent surplus sensor is no longer believed.** A sensor that kept its last value without reporting (a meter or an integration that hangs) was read as if the value were current: frozen at a large surplus the Venus would have charged on from the grid, frozen at a large demand it would have exported. A surplus sensor that is silent for far longer than it has ever been now counts as missing: no commands, standby after two ticks, and a repair notice that names the sensor and ends with its next report. The limit is learned per sensor from the gaps between its reports (three times the longest gap of the last seven days, at least 10 minutes), so that a sensor that only reports when its value changes is not taken for a dead one. Nothing is judged in the first 24 hours.
- **Values kept over a lost Modbus connection are no longer believed.** While the connection to the Venus is down (a restart of the Venus, for example), the Modbus integration keeps showing the last value of every sensor. The controller went on deciding with them: it saw a Venus charging at the power of minutes ago. With a connection sensor set up, a lost connection now counts as missing readings: no decision, standby after two ticks, and a fresh decision once the connection is back. Found on a real Venus A.
- **The watchdog acts as soon as the Venus is back.** After a restart of the Venus the RS485 control mode is off and the command is gone. The watchdog restored both at its next five-minute run, which left the Venus standing by for up to five minutes. It now also runs 15 seconds after the Modbus connection returns and when the control mode switch comes back in the off position.
- **New diagnostic sensor *Control quality*.** *Stable*, *Changing mode often*, *Venus does less than commanded*, *Venus does not respond*, *Collecting data* or *Paused*, with the mode changes of the last 30 minutes and the share of the command the Venus follows as attributes. While charging it names the reason for a Venus that takes less than commanded, where it is known: *Cells cold* (below 20 °C), *Cells warm* (from 40 °C) or *Nearly full* (from 90 %); in each the battery management of the Venus cuts the charge current. The cell temperatures are read from the Marstek Venus Modbus integration without any setup (enable its two cell temperature sensors). It changes no decision; it answers the first questions of a bug report. Also in the diagnostics download.
- **Repair notice when the Venus ignores its command.** A charge or discharge command that has stood for 10 minutes without any answer is named under Settings → Repairs. Not in dry run.
- **The limits stop at what the number entities take.** A charge or discharge limit above the maximum of the number entity behind it led to commands Home Assistant refused; they never reached the Venus, and only a warning in the log said so. The limits now stop at that maximum.

## 0.8.10 — 2026-11-14

- **The AC limits stop at 3600 W.** *Maximum AC charge command* and *Maximum discharge command* accepted up to 5000 W in the setup form, more than any Venus takes or delivers over AC. Both now end at 3600 W, the rating of the largest model; an entry that holds a higher value is treated as 3600 W. The defaults stay at 1200 W and 1000 W.

## 0.8.9 — 2026-11-14

- **Fixed: a full Venus was still told to charge.** At 100 % the controller kept the charge command and showed *Surplus, first battery full* with a setpoint, although the Venus took nothing. A Venus that stands at 100 % and takes nothing for four ticks now goes to standby with the new reason *Venus is full*; charging comes back once it is below 98 %. A Venus that still takes power at a displayed 100 % keeps its command until it stops. Reported by @VIMVa (#3).

## 0.8.8 — 2026-11-13

- **Fixed: a house with a small night load was served badly.** With a demand of 180–250 W the Venus either did not start discharging at all, or, since 0.8.5, delivered only 100 W and left more than half of the house to the grid: the fixed reserve of 120 W and the 100 W steps were made for larger loads. Discharging now moves in 50 W steps, the reserve is 20 % of the demand (40 to 120 W), the export guard 10 % (30 to 60 W), and the minimum is 100 W for every house. A house drawing 220 W now gets 150 W from the Venus. Above 600 W of demand the reserve and the guard are as before; only the steps are finer. Reported by @VIMVa (#2).
- **Fixed: a paused first battery kept the Venus from discharging.** The Venus waited for the first battery to deliver or to be empty. One that is paused or in standby does neither, so the Venus stood by all night with a charged battery. If the first battery delivers nothing although the house has been importing for six ticks, the Venus now takes over (new reason *House demand, first battery delivers nothing*). Reported by @VIMVa (#2).
- **The learned night load no longer sets the minimum discharge power.** The rule from 0.8.5 (100 W below 300 W of night load, 200 W otherwise) made a small house worse off, not better, and did nothing in the first night. The sensor *Learned night load* stays as a diagnostic value.
- A feed-in limit is now kept in 50 W steps as well (a Venus delivering 150 W of own PV on top of a 600 W command is set to 450 W instead of 400 W).

## 0.8.7 — 2026-11-13

- **Dutch and Spanish.** The setup forms, the entity names, the reasons, the repair notices and the card are now also available in Dutch and Spanish, next to English, German, French and Italian.

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
