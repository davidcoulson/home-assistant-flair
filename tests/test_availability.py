"""Every entity reports unavailable when the coordinator update failed (M4)."""
from __future__ import annotations

import importlib
import inspect
from unittest.mock import MagicMock

import pytest

from homeassistant.helpers.update_coordinator import CoordinatorEntity

PLATFORMS = ["binary_sensor", "button", "climate", "cover", "number", "select", "sensor", "switch"]


def _entity_classes():
    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.flair.{platform}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and issubclass(cls, CoordinatorEntity):
                yield cls


def test_all_custom_availability_found() -> None:
    """Guard against the parametrised test silently covering nothing."""

    overrides = [cls for cls in _entity_classes() if "available" in cls.__dict__]
    assert len(overrides) == 49


@pytest.mark.parametrize(
    "cls", list(_entity_classes()), ids=lambda cls: f"{cls.__module__.rsplit('.', 1)[1]}.{cls.__name__}"
)
def test_unavailable_when_coordinator_failed(cls) -> None:
    """Cached data must not keep an entity available after a failed poll."""

    entity = cls.__new__(cls)
    entity.coordinator = MagicMock(last_update_success=False)
    assert entity.available is False
