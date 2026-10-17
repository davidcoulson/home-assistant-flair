"""Tests for the Flair config and options flows."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flair.const import CONF_SCAN_INTERVAL, CONF_TIMEOUT, DOMAIN

VALIDATE = "custom_components.flair.config_flow.async_validate_api"


def _entry(client_id: str, version=2.1) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=version,
        unique_id=client_id,
        data={CONF_CLIENT_ID: client_id, CONF_CLIENT_SECRET: "secret"},
    )


async def test_options_flow(hass: HomeAssistant) -> None:
    """The options flow opens and saves on current HA (M1)."""

    entry = _entry("a")
    entry.add_to_hass(hass)

    with patch("custom_components.flair.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 60, CONF_TIMEOUT: 30}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 60, CONF_TIMEOUT: 30}


async def test_reauth_migrates_version_1_entry(hass: HomeAssistant) -> None:
    """Reauth of an OAuth1 entry updates credentials and version (M2)."""

    entry = _entry("old", version=1)
    entry.add_to_hass(hass)

    with (
        patch(VALIDATE, return_value=True),
        patch("custom_components.flair.async_setup_entry", return_value=True),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CLIENT_ID: "new", CONF_CLIENT_SECRET: "s2"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.version == 2.1
    assert entry.unique_id == "new"
    assert entry.data == {CONF_CLIENT_ID: "new", CONF_CLIENT_SECRET: "s2"}


async def test_reauth_rejects_other_entrys_credentials(hass: HomeAssistant) -> None:
    """Reauth cannot repoint an entry at another entry's account (M13)."""

    entry_a = _entry("a")
    entry_a.add_to_hass(hass)
    _entry("b").add_to_hass(hass)

    with (
        patch(VALIDATE, return_value=True),
        patch("custom_components.flair.async_setup_entry", return_value=True),
    ):
        result = await entry_a.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CLIENT_ID: "b", CONF_CLIENT_SECRET: "x"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry_a.unique_id == "a"
    assert entry_a.data[CONF_CLIENT_ID] == "a"


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """The initial flow still creates an entry."""

    with (
        patch(VALIDATE, return_value=True),
        patch("custom_components.flair.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CLIENT_ID: "a", CONF_CLIENT_SECRET: "s"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "a"
