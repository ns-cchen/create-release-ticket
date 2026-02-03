"""E2E tests that run the actual workflow_service._run_workflow() with fake clients.

These tests verify the full workflow code path, including:
- State transitions
- WebSocket notifications (mocked)
- Correct client calls at each step
- Resume from interrupted points
"""

from __future__ import annotations

import json
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

# We need to patch the RELEASES_DIR and ws_manager for these tests
pytestmark = pytest.mark.asyncio(loop_scope="function")


@pytest.fixture
def releases_dir(tmp_path):
    """Temporary releases directory."""
    d = tmp_path / "releases"
    d.mkdir()
    return d


@pytest.fixture
def mock_ws():
    """Mock WebSocket manager so no real WS connections are needed."""
    mock = AsyncMock()
    mock.send_step_start = AsyncMock()
    mock.send_step_progress = AsyncMock()
    mock.send_step_complete = AsyncMock()
    mock.send_workflow_paused = AsyncMock()
    mock.send_workflow_complete = AsyncMock()
    mock.send_workflow_error = AsyncMock()
    return mock


@pytest.fixture
def workflow_service(releases_dir, mock_ws):
    """Create WorkflowService with patched dirs and ws_manager."""
    # Import the module first to ensure it's loaded
    import backend.services.workflow_service as ws_module

    with (
        patch.object(ws_module, "RELEASES_DIR", releases_dir),
        patch.object(ws_module, "ws_manager", mock_ws),
    ):
        svc = ws_module.WorkflowService()
        yield svc


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
def base_state():
    """A fresh state ready for a workflow run."""
    return RunState(
        build_version="queryservice-release-2026.1.5.0.18914",
        rollback_version="queryservice-release-2026.1.4.0.18900",
        started_at="2026-01-29T10:00:00",
    )


# ── Full workflow ────────────────────────────────────────────────────────


class TestFullWorkflowE2E:
    async def test_complete_dry_run_workflow(
        self, workflow_service, releases_dir, mock_ws, base_state,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Full dry-run workflow should complete all 7 steps with fake clients."""
        release_id = "test-dry-run"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=base_state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        # Verify final state
        assert base_state.current_step == RunStep.COMPLETED
        assert base_state.promote_ticket_key.startswith("ENG-FAKE-")
        assert base_state.deployment_ticket_key.startswith("ENG-FAKE-")
        assert base_state.jenkins_build_number >= 1
        assert "jenkins.example.com" in base_state.jenkins_job_url
        assert base_state.completed_at != ""

        # Verify API call counts
        assert fake_jira.call_count("create_issue") == 2  # promote + deployment
        assert fake_jira.call_count("get_issue") == 1  # step 7 checks status
        assert fake_github.call_count("compare_commits") == 1
        # GitHub workflow is now split into trigger + poll phases
        assert fake_github.call_count("trigger_workflow") == 1
        assert fake_github.call_count("get_latest_workflow_run") == 1
        assert fake_github.call_count("poll_workflow_run") == 1
        # Jenkins build is now split into trigger + wait_for_start + poll phases
        assert fake_jenkins.call_count("trigger_build") == 1
        assert fake_jenkins.call_count("wait_for_build_start") == 1
        assert fake_jenkins.call_count("poll_build_by_number") == 1

        # Verify WebSocket notifications were sent
        assert mock_ws.send_step_start.call_count == 7
        assert mock_ws.send_step_complete.call_count == 7
        assert mock_ws.send_workflow_complete.call_count == 1

        # Verify state file was saved
        state_file = releases_dir / f"{release_id}.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["current_step"] == "completed"

    async def test_dry_run_state_has_jira_ids_from_fake_github(
        self, workflow_service, releases_dir, mock_ws, base_state,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Dry-run should extract Jira IDs from fake GitHub commits."""
        release_id = "test-jira-ids"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=base_state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        # FakeGitHub returns commits with ENG-11111, DINT-22222, EP-33333
        assert len(base_state.jira_ids) == 3
        assert "ENG-11111" in base_state.jira_ids


# ── Stop after ───────────────────────────────────────────────────────────


class TestStopAfter:
    async def test_stop_after_step3(
        self, workflow_service, releases_dir, mock_ws, base_state,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Workflow should pause after step 3."""
        release_id = "test-stop"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=base_state,
            dry_run=True,
            stop_after=RunStep.CREATED_PROMOTE_TICKET,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert base_state.current_step == RunStep.CREATED_PROMOTE_TICKET
        assert base_state.promote_ticket_key is not None

        # Steps 4-7 should NOT have run
        assert fake_github.call_count("trigger_and_wait_workflow") == 0
        assert fake_jenkins.call_count("trigger_and_wait") == 0
        assert mock_ws.send_workflow_paused.call_count == 1


# ── Resume from interrupted state ────────────────────────────────────────


class TestResumeE2E:
    async def test_resume_from_step3_skips_steps_1_to_3(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Resume from CREATED_PROMOTE_TICKET should skip steps 1-3."""
        release_id = "test-resume-from-3"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.CREATED_PROMOTE_TICKET,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111"],
            promote_ticket_key="ENG-EXISTING-1",
            promote_ticket_id="10001",
            started_at="2026-01-29T10:00:00",
        )

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        # Should complete
        assert state.current_step == RunStep.COMPLETED

        # Steps 1-3 should NOT have re-run
        assert fake_github.call_count("compare_commits") == 0  # Step 2 skipped
        assert fake_jira.call_count("create_issue") == 1  # Only deployment ticket (step 6)

        # Promote ticket key should be preserved
        assert state.promote_ticket_key == "ENG-EXISTING-1"

    async def test_resume_from_step5_skips_github_and_jenkins(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Resume from JENKINS_COMPLETED should skip steps 1-5."""
        release_id = "test-resume-from-5"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.JENKINS_COMPLETED,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111"],
            promote_ticket_key="ENG-EXISTING-1",
            promote_ticket_id="10001",
            jenkins_build_number=42,
            jenkins_job_url="https://jenkins.example.com/job/test/42/",
            started_at="2026-01-29T10:00:00",
        )

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # GitHub and Jenkins should NOT have been called
        assert fake_github.call_count("trigger_and_wait_workflow") == 0
        assert fake_github.call_count("compare_commits") == 0
        assert fake_jenkins.call_count("trigger_and_wait") == 0

        # Only deployment ticket creation + close promote
        assert fake_jira.call_count("create_issue") == 1  # Deployment ticket


# ── Interrupt and resume ─────────────────────────────────────────────────


class TestInterruptResumeE2E:
    async def test_github_failure_then_resume(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """GitHub fails mid-workflow, then resume completes successfully."""
        release_id = "test-gh-fail"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            started_at="2026-01-29T10:00:00",
        )

        # First run: GitHub will fail (now fails on trigger_workflow since split)
        fake_github.fail_on = "trigger_workflow"

        # The workflow should catch the error and set error state
        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        # Should be in error state
        assert state.error_message is not None
        assert "Simulated failure" in state.error_message
        # Promote ticket was created before the failure
        assert state.promote_ticket_key is not None

        # Step 3 was completed
        promote_key_from_first_run = state.promote_ticket_key
        create_count_before = fake_jira.call_count("create_issue")

        # Resume: fix the failure
        fake_github.fail_on = None
        state.error_message = None
        state.error_step = None

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        # Should complete now
        assert state.current_step == RunStep.COMPLETED
        assert state.error_message is None

        # Promote ticket should NOT have been re-created
        assert state.promote_ticket_key == promote_key_from_first_run

        # Only 1 additional create_issue for deployment ticket
        create_count_after = fake_jira.call_count("create_issue")
        assert create_count_after - create_count_before == 1

    async def test_jenkins_failure_then_resume(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Jenkins fails mid-workflow, then resume completes successfully."""
        release_id = "test-jenkins-fail"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            started_at="2026-01-29T10:00:00",
        )

        # First run: Jenkins will fail (now fails on trigger_build since split)
        fake_jenkins.fail_on = "trigger_build"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.error_message is not None
        # GitHub completed, promote ticket created
        assert state.promote_ticket_key is not None
        assert state.github_workflow_run_id is not None

        gh_calls_before = fake_github.call_count("trigger_and_wait_workflow")
        jira_creates_before = fake_jira.call_count("create_issue")

        # Resume
        fake_jenkins.fail_on = None
        state.error_message = None
        state.error_step = None

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # GitHub should NOT have been re-triggered
        assert fake_github.call_count("trigger_and_wait_workflow") == gh_calls_before

        # Promote ticket should NOT have been re-created (only deployment ticket)
        assert fake_jira.call_count("create_issue") - jira_creates_before == 1

    async def test_jira_promote_failure_then_resume(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Jira fails creating promote ticket (step 3), then resume succeeds."""
        release_id = "test-jira-promote-fail"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            started_at="2026-01-29T10:00:00",
        )

        # First run: Jira create_issue will fail
        fake_jira.fail_on = "create_issue"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        # Should be in error state at step 2 (commits fetched, then step 3 failed)
        assert state.error_message is not None
        assert "Simulated failure" in state.error_message
        # Steps 1-2 completed but promote ticket NOT created
        assert state.promote_ticket_key is None
        assert len(state.jira_ids) > 0  # Commits were fetched

        gh_compare_before = fake_github.call_count("compare_commits")

        # Resume: fix the failure
        fake_jira.fail_on = None
        state.error_message = None
        state.error_step = None

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # Steps 1-2 should NOT have re-run (commits already fetched)
        assert fake_github.call_count("compare_commits") == gh_compare_before

        # Promote ticket should now exist
        assert state.promote_ticket_key is not None
        assert state.promote_ticket_key.startswith("ENG-FAKE-")

    async def test_jira_deployment_failure_then_resume(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Jira fails creating deployment ticket (step 6), then resume succeeds."""
        release_id = "test-jira-deploy-fail"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.JENKINS_COMPLETED,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111"],
            promote_ticket_key="ENG-EXISTING-1",
            promote_ticket_id="10001",
            jenkins_build_number=42,
            jenkins_job_url="https://jenkins.example.com/job/test/42/",
            started_at="2026-01-29T10:00:00",
        )

        # Jira fails on create_issue (this time it's the deployment ticket)
        fake_jira.fail_on = "create_issue"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.error_message is not None
        assert state.deployment_ticket_key is None

        # Steps 1-5 should NOT have run
        assert fake_github.call_count("compare_commits") == 0
        assert fake_jenkins.call_count("trigger_and_wait") == 0

        # Resume
        fake_jira.fail_on = None
        state.error_message = None
        state.error_step = None

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED
        assert state.deployment_ticket_key is not None
        assert state.promote_ticket_key == "ENG-EXISTING-1"  # Preserved


# ── Resume from every intermediate step ──────────────────────────────────


class TestResumeFromEveryStep:
    async def test_resume_from_step2_skips_version_parsing(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Resume from FETCHED_COMMITS should skip steps 1-2."""
        release_id = "test-resume-from-2"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.FETCHED_COMMITS,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111", "DINT-22222"],
            started_at="2026-01-29T10:00:00",
        )

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # Steps 1-2 skipped
        assert fake_github.call_count("compare_commits") == 0
        assert fake_github.call_count("check_branch_exists") == 0

        # Steps 3-7 all ran
        assert fake_jira.call_count("create_issue") == 2  # promote + deployment
        # GitHub workflow is now split into trigger + poll phases
        assert fake_github.call_count("trigger_workflow") == 1
        assert fake_github.call_count("poll_workflow_run") == 1
        # Jenkins build is now split into trigger + poll phases
        assert fake_jenkins.call_count("trigger_build") == 1
        assert fake_jenkins.call_count("poll_build_by_number") == 1

    async def test_resume_from_step4_skips_github_runs_jenkins(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Resume from GITHUB_WORKFLOW_COMPLETED should skip 1-4, run 5-7."""
        release_id = "test-resume-from-4"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.GITHUB_WORKFLOW_COMPLETED,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111"],
            promote_ticket_key="ENG-EXISTING-1",
            promote_ticket_id="10001",
            github_workflow_run_id=100001,
            started_at="2026-01-29T10:00:00",
        )

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # GitHub NOT re-triggered, commits NOT re-fetched
        assert fake_github.call_count("trigger_workflow") == 0
        assert fake_github.call_count("poll_workflow_run") == 0
        assert fake_github.call_count("compare_commits") == 0

        # Jenkins DID run (split phases)
        assert fake_jenkins.call_count("trigger_build") == 1
        assert fake_jenkins.call_count("poll_build_by_number") == 1
        assert state.jenkins_build_number is not None

        # Deployment ticket created, promote closed
        assert fake_jira.call_count("create_issue") == 1  # deployment only

    async def test_resume_from_step6_only_closes_promote(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Resume from CREATED_DEPLOYMENT_TICKET should only run step 7."""
        release_id = "test-resume-from-6"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.CREATED_DEPLOYMENT_TICKET,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111"],
            promote_ticket_key="ENG-EXISTING-1",
            promote_ticket_id="10001",
            deployment_ticket_key="ENG-EXISTING-2",
            deployment_ticket_id="10002",
            jenkins_build_number=42,
            jenkins_job_url="https://jenkins.example.com/job/test/42/",
            started_at="2026-01-29T10:00:00",
        )

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # Nothing re-triggered except close promote
        assert fake_github.call_count("compare_commits") == 0
        assert fake_github.call_count("trigger_and_wait_workflow") == 0
        assert fake_jenkins.call_count("trigger_and_wait") == 0
        assert fake_jira.call_count("create_issue") == 0

        # Step 7 ran (close promote)
        assert fake_jira.call_count("get_issue") == 1
        assert fake_jira.call_count("transition_issue") == 1

        # Existing keys preserved
        assert state.promote_ticket_key == "ENG-EXISTING-1"
        assert state.deployment_ticket_key == "ENG-EXISTING-2"


# ── Step 7 graceful failure ──────────────────────────────────────────────


class TestStep7GracefulFailure:
    async def test_close_promote_fails_but_workflow_completes(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Step 7 (close promote) has internal try-catch — workflow should still complete."""
        release_id = "test-step7-graceful"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.CREATED_DEPLOYMENT_TICKET,
            current_branch="queryservice-release-2026.1.5",
            previous_branch="queryservice-release-2026.1.4",
            jira_ids=["ENG-11111"],
            promote_ticket_key="ENG-EXISTING-1",
            promote_ticket_id="10001",
            deployment_ticket_key="ENG-EXISTING-2",
            deployment_ticket_id="10002",
            jenkins_build_number=42,
            jenkins_job_url="https://jenkins.example.com/job/test/42/",
            started_at="2026-01-29T10:00:00",
        )

        # Make step 7 Jira calls fail (get_issue is first call in step 7)
        fake_jira.fail_on = "get_issue"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        # Workflow should still COMPLETE despite step 7 failure
        assert state.current_step == RunStep.COMPLETED
        assert state.error_message is None  # Not an error — graceful degradation
        assert state.completed_at != ""


# ── Stop-after then resume ───────────────────────────────────────────────


class TestStopAfterThenResume:
    async def test_stop_after_step3_then_resume_to_completion(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Two-phase: stop after step 3, then resume from step 3 to completion."""
        release_id = "test-stop-resume"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            started_at="2026-01-29T10:00:00",
        )

        # Phase 1: Run steps 1-3 only
        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            stop_after=RunStep.CREATED_PROMOTE_TICKET,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.CREATED_PROMOTE_TICKET
        assert state.promote_ticket_key is not None
        promote_key = state.promote_ticket_key
        assert mock_ws.send_workflow_paused.call_count == 1

        jira_creates_phase1 = fake_jira.call_count("create_issue")
        gh_compare_phase1 = fake_github.call_count("compare_commits")

        # Phase 2: Resume from step 3, no stop_after
        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # Steps 1-3 NOT repeated
        assert fake_github.call_count("compare_commits") == gh_compare_phase1
        assert state.promote_ticket_key == promote_key  # Preserved

        # Only 1 additional create_issue (deployment ticket in step 6)
        assert fake_jira.call_count("create_issue") - jira_creates_phase1 == 1

        # Steps 4-7 ran in phase 2 (split phases)
        assert fake_github.call_count("trigger_workflow") == 1
        assert fake_github.call_count("poll_workflow_run") == 1
        assert fake_jenkins.call_count("trigger_build") == 1
        assert fake_jenkins.call_count("poll_build_by_number") == 1

    async def test_stop_after_step5_then_resume(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Stop after Jenkins (step 5), then resume for steps 6-7."""
        release_id = "test-stop-step5"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            started_at="2026-01-29T10:00:00",
        )

        # Phase 1: Run steps 1-5
        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            stop_after=RunStep.JENKINS_COMPLETED,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.JENKINS_COMPLETED
        assert state.jenkins_build_number is not None
        assert state.deployment_ticket_key is None  # Step 6 didn't run

        jenkins_trigger_calls = fake_jenkins.call_count("trigger_build")
        jenkins_poll_calls = fake_jenkins.call_count("poll_build_by_number")

        # Phase 2: Resume for steps 6-7
        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED
        assert state.deployment_ticket_key is not None

        # Jenkins NOT re-triggered (split phases)
        assert fake_jenkins.call_count("trigger_build") == jenkins_trigger_calls
        assert fake_jenkins.call_count("poll_build_by_number") == jenkins_poll_calls


# ── Multiple sequential failures ─────────────────────────────────────────


class TestMultipleFailures:
    async def test_fail_at_step4_then_fail_at_step5_then_complete(
        self, workflow_service, releases_dir, mock_ws,
        fake_jira, fake_github, fake_jenkins,
    ):
        """Fail at GitHub (step 4), resume, fail at Jenkins (step 5), resume → complete."""
        release_id = "test-multi-fail"
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            started_at="2026-01-29T10:00:00",
        )

        # Run 1: GitHub fails at step 4 (trigger_workflow since split)
        fake_github.fail_on = "trigger_workflow"

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.error_message is not None
        assert state.promote_ticket_key is not None
        promote_key = state.promote_ticket_key

        # Run 2: Fix GitHub, but now Jenkins fails (trigger_build since split)
        fake_github.fail_on = None
        fake_jenkins.fail_on = "trigger_build"
        state.error_message = None
        state.error_step = None

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.error_message is not None
        assert state.github_workflow_run_id is not None  # Step 4 completed this time

        jira_creates_before_final = fake_jira.call_count("create_issue")

        # Run 3: Fix Jenkins → should complete
        fake_jenkins.fail_on = None
        state.error_message = None
        state.error_step = None

        await workflow_service._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=True,
            jira_client=fake_jira,
            github_client=fake_github,
            jenkins_client=fake_jenkins,
        )

        assert state.current_step == RunStep.COMPLETED

        # Promote ticket NEVER re-created across all 3 runs
        assert state.promote_ticket_key == promote_key

        # Only 1 new create_issue in run 3 (deployment ticket)
        assert fake_jira.call_count("create_issue") - jira_creates_before_final == 1
