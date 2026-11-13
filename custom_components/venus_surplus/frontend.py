"""Serving of the bundled Lovelace card (venus-surplus-card.js).

Registers a static path so the card file in this integration's frontend/
directory is reachable under /venus_surplus_files/. Adding it as a Lovelace
resource is left to the user: the resource list belongs to the dashboard
configuration the user controls. The README documents the one-time step.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "venus-surplus-card.js"
CARD_URL = f"/{DOMAIN}_files/{CARD_FILENAME}"
_REGISTERED_FLAG = f"{DOMAIN}_card_served"


async def async_serve_card(hass: HomeAssistant) -> None:
    """Make the bundled card file reachable over HTTP.

    Once per Home Assistant run; safe to call from every entry setup. The
    flag is claimed before the await so that two entries setting up at the
    same time do not register twice, and released again if the registration
    raises, so that the next setup retries.
    """
    if hass.data.get(_REGISTERED_FLAG):
        return
    hass.data[_REGISTERED_FLAG] = True
    registered = False
    try:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "frontend" / CARD_FILENAME), cache_headers=False)]
        )
        registered = True
    finally:
        if not registered:
            hass.data.pop(_REGISTERED_FLAG, None)
    _LOGGER.debug("Serving the bundled card at %s", CARD_URL)
