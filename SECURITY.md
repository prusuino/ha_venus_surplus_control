# Security Policy

## Supported Versions

Only the latest release is supported. Please update to the latest version before reporting an issue.

## Reporting a Vulnerability

This integration talks to nothing outside Home Assistant. It opens no network connection, has no credentials and no third-party dependencies.

**What it reads:** the states of the entities you pick in the setup (the surplus sensor or grid meter, the Venus entities of the Marstek Venus Modbus integration, and optionally the first battery, the PV forecast, the MPPT sensors and the Modbus connection sensor), and the next sunset from the `sun` integration.

**What it changes:** only the Venus entities you picked, through ordinary Home Assistant actions: the *Force Mode* select, the *Set charge power* and *Set discharge power* numbers and the *RS485 control mode* switch. If you name the Marstek Venus Modbus config entry in the setup, it reloads that entry after a long loss of the Modbus connection. Nothing else is touched. In dry run, which every new entry starts in, it changes nothing at all and only writes to the logbook what it would do.

**What it stores:** the config entry (the entity IDs you picked, the limits and options); and one file per entry under `.storage` (`venus_surplus.<entry id>`) with what has to survive a restart: the last commands and counters, the values you set on the device page, the learned night load and the reporting intervals of the surplus sensor. The file is removed with the entry. The diagnostics download holds the same plus the current readings of the configured entities; there are no secrets to redact.

**Dashboard card:** the bundled card is served as a static file from the integration's own folder (`/venus_surplus_files/venus-surplus-card.js`). It reads entity states through the frontend connection, sends nothing anywhere and escapes every value before it is placed in the page.

**A note on safety:** the integration commands a battery inverter. A wrong sign on the surplus or AC power sensor can make the Venus charge when it should discharge. That is why new entries start in dry run: check the decisions in the logbook before switching it off.

If you believe you have found a security issue, please report it privately via [GitHub Security Advisories](../../security/advisories/new) rather than opening a public issue. For anything else, please use the regular [Issues](../../issues) tab.
