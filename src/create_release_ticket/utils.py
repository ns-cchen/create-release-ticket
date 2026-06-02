"""Utility functions for parsing and extracting data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rich.console import Console

console = Console()


def derive_fix_version_label(build_version: str) -> str | None:
    """Derive ENG FixVersion label from a QueryService build version.

    ENG workflow expects something like: YYYYMM.W
    Example: queryservice-release-2026.1.4.0.18836 -> 202601.4

    Returns None if build_version cannot be parsed.
    """
    try:
        parsed = parse_build_version(build_version)
    except Exception:
        return None

    return f"{parsed.year}{parsed.month:02d}.{parsed.week}"


@dataclass
class ParsedVersion:
    """Parsed build version info."""

    full_version: str  # queryservice-release-2025.12.2.0.18496
    current_branch: str  # queryservice-release-2025.12.2
    previous_branch: str  # queryservice-release-2025.12.1 or 2025.11.4
    year: int
    month: int
    week: int
    patch: int
    drone_number: int


def parse_build_version(version: str) -> ParsedVersion:
    """
    Parse build version string.

    Format: queryservice-release-YYYY.MM.W.P.DRONE
    - YYYY: Year
    - MM: Month
    - W: Week of the month (1-4)
    - P: Patch/flow number
    - DRONE: Drone build number

    Args:
        version: Build version string (e.g., queryservice-release-2025.12.2.0.18496)

    Returns:
        ParsedVersion with extracted info

    Raises:
        ValueError if version format is invalid
    """
    # Pattern: queryservice-release-YYYY.MM.W.P.DRONE
    pattern = r"^(queryservice-release)-(\d{4})\.(\d{1,2})\.(\d{1})\.(\d+)\.(\d+)$"
    match = re.match(pattern, version)

    if not match:
        raise ValueError(
            f"Invalid version format: {version}\n"
            f"Expected format: queryservice-release-YYYY.MM.W.P.DRONE\n"
            f"Example: queryservice-release-2025.12.2.0.18496"
        )

    prefix = match.group(1)
    year = int(match.group(2))
    month = int(match.group(3))
    week = int(match.group(4))
    patch = int(match.group(5))
    drone = int(match.group(6))

    # Current branch: queryservice-release-YYYY.MM.W
    current_branch = f"{prefix}-{year}.{month}.{week}"

    # Previous branch: previous week
    prev_year, prev_month, prev_week = _get_previous_week(year, month, week)
    previous_branch = f"{prefix}-{prev_year}.{prev_month}.{prev_week}"

    return ParsedVersion(
        full_version=version,
        current_branch=current_branch,
        previous_branch=previous_branch,
        year=year,
        month=month,
        week=week,
        patch=patch,
        drone_number=drone,
    )


def _get_previous_week(year: int, month: int, week: int) -> tuple[int, int, int]:
    """
    Get the previous week's year, month, and week number.

    Args:
        year: Current year
        month: Current month (1-12)
        week: Current week of month (1-4)

    Returns:
        Tuple of (year, month, week) for previous week
    """
    if week > 1:
        # Same month, previous week
        return year, month, week - 1
    else:
        # Need to go to previous month
        if month > 1:
            prev_month = month - 1
            prev_year = year
        else:
            # January -> December of previous year
            prev_month = 12
            prev_year = year - 1

        # Assume 4 weeks per month for simplicity
        # In reality, some months might have 5 weeks
        prev_week = 4

        return prev_year, prev_month, prev_week


def extract_jira_ids(commits: list[dict[str, Any]]) -> list[str]:
    """
    Extract Jira IDs from commit messages.

    Looks for patterns like:
    - DINT-1234: some message
    - EP-1234: some message
    - ENG-1234: some message

    Args:
        commits: List of commit objects from GitHub API

    Returns:
        List of unique Jira IDs found
    """
    # Pattern: UPPERCASE-NUMBER at the start of commit message
    pattern = r"^([A-Z]+-\d+)"

    jira_ids: set[str] = set()

    for commit in commits:
        message = commit.get("commit", {}).get("message", "")
        # Only look at first line of commit message
        first_line = message.split("\n")[0]

        match = re.match(pattern, first_line)
        if match:
            jira_ids.add(match.group(1))

    # Sort for consistent output
    sorted_ids = sorted(jira_ids)

    if sorted_ids:
        console.print(f"[blue]Extracted {len(sorted_ids)} Jira IDs from commits[/blue]")
    else:
        console.print("[yellow]No Jira IDs found in commit messages[/yellow]")

    return sorted_ids


def format_jira_url(ticket_key: str) -> str:
    """Format a Jira ticket URL using the configured Jira base URL."""
    from create_release_ticket.config import get_app_config  # local import avoids circular
    base_url = get_app_config().jira.base_url
    return f"{base_url}/browse/{ticket_key}"


def format_github_compare_url(owner: str, repo: str, base: str, head: str) -> str:
    """Format a GitHub compare URL."""
    return f"https://github.com/{owner}/{repo}/compare/{base}...{head}"


def validate_version_format(version: str) -> bool:
    """
    Validate that a version string matches the expected format.

    Args:
        version: Version string to validate

    Returns:
        True if valid
    """
    pattern = r"^queryservice-release-\d{4}\.\d{1,2}\.\d{1}\.\d+\.\d+$"
    return bool(re.match(pattern, version))
