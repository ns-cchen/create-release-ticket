"""Tests for utility functions: version parsing, Jira ID extraction, formatting."""

from __future__ import annotations

import pytest

from create_release_ticket.utils import (
    _get_previous_week,
    derive_fix_version_label,
    extract_jira_ids,
    format_github_compare_url,
    format_jira_url,
    parse_build_version,
    validate_version_format,
)


# ── parse_build_version ──────────────────────────────────────────────────


class TestParseBuildVersion:
    def test_standard_version(self):
        v = parse_build_version("queryservice-release-2025.12.2.0.18496")
        assert v.year == 2025
        assert v.month == 12
        assert v.week == 2
        assert v.patch == 0
        assert v.drone_number == 18496
        assert v.current_branch == "queryservice-release-2025.12.2"
        assert v.previous_branch == "queryservice-release-2025.12.1"

    def test_january_week1_wraps_to_previous_december(self):
        v = parse_build_version("queryservice-release-2026.1.1.0.19000")
        assert v.current_branch == "queryservice-release-2026.1.1"
        assert v.previous_branch == "queryservice-release-2025.12.4"

    def test_month_boundary_march_week1_wraps_to_feb(self):
        v = parse_build_version("queryservice-release-2026.3.1.0.19100")
        assert v.previous_branch == "queryservice-release-2026.2.4"

    def test_mid_month(self):
        v = parse_build_version("queryservice-release-2026.6.3.0.20000")
        assert v.current_branch == "queryservice-release-2026.6.3"
        assert v.previous_branch == "queryservice-release-2026.6.2"

    def test_single_digit_month(self):
        v = parse_build_version("queryservice-release-2026.1.5.0.18914")
        assert v.month == 1
        assert v.week == 5

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid version format"):
            parse_build_version("invalid-version")

    def test_missing_drone_number_raises(self):
        with pytest.raises(ValueError):
            parse_build_version("queryservice-release-2026.1.1.0")

    def test_wrong_prefix_raises(self):
        with pytest.raises(ValueError):
            parse_build_version("other-release-2026.1.1.0.18914")

    def test_full_version_preserved(self):
        version = "queryservice-release-2026.1.5.0.18914"
        v = parse_build_version(version)
        assert v.full_version == version


# ── _get_previous_week ───────────────────────────────────────────────────


class TestGetPreviousWeek:
    def test_same_month_decrement(self):
        assert _get_previous_week(2026, 6, 3) == (2026, 6, 2)

    def test_first_week_wraps_to_prev_month(self):
        assert _get_previous_week(2026, 6, 1) == (2026, 5, 4)

    def test_jan_week1_wraps_to_dec(self):
        assert _get_previous_week(2026, 1, 1) == (2025, 12, 4)

    def test_week4_same_month(self):
        assert _get_previous_week(2026, 3, 4) == (2026, 3, 3)


# ── derive_fix_version_label ─────────────────────────────────────────────


class TestDeriveFixVersionLabel:
    def test_normal_version(self):
        assert derive_fix_version_label("queryservice-release-2026.1.4.0.18836") == "202601.4"

    def test_december(self):
        assert derive_fix_version_label("queryservice-release-2025.12.2.0.18496") == "202512.2"

    def test_invalid_version_returns_none(self):
        assert derive_fix_version_label("not-a-version") is None


# ── extract_jira_ids ─────────────────────────────────────────────────────


class TestExtractJiraIds:
    def _commit(self, msg: str) -> dict:
        return {"commit": {"message": msg}}

    def test_extracts_jira_ids_from_first_line(self):
        commits = [
            self._commit("ENG-123 Add feature"),
            self._commit("DINT-456 Fix bug"),
            self._commit("EP-789 Update config"),
        ]
        ids = extract_jira_ids(commits)
        assert ids == ["DINT-456", "ENG-123", "EP-789"]

    def test_deduplicates(self):
        commits = [
            self._commit("ENG-123 First change"),
            self._commit("ENG-123 Second change"),
        ]
        ids = extract_jira_ids(commits)
        assert ids == ["ENG-123"]

    def test_ignores_non_jira_messages(self):
        commits = [
            self._commit("Merge branch 'develop'"),
            self._commit("fixup! something"),
            self._commit("ENG-100 Real ticket"),
        ]
        ids = extract_jira_ids(commits)
        assert ids == ["ENG-100"]

    def test_empty_commits(self):
        assert extract_jira_ids([]) == []

    def test_no_jira_ids_found(self):
        commits = [self._commit("just a message")]
        assert extract_jira_ids(commits) == []

    def test_multiline_message_only_uses_first_line(self):
        commits = [self._commit("ENG-100 Main change\nENG-200 Should be ignored")]
        ids = extract_jira_ids(commits)
        assert ids == ["ENG-100"]

    def test_sorted_output(self):
        commits = [
            self._commit("ZETA-999 Last"),
            self._commit("ALPHA-001 First"),
            self._commit("MID-500 Middle"),
        ]
        ids = extract_jira_ids(commits)
        assert ids == ["ALPHA-001", "MID-500", "ZETA-999"]


# ── format helpers ───────────────────────────────────────────────────────


class TestFormatHelpers:
    def test_format_jira_url(self):
        assert format_jira_url("ENG-123") == "https://netskope.atlassian.net/browse/ENG-123"

    def test_format_github_compare_url(self):
        url = format_github_compare_url("owner", "repo", "base", "head")
        assert url == "https://github.com/owner/repo/compare/base...head"


# ── validate_version_format ──────────────────────────────────────────────


class TestValidateVersionFormat:
    def test_valid(self):
        assert validate_version_format("queryservice-release-2026.1.5.0.18914") is True

    def test_invalid(self):
        assert validate_version_format("random-string") is False

    def test_wrong_prefix(self):
        assert validate_version_format("other-release-2026.1.5.0.18914") is False
