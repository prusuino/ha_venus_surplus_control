"""Bundled card: the sensor it reads names the Venus entities of the setup,
and the card file is served."""
from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.venus_surplus.const import CONF_VENUS_AC_INVERT, CONF_VENUS_PV, DOMAIN
from custom_components.venus_surplus.controller import VenusController
from custom_components.venus_surplus.frontend import CARD_FILENAME, CARD_URL

from .test_repairs import DATA


async def test_card_sources_name_the_venus_entities(hass: HomeAssistant, enable_custom_integrations) -> None:
    data = {**DATA, CONF_VENUS_AC_INVERT: True, CONF_VENUS_PV: ["sensor.venus_mppt1", "sensor.venus_mppt2"]}
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=data)
    entry.add_to_hass(hass)
    sources = VenusController(hass, entry).card_sources()
    assert sources == {
        "soc_entity": "sensor.venus_soc",
        "ac_power_entity": "sensor.venus_ac_power",
        "ac_power_inverted": True,
        "pv_entities": ["sensor.venus_mppt1", "sensor.venus_mppt2"],
        "capacity_entity": None,
        "capacity_fallback_kwh": 5.12,
        "primary_power_entity": None,
        "primary_power_inverted": False,
        "primary_soc_entity": None,
    }


# The sun dependency sets up its own polled sensors; their timer outlives the test.
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_setup_serves_the_card_and_fills_the_attributes(hass: HomeAssistant, enable_custom_integrations, expected_lingering_timers) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=f"{DOMAIN}_select.venus_force_mode", title="Venus", data=DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.venus_target_mode")
    assert state is not None
    assert state.attributes["soc_entity"] == "sensor.venus_soc"
    assert state.attributes["ac_power_entity"] == "sensor.venus_ac_power"
    assert state.attributes["pv_entities"] == []

    assert CARD_URL == "/venus_surplus_files/venus-surplus-card.js"
    card = Path(__file__).parents[1] / "custom_components" / DOMAIN / "frontend" / CARD_FILENAME
    assert card.is_file()
    assert await hass.config_entries.async_unload(entry.entry_id)
