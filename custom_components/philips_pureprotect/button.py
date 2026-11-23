"""Actions on the purifier that are not a setting."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import Key
from .coordinator import PureProtectConfigEntry, PureProtectCoordinator
from .entity import PureProtectEntity, add_when_reported

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: PureProtectConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Add the button for a cleaned filter when the device reports its counter."""
    add_when_reported(
        entry,
        async_add_entities,
        [FilterCleanedButton],
        lambda _: (Key.FILTER_CLEAN_LEFT, Key.FILTER_CLEAN_TOTAL),
        lambda coordinator, cls: cls(coordinator),
    )


class FilterCleanedButton(PureProtectEntity, ButtonEntity):
    """Tell the purifier that its filter was cleaned, as the Air+ app does.

    The app sets the hours until the next cleaning back to the full interval
    (seen: 719 to 720, docs/metingen.md measurement 7), and the device takes
    that value from the network (measurement 14).
    """

    _attr_translation_key = "filter_cleaned"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PureProtectCoordinator) -> None:
        """Create the button."""
        super().__init__(coordinator, "filter_cleaned")

    async def async_press(self) -> None:
        """Set the cleaning counter back to the full interval."""
        total = self.coordinator.value(Key.FILTER_CLEAN_TOTAL)
        if not total or total <= 0:
            raise self.coordinator.error("filter_interval_unknown")
        await self.coordinator.async_write({Key.FILTER_CLEAN_LEFT: total})
