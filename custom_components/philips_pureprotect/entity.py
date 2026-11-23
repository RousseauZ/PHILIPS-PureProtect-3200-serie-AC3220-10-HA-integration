"""Base class of the PureProtect entities."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import PureProtectConfigEntry, PureProtectCoordinator


class PureProtectEntity(CoordinatorEntity[PureProtectCoordinator]):
    """An entity of one purifier."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PureProtectCoordinator, name: str) -> None:
        """Set the identity; ``name`` is the stable part of the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{name}"
        self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        """Follow the session: silence is never unavailability."""
        return self.coordinator.available


@callback
def add_when_reported[D](
    entry: PureProtectConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    descriptions: Iterable[D],
    needs: Callable[[D], Iterable[str]],
    create: Callable[[PureProtectCoordinator, D], PureProtectEntity],
) -> None:
    """Create the entities whose keys the device reports, now and when new keys appear.

    Before the first status the keys are the ones of the model. An entity that
    was created on that assumption is removed again when the device turns out
    not to report its key.
    """
    coordinator = entry.runtime_data
    pending = list(descriptions)
    assumed: list[tuple[D, PureProtectEntity]] = []

    @callback
    def add() -> None:
        if assumed and not coordinator.keys_assumed:
            registry = er.async_get(coordinator.hass)
            for item, entity in assumed:
                if not coordinator.keys.issuperset(needs(item)):
                    if entity.registry_entry is not None:
                        registry.async_remove(entity.entity_id)
                    pending.append(item)
            assumed.clear()
        ready = [item for item in pending if coordinator.keys.issuperset(needs(item))]
        if not ready:
            return
        created = [(item, create(coordinator, item)) for item in ready]
        for item in ready:
            pending.remove(item)
        if coordinator.keys_assumed:
            assumed.extend(created)
        async_add_entities(entity for _, entity in created)

    add()
    entry.async_on_unload(coordinator.async_add_listener(add))
