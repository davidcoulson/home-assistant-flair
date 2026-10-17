"""Tests for the Flair coordinator's Puck V2 handling."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientConnectionError, ClientPayloadError
from flairaio.exceptions import FlairError
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

from custom_components.flair.const import PUCK2_STALE_AFTER
from custom_components.flair.coordinator import FlairDataUpdateCoordinator
from custom_components.flair.util import async_validate_api

from .common import make_data, make_entry, make_structure, raw_puck2


class FakeApi:
    """Stand-in for FlairApiClient driven by per-test responses."""

    def __init__(self) -> None:
        self.puck2s: list | Exception = [raw_puck2("p1")]
        self.readings: dict = {}

    async def get_flair_data(self):
        return make_data(make_structure())

    async def get_related(self, obj, related_type):
        if related_type == "puck2s":
            if isinstance(self.puck2s, Exception):
                raise self.puck2s
            return self.puck2s
        reading = self.readings.get(obj.id, {"attributes": {"sub-ghz-rssi": -60}})
        if isinstance(reading, Exception):
            raise reading
        return reading


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
async def coordinator(hass: HomeAssistant, api: FakeApi) -> FlairDataUpdateCoordinator:
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.flair.coordinator.FlairApiClient", return_value=api):
        return FlairDataUpdateCoordinator(hass, entry)


async def _refresh(coordinator) -> None:
    coordinator.data = await coordinator._async_update_data()


def _puck2s(coordinator):
    return coordinator.data.structures["s1"].puck2s


async def test_first_refresh_puck2_failure_raises(coordinator, api) -> None:
    """A failed initial Puck V2 list makes setup retry, not succeed empty (M3)."""

    api.puck2s = FlairError("HTTP 500")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_transport_error_keeps_other_data(coordinator, api) -> None:
    """aiohttp errors use the Puck V2 fallback instead of failing (M6)."""

    await _refresh(coordinator)
    api.puck2s = ClientConnectionError("reset")
    await _refresh(coordinator)
    assert _puck2s(coordinator)["p1"].attributes["inactive"] is False


async def test_stale_puck2_data_goes_offline(coordinator, api) -> None:
    """Retained Puck V2 data expires after the grace period (M5)."""

    await _refresh(coordinator)
    api.puck2s = FlairError("HTTP 500")
    await _refresh(coordinator)
    assert _puck2s(coordinator)["p1"].attributes["inactive"] is False

    coordinator._puck2_list_ok["s1"] = dt_util.utcnow() - PUCK2_STALE_AFTER - timedelta(seconds=1)
    await _refresh(coordinator)
    p1 = _puck2s(coordinator)["p1"]
    assert p1.attributes["inactive"] is True
    assert p1.current_reading == {}


async def test_stale_reading_expires(coordinator, api) -> None:
    """A failing current-reading is reused only for the grace period (M5)."""

    await _refresh(coordinator)
    api.readings["p1"] = FlairError("HTTP 500")
    await _refresh(coordinator)
    assert _puck2s(coordinator)["p1"].current_reading == {"sub-ghz-rssi": -60}

    coordinator._puck2_reading_ok["p1"] = dt_util.utcnow() - PUCK2_STALE_AFTER - timedelta(seconds=1)
    await _refresh(coordinator)
    assert _puck2s(coordinator)["p1"].current_reading == {}


@pytest.mark.parametrize("reading", [None, {"attributes": None}, {}])
async def test_null_reading_does_not_abort_update(coordinator, api, reading) -> None:
    """A null current-reading leaves that device without a reading (M7)."""

    api.readings["p1"] = reading
    await _refresh(coordinator)
    assert _puck2s(coordinator)["p1"].current_reading == {}


async def test_malformed_record_is_skipped(coordinator, api) -> None:
    """Records missing attributes or relationships are skipped (M7)."""

    api.puck2s = [{"id": "bad", "attributes": None}, raw_puck2("p1")]
    await _refresh(coordinator)
    assert list(_puck2s(coordinator)) == ["p1"]


async def test_removed_device_goes_offline(coordinator, api) -> None:
    """A device missing from a successful list is kept as offline (M3)."""

    await _refresh(coordinator)
    api.puck2s = []
    await _refresh(coordinator)
    assert _puck2s(coordinator)["p1"].attributes["inactive"] is True


async def test_new_device_schedules_reload(hass: HomeAssistant, coordinator, api) -> None:
    """A Puck V2 added after setup triggers a reload to create entities (M3)."""

    await _refresh(coordinator)
    api.puck2s = [raw_puck2("p1"), raw_puck2("p2")]
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await _refresh(coordinator)
        await _refresh(coordinator)
    reload.assert_called_once_with(coordinator.config_entry.entry_id)


async def test_validate_payload_error_is_cannot_connect(hass: HomeAssistant) -> None:
    """A truncated body during validation maps to ConnectionError (M6)."""

    client = MagicMock()
    client.get_users = AsyncMock(side_effect=ClientPayloadError("truncated"))
    with (
        patch("custom_components.flair.util.FlairApiClient", return_value=client),
        pytest.raises(ConnectionError),
    ):
        await async_validate_api(hass, "id", "secret")
