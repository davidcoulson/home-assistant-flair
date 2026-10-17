"""Synthetic Flair data for tests."""
from __future__ import annotations

from flairaio.model import FlairData, Structure

from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flair.const import DOMAIN


def make_entry(client_id: str = "client") -> MockConfigEntry:
    """Return a current-version Flair config entry."""

    return MockConfigEntry(
        domain=DOMAIN,
        version=2.1,
        unique_id=client_id,
        data={CONF_CLIENT_ID: client_id, CONF_CLIENT_SECRET: "secret"},
    )


def make_structure(sid: str = "s1", with_puck2s: bool = True, **attributes) -> Structure:
    """Return a structure with no devices."""

    relationships = {"puck2s": {"links": {"related": f"/api/structures/{sid}/puck2s"}}}
    return Structure(
        id=sid,
        attributes={
            "name": f"Home {sid}",
            "mode": "auto",
            "structure-heat-cool-mode": "heat",
            "set-point-temperature-c": 21.0,
            "set-point-mode": "Home Evenness For Active Rooms Flair Setpoint",
            **attributes,
        },
        relationships=relationships if with_puck2s else {},
        rooms={},
        pucks={},
        vents={},
        bridges={},
        thermostats={},
        hvac_units={},
        zones={},
        schedules={},
    )


def make_data(*structures: Structure) -> FlairData:
    """Wrap structures in FlairData."""

    return FlairData(users={"u": None}, structures={s.id: s for s in structures})


def raw_puck2(pid: str, inactive: bool = False, **attributes) -> dict:
    """Return a JSON:API Puck V2 list record."""

    return {
        "id": pid,
        "attributes": {
            "name": pid,
            "inactive": inactive,
            "current-temperature-c": 20.5,
            **attributes,
        },
        "relationships": {
            "current-reading": {"links": {"related": f"/api/puck2s/{pid}/current-reading"}}
        },
    }


def make_coordinator(data: FlairData):
    """Return a mock coordinator serving data."""

    from unittest.mock import AsyncMock, MagicMock

    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    coordinator.client.update = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def attach(entity, hass):
    """Attach an entity to hass without adding it to a platform."""

    from unittest.mock import MagicMock

    entity.hass = hass
    entity.async_write_ha_state = MagicMock()
    return entity
