"""Deployment ticket template."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from create_release_ticket.config import get_app_config


def _build_jira_inline_cards(jira_ids: list[str]) -> list[dict[str, Any]]:
    """Build inline card nodes for Jira IDs."""
    nodes: list[dict[str, Any]] = []

    for jira_id in jira_ids:
        nodes.append({"type": "hardBreak"})
        nodes.append(
            {
                "type": "inlineCard",
                "attrs": {
                    "url": f"https://netskope.atlassian.net/browse/{jira_id}",
                },
            }
        )
        nodes.append({"type": "text", "text": " "})

    return nodes


def build_deployment_ticket_payload(
    build_version: str,
    rollback_version: str,
    current_branch: str,
    previous_branch: str,
    promote_ticket_key: str,
    devint_job_url: str,
    jira_ids: list[str],
    deploy_date: datetime | None = None,
) -> dict[str, Any]:
    """
    Build the payload for creating a deployment ticket.

    Args:
        build_version: Current build version (e.g., queryservice-release-2025.12.2.0.18496)
        rollback_version: Rollback version (e.g., queryservice-release-2025.12.1.0.18438)
        current_branch: Current branch (e.g., queryservice-release-2025.12.2)
        previous_branch: Previous branch (e.g., queryservice-release-2025.12.1)
        promote_ticket_key: Promote ticket key (e.g., ENG-826497)
        devint_job_url: Jenkins devint job URL
        jira_ids: List of Jira IDs from commits
        deploy_date: Deploy date (defaults to today)

    Returns:
        Jira issue creation payload
    """
    config = get_app_config()
    jira_config = config.jira

    if deploy_date is None:
        deploy_date = datetime.now()

    # Format dates
    date_str = deploy_date.strftime("%m/%d/%Y")

    def parse_tz_offset(value: str) -> datetime.tzinfo:
        v = value.strip()
        if v.upper() == "Z":
            return datetime.UTC

        # Accept "+08:00", "+0800", "-07:00", "-0700"
        if len(v) == 5 and (v[0] in "+-") and v[1:].isdigit():
            sign = 1 if v[0] == "+" else -1
            hours = int(v[1:3])
            minutes = int(v[3:5])
        elif (
            len(v) == 6 and (v[0] in "+-") and v[1:3].isdigit() and v[3] == ":" and v[4:6].isdigit()
        ):
            sign = 1 if v[0] == "+" else -1
            hours = int(v[1:3])
            minutes = int(v[4:6])
        else:
            raise ValueError(f"Unsupported timezone offset format: {value}")

        from datetime import timezone

        return timezone(sign * timedelta(hours=hours, minutes=minutes))

    tzinfo = parse_tz_offset(config.timezone)

    def jira_datetime(dt: datetime) -> str:
        # Jira Cloud datetime custom fields accept: yyyy-MM-dd'T'HH:mm:ss.SSSZ
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000%z")

    def on_date(base: datetime, hour: int, minute: int) -> datetime:
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=tzinfo)

    def window(
        base: datetime, start_hm: tuple[int, int], end_hm: tuple[int, int]
    ) -> tuple[str, str]:
        start = on_date(base, *start_hm)
        end = on_date(base, *end_hm)
        if end <= start:
            end = end + timedelta(days=1)
        return jira_datetime(start), jira_datetime(end)

    apac_start, apac_end = window(deploy_date, (22, 0), (2, 30))
    aus_start, aus_end = window(deploy_date, (22, 0), (3, 0))
    eu_start, eu_end = window(deploy_date, (22, 0), (3, 0))
    us_east_start, us_east_end = window(deploy_date, (5, 0), (7, 0))
    us_west_start, us_west_end = window(deploy_date, (5, 0), (7, 0))

    # Build summary
    summary = f"<QueryService><{date_str}><{build_version}>"

    # Build description content
    compare_url = (
        f"https://github.com/netSkope/query-engine/compare/{previous_branch}...{current_branch}"
    )
    promote_ticket_url = f"https://netskope.atlassian.net/browse/{promote_ticket_key}/"

    # Build the Key JIRAs paragraph with dynamic inline cards
    key_jiras_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": "Key JIRAs part of the deployment",
            "marks": [{"type": "strong"}],
        },
        {"type": "text", "text": ":"},
    ]
    key_jiras_content.extend(_build_jira_inline_cards(jira_ids))

    description_content: list[dict[str, Any]] = [
        # Description heading
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Description"}],
        },
        # Version to be deployed
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Version to be deployed", "marks": [{"type": "strong"}]},
            ],
        },
        {
            "type": "codeBlock",
            "attrs": {},
            "content": [{"type": "text", "text": build_version}],
        },
        # MPs
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "MPs", "marks": [{"type": "strong"}]}],
        },
        {
            "type": "codeBlock",
            "attrs": {},
            "content": [
                {
                    "type": "text",
                    "text": "SV5\nSJC1 (C4)\nAM2 (C4)\nFR4 (C4)\n\nZUR2\nRUH1\nSJC2\nFRA2\n\nSIN2\nLON3\nDFW3",
                }
            ],
        },
        # Rollback Version
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Rollback Version:", "marks": [{"type": "strong"}]},
            ],
        },
        {
            "type": "codeBlock",
            "attrs": {},
            "content": [{"type": "text", "text": rollback_version}],
        },
        # Key JIRAs (with dynamic inline cards)
        {
            "type": "paragraph",
            "content": key_jiras_content,
        },
        # Commit List
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Commit List:", "marks": [{"type": "strong"}]},
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": compare_url,
                    "marks": [{"type": "link", "attrs": {"href": compare_url}}],
                },
            ],
        },
        # Build Promotion
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Build Promotion:", "marks": [{"type": "strong"}]},
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Promotion Ticket",
                    "marks": [{"type": "link", "attrs": {"href": promote_ticket_url}}],
                },
            ],
        },
        # PDV_CONFIG_IMAGE_TAG
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "PDV_CONFIG_IMAGE_TAG", "marks": [{"type": "strong"}]},
                {"type": "hardBreak"},
                {
                    "type": "text",
                    "text": config.jenkins.pdv_config_image_tag,
                    "marks": [{"type": "code"}],
                },
            ],
        },
        # Slack Channels
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Slack Channels", "marks": [{"type": "strong"}]},
            ],
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": config.jenkins.slack_channel}],
        },
        # Deployment Order
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Deployment Order", "marks": [{"type": "strong"}]},
            ],
        },
        {"type": "paragraph", "content": [{"type": "text", "text": " "}]},
        # Deployment Order Table
        _build_deployment_order_table(),
        # Feature Flags
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Feature Flags:"}],
        },
        {"type": "paragraph", "content": [{"type": "text", "text": " "}]},
        # Devint Deployment
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Devint Deployment:"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": devint_job_url,
                    "marks": [{"type": "link", "attrs": {"href": devint_job_url}}],
                },
            ],
        },
        # GOV wiki update
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Update "},
                {
                    "type": "inlineCard",
                    "attrs": {
                        "url": "https://netskope.atlassian.net/wiki/spaces/ENG/pages/3824189863/GOV+environment+builds"
                    },
                },
                {
                    "type": "text",
                    "text": " with build version after deployment is complete in Prod:",
                },
            ],
        },
        # Deployment document
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Deployment document: "},
                {
                    "type": "inlineCard",
                    "attrs": {
                        "url": "https://netskope.atlassian.net/wiki/spaces/ENG/pages/3713827182/QueryService+SelfService+Deployment"
                    },
                },
            ],
        },
    ]

    payload: dict[str, Any] = {
        "fields": {
            "project": {"id": jira_config.project_id},
            "issuetype": {"id": jira_config.deployment_issue_type_id},
            "summary": summary,
            "customfield_17018": {"id": "22978", "value": "Scheduled deployment"},
            "customfield_20800": {"id": "5af0076491bc312e6a4ad8cf"},
            "customfield_23296": {"id": "26378", "value": "No"},
            "customfield_17280": [
                {"id": "14936", "value": "AM2"},
                {"id": "17009", "value": "DFW3"},
                {"id": "14938", "value": "FR4"},
                {"id": "16892", "value": "FRA2"},
                {"id": "18185", "value": "LON3"},
                {"id": "14941", "value": "MEL2"},
                {"id": "17008", "value": "RUH1"},
                {"id": "17007", "value": "SIN2"},
                {"id": "14966", "value": "SJC1"},
                {"id": "16627", "value": "SJC2"},
                {"id": "14943", "value": "SV5"},
                {"id": "16824", "value": "ZUR2"},
            ],
            # Planned deployment windows (Jira datetime custom fields)
            "customfield_20806": apac_start,
            "customfield_20807": apac_end,
            "customfield_21276": aus_start,
            "customfield_21277": aus_end,
            "customfield_20808": eu_start,
            "customfield_20809": eu_end,
            "customfield_20810": us_east_start,
            "customfield_20811": us_east_end,
            "customfield_20812": us_west_start,
            "customfield_20813": us_west_end,
            "description": {
                "version": 1,
                "type": "doc",
                "content": description_content,
            },
            "components": [
                {"id": jira_config.component_id, "name": jira_config.component_name},
            ],
            "reporter": {"id": jira_config.user_id},
            "customfield_20803": [
                {
                    "id": "22961",
                    "value": "No downtime / No inline impact / No customer action required",
                },
            ],
            "customfield_20823": build_version,
            "customfield_15000": [],
            "customfield_23871": [],
        },
        "update": {
            "issuelinks": [
                {
                    "add": {
                        "type": {"id": "10003"},
                        "inwardIssue": {"key": promote_ticket_key},
                    }
                }
            ],
        },
        "watchers": [jira_config.user_id],
    }

    return payload


def _build_deployment_order_table() -> dict[str, Any]:
    """Build the deployment order table."""
    return {
        "type": "table",
        "attrs": {
            "isNumberColumnEnabled": False,
            "layout": "default",
            "localId": "deployment-order-table",
            "width": 1203,
        },
        "content": [
            # Header row
            {
                "type": "tableRow",
                "content": [
                    _table_header("Region"),
                    _table_header("POP"),
                    _table_header("Cluster"),
                    _table_header("Deployment Window"),
                    _table_header("PDV"),
                ],
            },
            # Data rows
            _table_row(
                [
                    "APAC + Europe (Day1)",
                    "SIN2",
                    "c1",
                    "Between 6AM AND 10AM PST",
                    "OnCall/SRE runs the deployment. PDV runs as part of the deployment.",
                ]
            ),
            _table_row(
                [
                    "APAC + Europe (Day1)",
                    "FR4",
                    "c4",
                    "Between 12 Noon and 7 PM PST",
                    "When PDV fails, rerun the PDV with PDV-only option.",
                ]
            ),
            _table_row(
                ["Australia + US + EU (Day2)", "MEL2", "c1", "Between 6AM AND 10AM PST", ""]
            ),
            _table_row(["Australia + US + EU (Day2)", "SJC1", "c4", "After 8PM PST", ""]),
            _table_row(["Australia + US + EU (Day2)", "SJC2", "c1", "After 8PM PST", ""]),
            _table_row(["Australia + US + EU (Day2)", "DFW3", "c1", "After 8PM PST", ""]),
            _table_row(
                ["Australia + US + EU (Day2)", "RUH1", "c1", "Between 12 Noon and 5 PM PST", ""]
            ),
            _table_row(
                ["Australia + US + EU (Day2)", "FRA2", "c1", "Between 12 Noon and 5 PM PST", ""]
            ),
            _table_row(
                ["Australia + US + EU (Day2)", "LON3", "c1", "Between 12 Noon and 5 PM PST", ""]
            ),
            _table_row(
                ["Australia + US + EU (Day2)", "ZUR2", "c1", "Between 12 Noon and 5 PM PST", ""]
            ),
            _table_row(
                [
                    "END of Day 3",
                    "Update GOV wiki",
                    "",
                    "AFTER all prod deployments are completed.",
                    "",
                ]
            ),
        ],
    }


def _table_header(text: str) -> dict[str, Any]:
    """Build a table header cell."""
    return {
        "type": "tableHeader",
        "attrs": {"background": "var(--ds-background-accent-gray-subtlest, #F4F5F7)"},
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": text, "marks": [{"type": "strong"}]},
                ],
            }
        ],
    }


def _table_row(cells: list[str]) -> dict[str, Any]:
    """Build a table row."""
    return {
        "type": "tableRow",
        "content": [_table_cell(cell) for cell in cells],
    }


def _table_cell(text: str) -> dict[str, Any]:
    """Build a table cell."""
    content: list[dict[str, Any]] = []
    if text:
        content = [{"type": "text", "text": text}]

    return {
        "type": "tableCell",
        "attrs": {},
        "content": [{"type": "paragraph", "content": content}],
    }
