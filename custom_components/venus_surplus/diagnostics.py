"""Diagnostics download: configuration, persisted state, last decision and
the current readings of the configured entities."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import engine
from .const import DOMAIN
from .controller import VenusController


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    c: VenusController = hass.data[DOMAIN][entry.entry_id]
    readings = {}
    for key, value in {**entry.data, **entry.options}.items():
        ents = value if isinstance(value, list) else [value]
        for ent in ents:
            if isinstance(ent, str) and "." in ent and not ent.startswith("01"):
                st = hass.states.get(ent)
                readings[ent] = None if st is None else {"state": st.state, "unit": st.attributes.get("unit_of_measurement"), "last_changed": st.last_changed.isoformat()}
    s = c.status
    return {
        "entry": {"data": dict(entry.data), "options": dict(entry.options)},
        "settings": c.settings.__dict__,
        "state": engine.state_to_dict(c.state),
        "status": {
            "target_mode": s.target_mode,
            "reason": s.reason,
            "text": s.text,
            "values": s.values,
            "decided_at": s.decided_at.isoformat() if s.decided_at else None,
            "last_command": s.last_command,
            "last_command_power": s.last_command_power,
            "watchdog_restores": s.watchdog_restores,
            "cap_enforced": s.cap_enforced,
            "self_heals": s.self_heals,
            "dry_run_commands": s.dry_run_commands,
        },
        "readings": readings,
    }
