"""Fixtures for Flair tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.flair.util import FlairApiClient


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the custom integration in every test."""
    yield


@pytest.fixture(autouse=True)
def no_flair_network():
    """Make sure no test can reach the Flair cloud."""

    async def _blocked(*args, **kwargs):
        raise RuntimeError("Flair network access is disabled in tests")

    with (
        patch.object(FlairApiClient, "check_token", _blocked),
        patch.object(FlairApiClient, "_get", _blocked),
        patch.object(FlairApiClient, "_post", _blocked),
        patch.object(FlairApiClient, "_patch", _blocked),
        patch.object(FlairApiClient, "_delete", _blocked),
    ):
        yield
