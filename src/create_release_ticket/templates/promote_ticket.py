"""Promote ticket template."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from create_release_ticket.config import get_app_config


def build_promote_ticket_payload(
    build_version: str,
    deploy_date: datetime | None = None,
) -> dict[str, Any]:
    """
    Build the payload for creating a promote ticket.

    Args:
        build_version: Build version (e.g., queryservice-release-2025.12.2.0.18496)
        deploy_date: Deploy date (defaults to today)

    Returns:
        Jira issue creation payload
    """
    config = get_app_config()
    jira_config = config.jira

    if deploy_date is None:
        deploy_date = datetime.now()

    # Format date for summary
    date_str = deploy_date.strftime("%Y-%m-%d")
    timezone = config.timezone

    summary = f"Queryservice: {date_str} {timezone} Promote commercial build"

    payload: dict[str, Any] = {
        "fields": {
            "project": {
                "id": jira_config.project_id,
            },
            "issuetype": {
                "id": jira_config.promote_issue_type_id,
            },
            "summary": summary,
            "description": {
                "version": 1,
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Promoting commercial build: {build_version}",
                                "marks": [{"type": "code"}],
                            }
                        ],
                    }
                ],
            },
            "priority": {
                "id": "3",
                "name": "Major",
                "iconUrl": "https://netskope.atlassian.net/images/icons/priorities/major.svg",
            },
            "components": [
                {
                    "id": jira_config.component_id,
                    "name": jira_config.component_name,
                }
            ],
            "customfield_15000": [],
            "assignee": {"id": jira_config.user_id},
            "reporter": {"id": jira_config.user_id},
            "customfield_10004": 0,
            "customfield_16812": [],
            # Sub-Component is required at resolve time; default to NA.
            "customfield_15000": [{"id": "21484"}],
            # These fields are required to resolve as Fixed in ENG workflow.
            "customfield_12502": {"id": "10503"},
            "customfield_12503": "NA",
            "customfield_16630": ["NA"],
            "customfield_16629": [build_version],
            "fixVersions": [],
            # Allows Fix Version to be empty/NA in some workflows.
            "labels": ["no-code"],
            "customfield_16747": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "1. What functionality is impacted?\r\n\r\n"
                                    "2. Who is impacted (customers and/or services)? \r\n\r\n"
                                    "3. When and how was this bug introduced?\r\n\r\n"
                                    "4. Why was this bug not found earlier in the release? \r\n\r\n"
                                    "5. Is there a workaround available?\r\n\r\n"
                                    "6. How critical is this change? Describe the exact impact to customers without this change. \r\n\r\n"
                                    "7. Is this a safe change? What's the likelihood of this change causing regression or IMF in this component and other dependency components (low/medium/high)?\r\n\r\n"
                                    "8. Is this impacting any other service and/or dependent service? If yes, list all the components suggested for regression testing, including this direct component and other related components.\r\n\r\n"
                                    "9. Is the change merged and tested in the develop branch for both functionality and regression?\r\n\r\n"
                                    "10. List the full name of all QE owners that certified this change."
                                ),
                            }
                        ],
                    }
                ],
            },
            "customfield_16746": {
                "id": "13094",
                "value": "NA",
            },
            "customfield_16180": [],
            "customfield_16176": [],
            "customfield_16177": [],
            "customfield_13000": [],
        },
        "update": {},
        "transition": {
            "id": "791",
        },
        "watchers": [jira_config.user_id],
    }

    return payload
