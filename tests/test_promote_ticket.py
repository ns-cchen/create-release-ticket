"""Tests for promote ticket template."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _patch_app_config(monkeypatch):
    """Patch get_app_config for promote ticket template tests."""
    import create_release_ticket.templates.promote_ticket as promote_module

    monkeypatch.setattr(
        promote_module,
        "get_app_config",
        lambda: SimpleNamespace(
            jira=SimpleNamespace(
                base_url="https://jira.example.com",
                project_id="10011",
                promote_issue_type_id="7",
                component_id="13002",
                component_name="Query Service (QS)",
                user_id="712020:test-user-id",
            ),
            timezone="+08:00",
        ),
    )


def test_promote_ticket_payload_excludes_resolve_only_fields(monkeypatch):
    """
    BUG FIX: customfield_16629 and customfield_16630 cannot be set at issue
    creation time - they are only available on the resolve/transition screen.

    This test verifies that these fields are NOT included in the create payload.
    """
    _patch_app_config(monkeypatch)

    from create_release_ticket.templates.promote_ticket import build_promote_ticket_payload

    payload = build_promote_ticket_payload(
        build_version="queryservice-release-2026.1.5.0.18914"
    )

    fields = payload["fields"]

    # These fields should NOT be in the create payload - they're resolve-only
    assert "customfield_16629" not in fields, (
        "customfield_16629 should not be in create payload - it's only available on resolve screen"
    )
    assert "customfield_16630" not in fields, (
        "customfield_16630 should not be in create payload - it's only available on resolve screen"
    )


def test_promote_ticket_payload_has_required_fields(monkeypatch):
    """Verify that required fields are still present in the payload."""
    _patch_app_config(monkeypatch)

    from create_release_ticket.templates.promote_ticket import build_promote_ticket_payload

    payload = build_promote_ticket_payload(
        build_version="queryservice-release-2026.1.5.0.18914"
    )

    fields = payload["fields"]

    # Required fields should still be present
    assert "project" in fields
    assert "issuetype" in fields
    assert "summary" in fields
    assert "description" in fields
    assert "components" in fields
    assert "labels" in fields
