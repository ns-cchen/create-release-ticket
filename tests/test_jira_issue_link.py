from __future__ import annotations

from types import SimpleNamespace

import pytest


class _DummyResponse:
    def __init__(self, status_code: int = 201, text: str = ""):
        self.status_code = status_code
        self.text = text


def _patch_jira_config(monkeypatch):
    # JiraClient imports get_settings/get_app_config directly into the module,
    # so patch the module symbols (not create_release_ticket.config.*).
    import create_release_ticket.clients.jira as jira_module

    monkeypatch.setattr(
        jira_module,
        "get_settings",
        lambda: SimpleNamespace(
            jira_email="test@example.com",
            jira_api_token="token",
            github_pat="ghp_x",
            jenkins_user="u",
            jenkins_api_token="t",
            jenkins_url="https://jenkins.example.com",
        ),
    )

    # Minimal app config shape used by JiraClient
    monkeypatch.setattr(
        jira_module,
        "get_app_config",
        lambda: SimpleNamespace(jira=SimpleNamespace(base_url="https://jira.example.com")),
    )


def test_create_issue_link_posts_expected_payload(monkeypatch):
    _patch_jira_config(monkeypatch)

    from create_release_ticket.clients.jira import JiraClient

    client = JiraClient()

    captured = {}

    def fake_post(endpoint: str, *, json=None, data=None, headers=None):
        captured["endpoint"] = endpoint
        captured["json"] = json
        return _DummyResponse(status_code=201)

    monkeypatch.setattr(client, "post", fake_post)

    client.create_issue_link(
        inward_issue_key="ENG-857076",
        outward_issue_key="ENG-999999",
        link_type="Relates",
    )

    assert captured["endpoint"] == "/rest/api/3/issueLink"
    assert captured["json"]["type"]["name"] == "Relates"
    assert captured["json"]["inwardIssue"]["key"] == "ENG-857076"
    assert captured["json"]["outwardIssue"]["key"] == "ENG-999999"


def test_create_issue_link_raises_on_failure(monkeypatch):
    _patch_jira_config(monkeypatch)

    from create_release_ticket.clients.jira import JiraClient

    client = JiraClient()

    def fake_post(endpoint: str, *, json=None, data=None, headers=None):
        return _DummyResponse(status_code=400, text="bad")

    monkeypatch.setattr(client, "post", fake_post)

    with pytest.raises(Exception) as exc:
        client.create_issue_link(
            inward_issue_key="ENG-857076",
            outward_issue_key="ENG-999999",
        )

    assert "Failed to create issue link" in str(exc.value)
