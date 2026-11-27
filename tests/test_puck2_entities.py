"""Tests for Puck V2 number and sensor entities."""
from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.flair.model import Puck2
from custom_components.flair.number import Puck2LowerLimit, Puck2UpperLimit
from custom_components.flair.sensor import Gateway, Puck2RSSI

from .common import attach, make_coordinator, make_data, make_structure


def _setup(attributes: dict, reading: dict | None = None):
    structure = make_structure()
    structure.puck2s = {
        "p1": Puck2(
            id="p1",
            attributes={"name": "p1", "inactive": False, **attributes},
            relationships={},
            current_reading=reading or {},
        )
    }
    return make_coordinator(make_data(structure))


async def test_lower_limit_with_null_upper_bound(hass: HomeAssistant) -> None:
    """An explicit null opposite bound falls back to the default (M12)."""

    hass.config.units = US_CUSTOMARY_SYSTEM
    coordinator = _setup({"setpoint-bound-low": 10, "setpoint-bound-high": None})
    entity = attach(Puck2LowerLimit(coordinator, "s1", "p1"), hass)
    assert entity.available is True
    assert entity.native_max_value == round(32.0 * 9 / 5 + 32, 0)


async def test_upper_limit_with_null_lower_bound(hass: HomeAssistant) -> None:
    """The upper-limit entity has the symmetric fallback (M12)."""

    coordinator = _setup({"setpoint-bound-low": None, "setpoint-bound-high": 30})
    entity = attach(Puck2UpperLimit(coordinator, "s1", "p1"), hass)
    assert entity.native_min_value == 10.0


async def test_rssi_and_gateway_from_current_reading(hass: HomeAssistant) -> None:
    """V2 RSSI and gateway come from the current reading (L2)."""

    coordinator = _setup(
        {"current-rssi": None, "connected-gateway-id": None, "connected-gateway-type": None},
        {"sub-ghz-rssi": -66, "connected-gateway-name": "Hall bridge"},
    )
    rssi = attach(Puck2RSSI(coordinator, "s1", "p1"), hass)
    gateway = attach(Gateway(coordinator, "s1", "p1", "puck2s"), hass)
    assert rssi.native_value == -66
    assert gateway.native_value == "Hall bridge"


async def test_rssi_falls_back_to_list_attribute(hass: HomeAssistant) -> None:
    """Without a reading, the list attribute is still used (L2)."""

    coordinator = _setup({"current-rssi": -70})
    assert attach(Puck2RSSI(coordinator, "s1", "p1"), hass).native_value == -70
