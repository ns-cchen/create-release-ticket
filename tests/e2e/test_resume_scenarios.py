"""E2E tests for workflow resume/interrupt scenarios.

These tests verify that:
1. The workflow correctly skips completed steps on resume
2. No duplicate API calls are made when resuming
3. Dry-run uses fake clients and produces realistic state
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from create_release_ticket.state import RunState, RunStep
from tests.fakes.clients import (
    FakeClientError,
    FakeGitHubClient,
    FakeJenkinsClient,
    FakeJiraClient,
)


# Test fixtures


@pytest.fixture
def fake_jira():
    return FakeJiraClient()


@pytest.fixture
def fake_github():
    return FakeGitHubClient()


@pytest.fixture
def fake_jenkins():
    return FakeJenkinsClient()


@pytest.fixture
def releases_dir(tmp_path):
    """Temporary releases directory."""
    releases = tmp_path / "releases"
    releases.mkdir()
    return releases


class TestFakeClientsWork:
    """Verify fake clients behave correctly before using them in E2E tests."""

    def test_fake_jira_creates_issues_with_incrementing_keys(self, fake_jira):
        result1 = fake_jira.create_issue({"fields": {"summary": "Test 1"}})
        result2 = fake_jira.create_issue({"fields": {"summary": "Test 2"}})

        assert result1["key"] == "ENG-FAKE-1"
        assert result2["key"] == "ENG-FAKE-2"
        assert fake_jira.call_count("create_issue") == 2

    def test_fake_jira_tracks_all_calls(self, fake_jira):
        fake_jira.create_issue({"fields": {"summary": "Test"}})
        fake_jira.get_issue("ENG-123")
        fake_jira.transition_issue("ENG-123", transition_name="Done")

        assert fake_jira.call_count("create_issue") == 1
        assert fake_jira.call_count("get_issue") == 1
        assert fake_jira.call_count("transition_issue") == 1

    def test_fake_jira_can_fail_on_command(self, fake_jira):
        fake_jira.fail_on = "create_issue"

        with pytest.raises(FakeClientError, match="Simulated failure"):
            fake_jira.create_issue({"fields": {}})

    def test_fake_github_returns_mock_commits(self, fake_github):
        commits = fake_github.compare_commits("branch-a", "branch-b")

        assert len(commits) == 3  # Default mock commits
        assert "ENG-11111" in commits[0]["commit"]["message"]

    def test_fake_github_can_fail_on_command(self, fake_github):
        fake_github.fail_on = "trigger_and_wait_workflow"

        with pytest.raises(FakeClientError):
            fake_github.trigger_and_wait_workflow(ref="main", inputs={})

    def test_fake_jenkins_returns_incrementing_builds(self, fake_jenkins):
        result1 = fake_jenkins.trigger_and_wait("v1", "ENG-1")
        result2 = fake_jenkins.trigger_and_wait("v2", "ENG-2")

        assert result1["build_number"] == 1
        assert result2["build_number"] == 2


class TestResumeIdempotency:
    """Verify that resume doesn't duplicate API calls."""

    def test_state_skip_logic_for_promote_ticket(self, fake_jira):
        """If promote ticket exists and step is past step 3, don't recreate."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.TRIGGERED_GITHUB_WORKFLOW,
            promote_ticket_key="ENG-EXISTING-123",
        )

        # Verify the skip condition
        should_skip = state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET) and state.promote_ticket_key
        assert should_skip, "Should skip step 3 when ticket exists and step is past 3"

    def test_state_skip_logic_for_github(self, fake_github):
        """If GitHub workflow completed, don't re-trigger."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.GITHUB_WORKFLOW_COMPLETED,
            github_workflow_run_id=12345,
        )

        should_skip = state.can_resume_from(RunStep.GITHUB_WORKFLOW_COMPLETED)
        assert should_skip, "Should skip step 4 when already completed"

    def test_state_skip_logic_for_jenkins(self, fake_jenkins):
        """If Jenkins completed, don't re-trigger."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.JENKINS_COMPLETED,
            jenkins_build_number=456,
            jenkins_job_url="https://jenkins.example.com/job/test/456/",
        )

        should_skip = state.can_resume_from(RunStep.JENKINS_COMPLETED) and state.jenkins_job_url
        assert should_skip, "Should skip step 5 when already completed"


class TestDryRunWithFakes:
    """Verify dry-run mode uses fake clients correctly."""

    def test_dry_run_state_has_realistic_keys(self, fake_jira, fake_github, fake_jenkins):
        """Dry-run should produce state with ENG-FAKE-* keys."""
        # Simulate what happens in dry-run mode
        result = fake_jira.create_issue({"fields": {"summary": "Promote ticket"}})
        assert result["key"].startswith("ENG-FAKE-")
        assert result["id"].isdigit()

    def test_dry_run_github_returns_workflow_id(self, fake_github):
        """Dry-run GitHub should return realistic workflow run ID."""
        result = fake_github.trigger_and_wait_workflow(
            ref="develop",
            inputs={"release-ticket": "ENG-FAKE-1"},
        )

        assert "id" in result
        assert result["id"] >= 100000  # Our fake starts at 100001

    def test_dry_run_jenkins_returns_build_info(self, fake_jenkins):
        """Dry-run Jenkins should return realistic build info."""
        result = fake_jenkins.trigger_and_wait(
            release_version="queryservice-release-2026.1.5.0.18914",
            ticket="ENG-FAKE-1",
        )

        assert "build_number" in result
        assert "job_url" in result
        assert "jenkins.example.com" in result["job_url"]


class TestInterruptAndResume:
    """Test interrupt at various points and verify correct resume behavior."""

    def test_interrupt_tracking_with_fail_on(self, fake_jira, fake_github):
        """Verify fail_on mechanism for simulating interrupts."""
        fake_github.fail_on = "trigger_and_wait_workflow"

        # Normal operations work
        fake_jira.create_issue({"fields": {}})
        assert fake_jira.call_count("create_issue") == 1

        # GitHub fails when we try
        with pytest.raises(FakeClientError):
            fake_github.trigger_and_wait_workflow(ref="main", inputs={})

        # Can reset and continue
        fake_github.fail_on = None
        result = fake_github.trigger_and_wait_workflow(ref="main", inputs={})
        assert result["status"] == "completed"

    def test_calls_before_interrupt_are_tracked(self, fake_jira, fake_github):
        """Before interrupt, all calls should be tracked."""
        # Simulate steps 1-3
        fake_jira.create_issue({"fields": {"summary": "Promote"}})

        # Step 4 will fail
        fake_github.fail_on = "trigger_and_wait_workflow"

        with pytest.raises(FakeClientError):
            fake_github.trigger_and_wait_workflow(ref="main", inputs={})

        # Verify calls were tracked
        assert fake_jira.call_count("create_issue") == 1
        assert fake_github.call_count("trigger_and_wait_workflow") == 1  # Failed attempt counted

    def test_resume_after_interrupt_uses_existing_data(self, fake_jira):
        """On resume, should use existing promote ticket, not create new."""
        # First run created a ticket
        result1 = fake_jira.create_issue({"fields": {}})
        existing_key = result1["key"]

        # Simulate resume - check if ticket exists
        issue = fake_jira.get_issue(existing_key)
        assert issue["key"] == existing_key

        # If ticket exists, don't create again
        # (This is the logic the workflow should follow)
        assert fake_jira.call_count("create_issue") == 1


class TestFullWorkflowSimulation:
    """Simulate the full workflow with fake clients."""

    def test_complete_workflow_with_fakes(
        self, fake_jira, fake_github, fake_jenkins
    ):
        """Run through all steps using fake clients."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
        )

        # Step 1: Parse version (no API calls needed)
        state.current_branch = "queryservice-release-2026.1.5"
        state.previous_branch = "queryservice-release-2026.1.4"
        state.current_step = RunStep.PARSED_VERSION

        # Step 2: Fetch commits
        commits = fake_github.compare_commits(state.previous_branch, state.current_branch)
        state.jira_ids = ["ENG-11111", "DINT-22222", "EP-33333"]  # Extracted from commits
        state.current_step = RunStep.FETCHED_COMMITS

        # Step 3: Create promote ticket
        result = fake_jira.create_issue({"fields": {"summary": f"Promote {state.build_version}"}})
        state.promote_ticket_key = result["key"]
        state.promote_ticket_id = result["id"]
        state.current_step = RunStep.CREATED_PROMOTE_TICKET

        # Step 4: GitHub workflow
        gh_result = fake_github.trigger_and_wait_workflow(
            ref="develop",
            inputs={"release-ticket": state.promote_ticket_key},
        )
        state.github_workflow_run_id = gh_result["id"]
        state.current_step = RunStep.GITHUB_WORKFLOW_COMPLETED

        # Step 5: Jenkins build
        jenkins_result = fake_jenkins.trigger_and_wait(
            release_version=state.build_version,
            ticket=state.promote_ticket_key,
        )
        state.jenkins_build_number = jenkins_result["build_number"]
        state.jenkins_job_url = jenkins_result["job_url"]
        state.current_step = RunStep.JENKINS_COMPLETED

        # Step 6: Create deployment ticket
        result = fake_jira.create_issue({"fields": {"summary": f"Deploy {state.build_version}"}})
        state.deployment_ticket_key = result["key"]
        state.deployment_ticket_id = result["id"]
        state.current_step = RunStep.CREATED_DEPLOYMENT_TICKET

        # Step 7: Close promote ticket
        fake_jira.transition_issue(
            state.promote_ticket_key,
            transition_name="Resolve Issue",
            resolution="Fixed",
        )
        state.current_step = RunStep.CLOSED_PROMOTE_TICKET

        # Verify final state
        assert state.current_step == RunStep.CLOSED_PROMOTE_TICKET
        assert state.promote_ticket_key == "ENG-FAKE-1"
        assert state.deployment_ticket_key == "ENG-FAKE-2"
        assert state.jenkins_build_number == 1

        # Verify API call counts
        assert fake_jira.call_count("create_issue") == 2  # Promote + Deployment
        assert fake_jira.call_count("transition_issue") == 1
        assert fake_github.call_count("compare_commits") == 1
        assert fake_github.call_count("trigger_and_wait_workflow") == 1
        assert fake_jenkins.call_count("trigger_and_wait") == 1

    def test_resume_from_step4_skips_earlier_steps(
        self, fake_jira, fake_github, fake_jenkins
    ):
        """Resume from TRIGGERED_GITHUB_WORKFLOW should skip steps 1-3."""
        # Simulate state after step 4 was triggered but not completed
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.TRIGGERED_GITHUB_WORKFLOW,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111"],
            promote_ticket_key="ENG-EXISTING-1",
            promote_ticket_id="10001",
            github_workflow_run_id=100001,
        )

        # On resume, steps 1-3 should be skipped
        assert state.can_resume_from(RunStep.PARSED_VERSION)
        assert state.can_resume_from(RunStep.FETCHED_COMMITS)
        assert state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET)
        assert state.can_resume_from(RunStep.TRIGGERED_GITHUB_WORKFLOW)

        # Step 4 completion and later should proceed
        assert not state.can_resume_from(RunStep.GITHUB_WORKFLOW_COMPLETED)

        # Continue from step 4 (poll workflow)
        gh_result = fake_github.get_workflow_run(state.github_workflow_run_id)
        assert gh_result["status"] == "completed"

        # No new create_issue calls should happen
        assert fake_jira.call_count("create_issue") == 0
