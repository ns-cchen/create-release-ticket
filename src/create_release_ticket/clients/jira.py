"""Jira API client."""

from __future__ import annotations

import base64
from typing import Any

from rich.console import Console

from create_release_ticket.clients.base import BaseClient
from create_release_ticket.config import get_app_config, get_settings

console = Console()


def _adf_text(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]},
        ],
    }


class JiraClient(BaseClient):
    """Client for Jira REST API."""

    def __init__(self):
        settings = get_settings()
        config = get_app_config()

        # Create Basic Auth header
        credentials = f"{settings.jira_email}:{settings.jira_api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()

        super().__init__(
            base_url=config.jira.base_url,
            headers={
                "Authorization": f"Basic {encoded}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self.jira_config = config.jira

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Create a Jira issue.

        Args:
            payload: Issue creation payload

        Returns:
            Dict with 'id', 'key', and 'self' URL

        Raises:
            Exception if creation fails
        """
        response = self.post(
            "/rest/api/3/issue",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code not in (200, 201):
            error_detail = response.text
            try:
                error_json = response.json()
                if "errors" in error_json:
                    error_detail = str(error_json["errors"])
                elif "errorMessages" in error_json:
                    error_detail = str(error_json["errorMessages"])
            except Exception:
                pass
            raise Exception(f"Failed to create Jira issue: {response.status_code} - {error_detail}")

        result = response.json()
        console.print(f"[green]✓ Created Jira issue: {result['key']}[/green]")
        return result

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        """
        Get issue details.

        Args:
            issue_key: Issue key (e.g., ENG-123456)

        Returns:
            Issue details
        """
        response = self.get(f"/rest/api/3/issue/{issue_key}")

        if response.status_code != 200:
            raise Exception(f"Failed to get issue {issue_key}: {response.status_code}")

        return response.json()

    def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        """
        Get available transitions for an issue.

        Args:
            issue_key: Issue key (e.g., ENG-123456)

        Returns:
            List of available transitions
        """
        response = self.get(f"/rest/api/3/issue/{issue_key}/transitions")

        if response.status_code != 200:
            raise Exception(f"Failed to get transitions for {issue_key}: {response.status_code}")

        return response.json().get("transitions", [])

    def transition_issue(
        self,
        issue_key: str,
        transition_id: str | None = None,
        transition_name: str = "Done",
        resolution: str = "Done",
        fields: dict[str, Any] | None = None,
    ) -> bool:
        """
        Transition an issue to a new status.

        Args:
            issue_key: Issue key (e.g., ENG-123456)
            transition_id: Specific transition ID to use
            transition_name: Transition name to search for if ID not provided
            resolution: Resolution to set (e.g., "Done")

        Returns:
            True if successful
        """
        # If no transition_id provided, find it by name
        if transition_id is None:
            transitions = self.get_transitions(issue_key)
            for t in transitions:
                if t["name"].lower() == transition_name.lower():
                    transition_id = t["id"]
                    break

            if transition_id is None:
                available = [t["name"] for t in transitions]
                raise Exception(
                    f"Transition '{transition_name}' not found for {issue_key}. "
                    f"Available: {available}"
                )

        payload: dict[str, Any] = {"transition": {"id": transition_id}}

        merged_fields: dict[str, Any] = {}
        if fields:
            merged_fields.update(fields)
        if resolution:
            merged_fields["resolution"] = {"name": resolution}
        if merged_fields:
            payload["fields"] = merged_fields

        response = self.post(
            f"/rest/api/3/issue/{issue_key}/transitions",
            json=payload,
        )

        if response.status_code not in (200, 204):
            raise Exception(
                f"Failed to transition {issue_key}: {response.status_code} - {response.text}"
            )

        console.print(f"[green]✓ Transitioned {issue_key} to {transition_name}[/green]")
        return True

    def update_issue_fields(self, issue_key: str, fields: dict[str, Any]) -> bool:
        """Update Jira issue fields.

        Uses Jira Cloud edit issue API.
        """
        response = self.put(
            f"/rest/api/3/issue/{issue_key}",
            json={"fields": fields},
        )

        if response.status_code not in (200, 204):
            raise Exception(
                f"Failed to update {issue_key}: {response.status_code} - {response.text}"
            )

        return True

    def prepare_resolve_fixed(
        self,
        issue_key: str,
        *,
        fix_version_label: str | None,
        sub_component_label: str | None = None,
        add_no_code_label: bool = True,
    ) -> dict[str, Any]:
        """Build fields payload required to resolve as Fixed.

        The ENG Jira workflow enforces additional required fields on Resolve Issue.
        Some of these fields are only available on the transition screen, not the
        normal edit screen, so callers should pass the returned fields into
        transition_issue(..., fields=...).
        """
        issue = self.get_issue(issue_key)
        current_fields = issue.get("fields") or {}
        labels: list[str] = list(current_fields.get("labels") or [])

        # Add a label that relaxes FixVersion requirements in some workflows.
        # Only do this if explicitly requested or if we don't have a real fix version.
        should_add_no_code = add_no_code_label or not fix_version_label
        if should_add_no_code:
            if "no-code" not in labels and "no_code" not in labels:
                labels.append("no-code")

        # Defaults derived from org workflow constraints.
        # - Sub-Component (customfield_15000) requires selecting NA option when not applicable.
        # - Fix Dev Tested (customfield_12502) is a Yes/No radio button.
        # - Fix QA Test Recommendations (customfield_12503) is a textarea.
        fields_to_set: dict[str, Any] = {
            "labels": labels,
            "customfield_15000": [{"id": "21484"}],  # NA
            "customfield_12502": {"id": "10503"},  # Yes
            "customfield_12503": _adf_text("NA"),
        }

        # Also try to set the system Fix Versions field (project version picker).
        # If the version doesn't exist in Jira, Jira will reject it; let that surface.
        if fix_version_label:
            fields_to_set["fixVersions"] = [{"name": fix_version_label}]

        return fields_to_set

    def delete_issue(self, issue_key: str) -> bool:
        """
        Delete an issue.

        Args:
            issue_key: Issue key (e.g., ENG-123456)

        Returns:
            True if successful
        """
        response = self.delete(f"/rest/api/3/issue/{issue_key}")

        if response.status_code not in (200, 204):
            raise Exception(
                f"Failed to delete {issue_key}: {response.status_code} - {response.text}"
            )

        console.print(f"[green]✓ Deleted issue {issue_key}[/green]")
        return True

    def add_comment(self, issue_key: str, comment: str) -> bool:
        """
        Add a comment to an issue.

        Args:
            issue_key: Issue key (e.g., ENG-123456)
            comment: Comment text

        Returns:
            True if successful
        """
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}],
                    }
                ],
            }
        }

        response = self.post(f"/rest/api/3/issue/{issue_key}/comment", json=payload)

        if response.status_code not in (200, 201):
            raise Exception(
                f"Failed to add comment to {issue_key}: {response.status_code} - {response.text}"
            )

        return True

    def create_issue_link(
        self,
        *,
        inward_issue_key: str,
        outward_issue_key: str,
        link_type: str = "Relates",
    ) -> bool:
        """Create an issue link between two issues.

        For "Relates", direction typically doesn't matter in Jira UI.
        """
        payload: dict[str, Any] = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_issue_key},
            "outwardIssue": {"key": outward_issue_key},
        }

        response = self.post("/rest/api/3/issueLink", json=payload)
        if response.status_code not in (200, 201, 204):
            raise Exception(
                f"Failed to create issue link ({link_type}) {inward_issue_key} <-> {outward_issue_key}: "
                f"{response.status_code} - {response.text}"
            )

        console.print(f"[green]✓ Linked {outward_issue_key} relates to {inward_issue_key}[/green]")
        return True

        return True

    def validate_credentials(self) -> bool:
        """
        Validate Jira credentials by making a simple API call.

        Returns:
            True if credentials are valid
        """
        try:
            response = self.get("/rest/api/3/myself")
            if response.status_code == 200:
                user = response.json()
                console.print(
                    f"[green]✓ Jira: Authenticated as {user.get('displayName', 'Unknown')}[/green]"
                )
                return True
            return False
        except Exception as e:
            console.print(f"[red]✗ Jira authentication failed: {e}[/red]")
            return False
