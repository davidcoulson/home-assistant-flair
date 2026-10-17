"""Tests for Flair climate entities."""
from __future__ import annotations

import itertools
from types import SimpleNamespace
from unittest.mock import MagicMock, call

from flairaio.exceptions import FlairError
from flairaio.model import HVACUnit, Room
import pytest

from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.climate.const import ATTR_HVAC_MODE
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.flair import climate
from custom_components.flair.climate import HVAC, RoomTemp, StructureClimate
from custom_components.flair.const import DOMAIN

from .common import attach, make_coordinator, make_data, make_structure


def _room(rid: str = "r1") -> Room:
    return Room(
        id=rid,
        attributes={"name": rid, "current-temperature-c": 20.0, "set-point-c": 21.0},
        relationships={},
    )


def _hvac(hid: str = "h1", fan: bool = True, swing: bool = True, **attributes) -> HVACUnit:
    speeds = {"FAN AUTO": {}, "FAN HI": {}} if fan else {}
    return HVACUnit(
        id=hid,
        attributes={
            "name": hid,
            "make-name": "Acme",
            "constraints": {
                "temperature-scale": "C",
                "ON": {m: {"ON": speeds} for m in ("COOL", "HEAT", "DRY", "FAN", "AUTO")},
            },
            "codesets": [],
            "power": "On",
            "mode": "Cool",
            "swing": "On" if swing else None,
            "fan-speed": "Auto",
            "temperature": 22,
            **attributes,
        },
        relationships={"room": {"data": {"id": "r1"}}, "puck2": {"data": None}},
    )


def _structure(**attributes):
    structure = make_structure(**attributes)
    structure.rooms = {"r1": _room()}
    structure.hvac_units = {"h1": _hvac()}
    return structure


async def test_structure_set_temperature_applies_mode(hass: HomeAssistant) -> None:
    """A combined temperature + mode call changes both (M8)."""

    coordinator = make_coordinator(make_data(_structure(**{"structure-heat-cool-mode": "float"})))
    entity = attach(StructureClimate(coordinator, "s1"), hass)

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 22, ATTR_HVAC_MODE: HVACMode.HEAT})

    assert coordinator.client.update.await_args_list == [
        call("structures", "s1", attributes={"structure-heat-cool-mode": "heat"}, relationships={}),
        call("structures", "s1", attributes={"set-point-temperature-c": 22}, relationships={}),
    ]


async def test_structure_mode_only_does_not_send_null_setpoint(hass: HomeAssistant) -> None:
    """A mode-only call never sends a null set point (M8)."""

    coordinator = make_coordinator(make_data(_structure()))
    entity = attach(StructureClimate(coordinator, "s1"), hass)

    await entity.async_set_temperature(**{ATTR_HVAC_MODE: HVACMode.COOL})

    coordinator.client.update.assert_awaited_once_with(
        "structures", "s1", attributes={"structure-heat-cool-mode": "cool"}, relationships={}
    )


async def test_room_set_temperature_applies_mode(hass: HomeAssistant) -> None:
    """RoomTemp also honours a requested mode (M8)."""

    coordinator = make_coordinator(make_data(_structure(**{"structure-heat-cool-mode": "float"})))
    entity = attach(RoomTemp(coordinator, "s1", "r1"), hass)

    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 19, ATTR_HVAC_MODE: HVACMode.HEAT})

    assert coordinator.client.update.await_args_list == [
        call("structures", "s1", attributes={"structure-heat-cool-mode": "heat"}, relationships={}),
        call("rooms", "r1", attributes={"set-point-c": 19, "active": True}, relationships={}),
    ]


async def test_structure_temperature_limits(hass: HomeAssistant) -> None:
    """Flair's set-point limits are exposed as min/max temp (M11)."""

    entity = attach(StructureClimate(make_coordinator(make_data(_structure())), "s1"), hass)
    assert (entity.min_temp, entity.max_temp) == (10.0, 32.23)


@pytest.mark.parametrize(
    ("mode", "power", "fan", "swing", "hvac_mode"),
    list(itertools.product(("auto", "manual"), ("On", "Off"), (True, False), (True, False), ("Cool", "Dry"))),
)
def test_hvac_supported_features_always_a_mask(hass, mode, power, fan, swing, hvac_mode) -> None:
    """Every mode/power/fan/swing combination returns a feature mask (M9)."""

    structure = _structure(mode=mode)
    structure.hvac_units = {"h1": _hvac(fan=fan, swing=swing, power=power, mode=hvac_mode)}
    entity = attach(HVAC(make_coordinator(make_data(structure)), "s1", "h1"), hass)

    features = entity.supported_features
    assert isinstance(features, ClimateEntityFeature)
    assert bool(features & ClimateEntityFeature.FAN_MODE) == (fan and not (mode == "manual" and power == "Off"))
    assert bool(features & ClimateEntityFeature.SWING_MODE) == (swing and not (mode == "manual" and power == "Off"))


def test_hvac_auto_powered_off_fan_only(hass) -> None:
    """The combination the review found returning None (M9)."""

    structure = _structure(mode="auto")
    structure.hvac_units = {"h1": _hvac(fan=True, swing=False, power="Off")}
    entity = attach(HVAC(make_coordinator(make_data(structure)), "s1", "h1"), hass)
    assert entity.supported_features == (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE
    )


async def test_setup_survives_incomplete_codesets(hass: HomeAssistant) -> None:
    """Empty or missing codesets don't stop other climates loading (M10)."""

    structure = _structure()
    no_scale = _hvac("h2")
    del no_scale.attributes["constraints"]["temperature-scale"]
    no_scale.attributes["codesets"] = None
    structure.hvac_units = {"h1": _hvac("h1"), "h2": no_scale}
    coordinator = make_coordinator(make_data(structure))
    entry = SimpleNamespace(entry_id="e1")
    hass.data[DOMAIN] = {"e1": coordinator}
    add = MagicMock()

    await climate.async_setup_entry(hass, entry, add)

    entities = add.call_args.args[0]
    assert [type(e).__name__ for e in entities] == ["StructureClimate", "RoomTemp", "HVAC"]
    assert entities[2].hvac_id == "h1"


async def test_failed_command_keeps_cached_state(hass: HomeAssistant) -> None:
    """A failed PATCH propagates and leaves cached power unchanged (H1)."""

    structure = _structure(mode="manual")
    coordinator = make_coordinator(make_data(structure))
    coordinator.client.update.side_effect = FlairError("HTTP 500")
    entity = attach(HVAC(coordinator, "s1", "h1"), hass)

    with pytest.raises(FlairError):
        await entity.async_turn_off()
    assert structure.hvac_units["h1"].attributes["power"] == "On"


async def test_missing_puck_repair_cleared_on_removal(hass: HomeAssistant) -> None:
    """The missing-Puck repair is deleted when the entity is removed (L3)."""

    entity = attach(HVAC(make_coordinator(make_data(_structure())), "s1", "h1"), hass)
    assert entity.available is False
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "hvac_no_puck_h1") is not None

    await entity.async_will_remove_from_hass()
    assert registry.async_get_issue(DOMAIN, "hvac_no_puck_h1") is None
