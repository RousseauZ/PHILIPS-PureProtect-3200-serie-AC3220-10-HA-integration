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
    """Add the filter buttons when the device reports their counters."""
    add_when_reported(
        entry,
        async_add_entities,
        [FilterCleanedButton],
        lambda _: (Key.FILTER_CLEAN_LEFT, Key.FILTER_CLEAN_TOTAL),
        lambda coordinator, cls: cls(coordinator),
    )
    add_when_reported(
        entry,
        async_add_entities,
        [FilterReplacedButton],
        lambda _: (Key.FILTER_LIFE_LEFT, Key.FILTER_LIFE_TOTAL),
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


class FilterReplacedButton(PureProtectEntity, ButtonEntity):
    """Tell the purifier that a new filter was fitted.

    Sets the hours of filter life back to the full life the device reports.
    The counter takes a value from the network (docs/metingen.md, measurement
    14). Not seen in the Air+ app; press it only after fitting a new filter.
    """

    _attr_translation_key = "filter_replaced"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PureProtectCoordinator) -> None:
        """Create the button."""
        super().__init__(coordinator, "filter_replaced")

    async def async_press(self) -> None:
        """Set the filter life back to full."""
        total = self.coordinator.value(Key.FILTER_LIFE_TOTAL)
        if not total or total <= 0:
            raise self.coordinator.error("filter_life_unknown")
        await self.coordinator.async_write({Key.FILTER_LIFE_LEFT: total})
