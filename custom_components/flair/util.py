"""Utilities for Flair Integration"""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import ClientResponse
from flairaio import FlairClient
from flairaio.exceptions import FlairAuthError, FlairError
from flairaio.model import (
    Bridge,
    FlairData,
    HVACUnit,
    Puck,
    Room,
    Schedule,
    Structure,
    Thermostat,
    User,
    Vent,
    Zone,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import LOGGER, FLAIR_ERRORS, TIMEOUT


class FlairApiClient(FlairClient):
    """FlairClient with strict response handling and per-structure data.

    flairaio 0.2.0 returns None for unrecognised non-200 responses, so a
    failed PATCH looks like a success, and it shares one set of device
    dictionaries between all structures on the account. Both are fixed
    here until the dependency is.
    """

    @staticmethod
    async def _response(resp: ClientResponse) -> dict[str, Any] | None:
        """Return the JSON body of a successful response or raise."""

        if resp.status == 204:
            return None

        try:
            response = await resp.json(content_type=None)
        except ValueError:
            response = None

        if 200 <= resp.status < 300:
            if response is None:
                text = await resp.text()
                raise FlairError(f'Flair server response is not json: {text[:200]}')
            return response

        detail = _error_detail(response) if response is not None else (await resp.text())[:200]
        if resp.status in (401, 403) or (
            isinstance(response, dict) and response.get('error') == 'invalid_client'
        ):
            raise FlairAuthError(f'HTTP {resp.status}: {detail}')
        if resp.status == 429:
            retry_after = resp.headers.get('Retry-After')
            raise FlairError(f'HTTP 429 rate limited (Retry-After: {retry_after}): {detail}')
        raise FlairError(f'HTTP {resp.status}: {detail}')

    async def get_flair_data(self) -> FlairData:
        """Return all data, with each structure's devices kept separate."""

        users: dict[str, User] = dict((await self.get_users()).users)
        structures_data: dict[str, Structure] = {}

        for structure in (await self.get_structures()).structures.values():
            (rooms, pucks, vents, thermostats, hvac_units, zones, schedules,
             bridges) = await self.fetch_all_structure_relations(structure)
            structures_data[structure.id] = Structure(
                id=structure.id,
                attributes=structure.attributes,
                relationships=structure.relationships,
                rooms=_build(Room, rooms),
                pucks=await self._build_with_reading(Puck, pucks),
                vents=await self._build_with_reading(Vent, vents),
                bridges=await self._build_with_reading(Bridge, bridges),
                thermostats=_build(Thermostat, thermostats),
                hvac_units=_build(HVACUnit, hvac_units),
                zones=_build(Zone, zones),
                schedules=_build(Schedule, schedules),
            )
        return FlairData(users=users, structures=structures_data)

    async def _build_with_reading(self, cls, items: list | None) -> dict[str, Any]:
        """Build devices that carry a current reading when active."""

        devices = _build(cls, items, current_reading=None)
        for device in devices.values():
            if not device.attributes['inactive']:
                reading = await self.get_related(device, 'current-reading')
                device.current_reading = (
                    reading['attributes'] if isinstance(reading, dict) else {}
                )
            else:
                device.current_reading = {}
        return devices


def _build(cls, items: list | None, **extra: Any) -> dict[str, Any]:
    """Build a fresh id -> model dictionary from JSON:API resources."""

    return {
        item['id']: cls(
            id=item['id'],
            attributes=item['attributes'],
            relationships=item['relationships'],
            **extra,
        )
        for item in items or []
    }


def _error_detail(response: Any) -> str:
    """Summarise a Flair error body."""

    if isinstance(response, dict):
        errors = response.get('errors')
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            base = errors[0]
            return ': '.join(str(base[k]) for k in ('title', 'detail') if base.get(k))
        if 'error' in response:
            return str(response.get('error_description') or response['error'])
    return str(response)[:200]


async def async_validate_api(hass: HomeAssistant, client_id: str, client_secret: str) -> bool:
    """Get data from API."""

    client = FlairApiClient(
        client_id,
        client_secret,
        session=async_get_clientsession(hass),
        timeout=TIMEOUT,
    )

    try:
        async with asyncio.timeout(TIMEOUT):
            users_query = await client.get_users()
            structures_query = await client.get_structures()
    except FlairAuthError as err:
        LOGGER.error(f'Could not authenticate on Flair servers: {err}')
        raise
    except FLAIR_ERRORS as err:
        LOGGER.error(f'Failed to get information from Flair servers: {err}')
        raise ConnectionError from err

    users: dict[str, User] = users_query.users
    structures: dict[str, Structure] = structures_query.structures

    if not users:
        LOGGER.error("Could not retrieve any users from Flair servers")
        raise NoUserError("No users found on Flair account")
    if not structures:
        LOGGER.error('Could not retrieve any structures from Flair servers')
        raise NoStructuresError("No structures found on Flair account")
    return True


class NoUserError(Exception):
    """ No User from Flair API. """


class NoStructuresError(Exception):
    """ No Structures from Flair API. """
