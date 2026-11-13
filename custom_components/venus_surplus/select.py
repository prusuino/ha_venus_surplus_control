"""Select: how quickly the controller follows the surplus."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_REACTION, REACTION_MINUTES
from .controller import VenusController
from .entity import VenusEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([ReactionSelect(entry.runtime_data)])


class ReactionSelect(VenusEntity, SelectEntity):
    """Calm, normal or fast: the surplus is averaged over 5, 3 or 1 minute."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:speedometer"
    _attr_options = list(REACTION_MINUTES)

    def __init__(self, c: VenusController) -> None:
        super().__init__(c, "reaction")

    @property
    def current_option(self) -> str:
        value = self.controller.settings.reaction
        return value if value in REACTION_MINUTES else DEFAULT_REACTION

    async def async_select_option(self, option: str) -> None:
        await self.controller.async_set_setting("reaction", option)
