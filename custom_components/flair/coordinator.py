"""DataUpdateCoordinator for the Flair integration."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError

from flairaio.exceptions import FlairAuthError, FlairError
from flairaio.model import FlairData


from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    LOGGER,
    PUCK2_STALE_AFTER,
)
from .model import Puck2
from .util import FlairApiClient

PUCK2_ERRORS = (FlairError, asyncio.TimeoutError, ClientError)


class FlairDataUpdateCoordinator(DataUpdateCoordinator):
    """Flair Data Update Coordinator."""

    data: FlairData

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the Flair coordinator."""

        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        timeout = entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

        self.client = FlairApiClient(
            entry.data[CONF_CLIENT_ID],
            entry.data[CONF_CLIENT_SECRET],
            session=async_get_clientsession(hass),
            timeout=timeout,
        )
        self._puck2_list_ok: dict[str, datetime] = {}
        self._puck2_reading_ok: dict[str, datetime] = {}
        self._known_puck2_ids: set[str] | None = None
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> FlairData:
        """Fetch data from Flair."""

        try:
            data = await self.client.get_flair_data()
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(
                    'Found %d Flair structure(s): %s',
                    len(data.structures),
                    [s.attributes['name'] for s in data.structures.values()],
                )
                for structure in data.structures.values():
                    LOGGER.debug(
                        'Structure "%s" relationship keys: %s',
                        structure.attributes['name'],
                        list(structure.relationships.keys()),
                    )
        except FlairAuthError as error:
            raise ConfigEntryAuthFailed(error) from error
        except FlairError as error:
            raise UpdateFailed(error) from error
        if not data.structures:
            raise UpdateFailed("No Structures found")

        previous_data: FlairData | None = getattr(self, 'data', None)
        now = dt_util.utcnow()
        puck2_ids: set[str] = set()

        for structure_id, structure in data.structures.items():
            previous_puck2s: dict[str, Puck2] = {}
            if previous_data is not None:
                prev_structure = previous_data.structures.get(structure_id)
                if prev_structure is not None:
                    previous_puck2s = getattr(prev_structure, 'puck2s', {})

            if 'puck2s' not in structure.relationships:
                structure.puck2s = {}
                continue

            try:
                raw_list = await self.client.get_related(structure, 'puck2s')
                if not isinstance(raw_list, list):
                    raise FlairError(f'Unexpected puck2s payload: {type(raw_list).__name__}')
            except FlairAuthError as err:
                raise ConfigEntryAuthFailed(err) from err
            except PUCK2_ERRORS as err:
                if previous_data is None:
                    # Without a first list there is nothing to create entities
                    # from; fail so Home Assistant retries setup.
                    raise UpdateFailed(f'Failed to fetch Puck V2 devices: {err}') from err
                last_ok = self._puck2_list_ok.get(structure_id)
                fresh = last_ok is not None and now - last_ok < PUCK2_STALE_AFTER
                LOGGER.warning(
                    'Failed to fetch puck2s for structure %s (%s); %s (%d puck2 device(s)): %s: %s',
                    structure_id,
                    structure.attributes.get('name', 'unknown'),
                    'retaining previous data' if fresh else 'marking devices offline',
                    len(previous_puck2s),
                    type(err).__name__,
                    err,
                )
                structure.puck2s = (
                    previous_puck2s if fresh
                    else {pid: _offline(p) for pid, p in previous_puck2s.items()}
                )
                continue
            self._puck2_list_ok[structure_id] = now

            puck2s: dict[str, Puck2] = {}
            for raw in raw_list:
                if not (
                    isinstance(raw, dict)
                    and isinstance(raw.get('id'), str)
                    and isinstance(raw.get('attributes'), dict)
                    and isinstance(raw.get('relationships'), dict)
                ):
                    LOGGER.warning('Skipping malformed puck2 record in structure %s', structure_id)
                    continue
                obj = Puck2(
                    id=raw['id'],
                    attributes=raw['attributes'],
                    relationships=raw['relationships'],
                )
                if raw['attributes'].get('inactive', True):
                    obj.current_reading = {}
                else:
                    obj.current_reading = await self._async_puck2_reading(
                        obj, previous_puck2s.get(raw['id']), now
                    )
                puck2s[raw['id']] = obj
                puck2_ids.add(raw['id'])

            # A device missing from a successful list has been removed or
            # moved; keep it as offline so its entities go unavailable.
            for puck2_id, prior in previous_puck2s.items():
                if puck2_id not in puck2s:
                    puck2s[puck2_id] = _offline(prior)
            structure.puck2s = puck2s

        if self._known_puck2_ids is None:
            self._known_puck2_ids = puck2_ids
        elif new_ids := puck2_ids - self._known_puck2_ids:
            # Entities are only created at setup, so reload to add them.
            LOGGER.info('Found new Puck V2 device(s) %s; reloading', sorted(new_ids))
            self._known_puck2_ids |= new_ids
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

        return data

    async def _async_puck2_reading(
        self, obj: Puck2, prior: Puck2 | None, now: datetime
    ) -> dict[str, Any]:
        """Fetch a Puck V2 current reading, reusing a recent one on failure."""

        error: Exception | str = 'no current-reading in response'
        if 'current-reading' in obj.relationships:
            try:
                reading = await self.client.get_related(obj, 'current-reading')
            except FlairAuthError as err:
                raise ConfigEntryAuthFailed(err) from err
            except PUCK2_ERRORS as err:
                error = err
            else:
                if isinstance(reading, dict) and isinstance(reading.get('attributes'), dict):
                    self._puck2_reading_ok[obj.id] = now
                    return reading['attributes']

        last_ok = self._puck2_reading_ok.get(obj.id)
        keep = prior is not None and last_ok is not None and now - last_ok < PUCK2_STALE_AFTER
        LOGGER.warning(
            'Failed to fetch current-reading for puck2 %s; using %s: %s',
            obj.id,
            'previous reading' if keep else 'empty reading',
            error,
        )
        return prior.current_reading if keep else {}


def _offline(puck2: Puck2) -> Puck2:
    """Return a copy of a Puck V2 marked offline with no reading."""

    return Puck2(
        id=puck2.id,
        attributes={**puck2.attributes, 'inactive': True},
        relationships=puck2.relationships,
        current_reading={},
    )
