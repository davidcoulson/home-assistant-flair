"""Tests for Flair diagnostics redaction (L1)."""
from __future__ import annotations

import json

from homeassistant.core import HomeAssistant

from custom_components.flair.const import DOMAIN
from custom_components.flair.diagnostics import async_get_config_entry_diagnostics
from custom_components.flair.model import Puck2

from .common import make_coordinator, make_data, make_entry, make_structure

SENTINEL = "SENTINEL-123 Main St"


async def test_diagnostics_redact_personal_data(hass: HomeAssistant) -> None:
    """Names and location never appear in diagnostics."""

    structure = make_structure(name=SENTINEL, location=SENTINEL, latitude=SENTINEL)
    structure.puck2s = {
        "p1": Puck2(
            id="p1",
            attributes={"name": SENTINEL, "inactive": False},
            relationships={},
            current_reading={"connected-gateway-name": SENTINEL, "humidity": 40},
        )
    }
    entry = make_entry("client-sentinel")
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: make_coordinator(make_data(structure))}

    result = await async_get_config_entry_diagnostics(hass, entry)

    dumped = json.dumps(result, default=str)
    assert SENTINEL not in dumped
    assert "client-sentinel" not in dumped
    assert result["structures"]["s1"]["puck2s"]["p1"]["current_reading"]["humidity"] == 40
