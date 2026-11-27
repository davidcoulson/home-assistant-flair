"""flair.reload_code clears Marketplace's restart repair."""

import json
from pathlib import Path

from homeassistant.helpers import issue_registry as ir

from custom_components import flair


async def test_reload_clears_only_marketplaces_running_version_repairs(hass, monkeypatch):
    mod = flair
    monkeypatch.setattr(mod, "_CODE_VERSION", "1.2.3")
    for domain, issue_id, issue_domain in (
        ("marketplace", "restart_required_1_tags/1.2.3", "flair"),
        ("marketplace", "restart_required_2_tags/v1.2.3", "flair"),
        ("marketplace", "restart_required_3_tags/1.2.4", "flair"),
        ("marketplace", "restart_required_4_tags/1.2.3", "ssh"),
        ("marketplace", "critical_x/1.2.3", "flair"),
        ("flair", "restart_required_x/1.2.3", "flair"),
    ):
        ir.async_create_issue(
            hass, domain, issue_id, is_fixable=False, issue_domain=issue_domain,
            severity=ir.IssueSeverity.WARNING, translation_key="x",
        )
    mod._clear_marketplace_restart(hass)
    assert set(ir.async_get(hass).issues) == {
        ("marketplace", "restart_required_3_tags/1.2.4"),
        ("marketplace", "restart_required_4_tags/1.2.3"),
        ("marketplace", "critical_x/1.2.3"),
        ("flair", "restart_required_x/1.2.3"),
    }


def test_code_version_is_the_manifest_version():
    mod = flair
    manifest = json.loads((Path(mod.__file__).parent / "manifest.json").read_text())
    assert mod._CODE_VERSION == manifest["version"]
