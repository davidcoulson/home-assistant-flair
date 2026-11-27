"""flair.reload_code clears Marketplace's restart repair."""

from homeassistant.helpers import issue_registry as ir

from custom_components import flair


async def test_reload_clears_only_marketplaces_flair_restart_repairs(hass):
    for domain, issue_id, issue_domain in (
        ("marketplace", "restart_required_1_tags/2026.11.27.2", "flair"),
        ("marketplace", "restart_required_2_tags/2026.11.26.01", "ssh"),
        ("marketplace", "critical_x", "flair"),
        ("flair", "restart_required_x", "flair"),
    ):
        ir.async_create_issue(
            hass, domain, issue_id, is_fixable=False, issue_domain=issue_domain,
            severity=ir.IssueSeverity.WARNING, translation_key="x",
        )
    flair._clear_marketplace_restart(hass)
    assert set(ir.async_get(hass).issues) == {
        ("marketplace", "restart_required_2_tags/2026.11.26.01"),
        ("marketplace", "critical_x"),
        ("flair", "restart_required_x"),
    }
