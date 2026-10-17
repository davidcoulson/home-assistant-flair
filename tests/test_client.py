"""Tests for the FlairApiClient wrapper around flairaio."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from flairaio.exceptions import FlairAuthError, FlairError
import pytest

from custom_components.flair.util import FlairApiClient


class FakeResponse:
    """Minimal stand-in for aiohttp.ClientResponse."""

    def __init__(self, status: int, body: str = "", headers: dict | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def json(self, content_type=None):
        return json.loads(self._body)

    async def text(self):
        return self._body


JSONAPI_ERROR = json.dumps({"errors": [{"title": "Server Error", "detail": "boom"}]})


@pytest.mark.parametrize("status", [400, 404, 409, 422, 500, 502, 503, 504])
async def test_error_status_raises(status: int) -> None:
    """Every unsuccessful status raises instead of returning None."""

    with pytest.raises(FlairError, match=f"HTTP {status}"):
        await FlairApiClient._response(FakeResponse(status, JSONAPI_ERROR))


@pytest.mark.parametrize("body", ["<html>Bad gateway</html>", ""])
async def test_error_status_non_json_raises(body: str) -> None:
    """Non-JSON error bodies raise too."""

    with pytest.raises(FlairError):
        await FlairApiClient._response(FakeResponse(500, body))


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_status_raises_auth_error(status: int) -> None:
    """401/403 are classified as auth failures."""

    with pytest.raises(FlairAuthError):
        await FlairApiClient._response(FakeResponse(status, JSONAPI_ERROR))


async def test_invalid_client_raises_auth_error() -> None:
    """The token endpoint's invalid_client error is an auth failure."""

    body = json.dumps({"error": "invalid_client"})
    with pytest.raises(FlairAuthError):
        await FlairApiClient._response(FakeResponse(400, body))


async def test_rate_limit_keeps_retry_after() -> None:
    """429 raises with the Retry-After value in the message."""

    with pytest.raises(FlairError, match="Retry-After: 30"):
        await FlairApiClient._response(
            FakeResponse(429, JSONAPI_ERROR, {"Retry-After": "30"})
        )


async def test_success_statuses() -> None:
    """200/201 return the body and 204 returns None."""

    body = json.dumps({"data": []})
    assert await FlairApiClient._response(FakeResponse(200, body)) == {"data": []}
    assert await FlairApiClient._response(FakeResponse(201, body)) == {"data": []}
    assert await FlairApiClient._response(FakeResponse(204)) is None


async def test_success_non_json_raises() -> None:
    """A 200 without a JSON body is an error."""

    with pytest.raises(FlairError):
        await FlairApiClient._response(FakeResponse(200, "<html></html>"))


def _resource(rid: str, **attributes) -> dict:
    return {"id": rid, "attributes": {"name": rid, **attributes}, "relationships": {}}


async def test_structures_do_not_share_devices() -> None:
    """Each structure gets its own device dictionaries (H2)."""

    client = FlairApiClient("id", "secret", session=object())
    structures = {
        "A": _resource("A", **{"setup-complete": True}),
        "B": _resource("B", **{"setup-complete": True}),
    }

    async def relations(structure):
        sid = structure.id
        return [
            [_resource(f"room_{sid}")],
            [_resource(f"puck_{sid}", inactive=False)],
            [_resource(f"vent_{sid}", inactive=True)],
            [],
            [_resource(f"hvac_{sid}")],
            None,
            [],
            [_resource(f"bridge_{sid}", inactive=True)],
        ]

    with (
        patch.object(
            client, "_get",
            AsyncMock(side_effect=[{"data": []}, {"data": list(structures.values())}]),
        ),
        patch.object(client, "fetch_all_structure_relations", side_effect=relations),
        patch.object(
            client, "get_related", AsyncMock(return_value={"attributes": {"humidity": 40}})
        ),
    ):
        data = await client.get_flair_data()

    a, b = data.structures["A"], data.structures["B"]
    assert a.rooms is not b.rooms
    assert list(a.rooms) == ["room_A"]
    assert list(b.rooms) == ["room_B"]
    assert list(a.hvac_units) == ["hvac_A"]
    assert list(b.hvac_units) == ["hvac_B"]
    assert list(a.pucks) == ["puck_A"]
    assert a.pucks["puck_A"].current_reading == {"humidity": 40}
    assert b.vents["vent_B"].current_reading == {}
    assert a.zones == {}
