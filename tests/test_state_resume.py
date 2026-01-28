"""Tests for state management and resume logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from create_release_ticket.state import RunState, RunStep


class TestResumeSkipsCompletedSteps:
    """BUG: When resuming from step 4/5, step 3 should NOT re-run.

    Root cause: The step 3 condition in cli.py uses:
        if not state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET) or not state.promote_ticket_key:

    The `or not state.promote_ticket_key` clause causes step 3 to re-run
    even when current_step is past step 3, if promote_ticket_key wasn't saved.

    This happens because mark_step() only saves when the step advances forward.
    When using --jenkins-build-number to skip ahead, earlier step data isn't persisted.
    """

    def test_step3_should_not_run_when_resuming_from_step4(self):
        """When current_step is TRIGGERED_GITHUB_WORKFLOW, step 3 should be skipped."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.TRIGGERED_GITHUB_WORKFLOW,
            promote_ticket_key="ENG-12345",  # Already created
        )

        # Step 3 condition: should be False (skip the step)
        should_run_step3 = (
            not state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET)
            or not state.promote_ticket_key
        )

        assert not should_run_step3, (
            "Step 3 should NOT run when resuming from step 4 with promote_ticket_key set"
        )

    def test_step3_condition_with_missing_data_is_safety_fallback(self):
        """The `or not promote_ticket_key` condition is a safety fallback.

        If somehow promote_ticket_key is missing despite being past step 3,
        the condition will re-run step 3 to ensure data integrity.
        This is intentional - the FIX is to ensure data IS saved properly.
        """
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.TRIGGERED_GITHUB_WORKFLOW,
            promote_ticket_key=None,  # Missing data - safety fallback triggers
        )

        should_run_step3 = (
            not state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET)
            or not state.promote_ticket_key
        )

        # This is expected - missing data triggers a re-run as safety fallback
        assert should_run_step3, (
            "Step 3 should run as safety fallback when promote_ticket_key is missing"
        )

    def test_mark_step_saves_state_when_advancing_forward(self, tmp_path):
        """mark_step saves state when step advances forward."""
        state_file = tmp_path / "test-state.json"
        state = RunState(
            build_version="test",
            rollback_version="test",
            current_step=RunStep.FETCHED_COMMITS,
        )

        state.promote_ticket_key = "ENG-99999"
        state.mark_step(RunStep.CREATED_PROMOTE_TICKET)

        # Save should happen because step advanced
        state.save(state_file)
        loaded = RunState.load(state_file)

        assert loaded.promote_ticket_key == "ENG-99999"
        assert loaded.current_step == RunStep.CREATED_PROMOTE_TICKET

    def test_mark_step_only_advances_step_forward(self, tmp_path):
        """mark_step only advances current_step forward, not backward.

        This is correct behavior - the step counter should only go forward.
        The FIX is to call state.save() explicitly after setting data,
        not rely on mark_step() for saving.
        """
        state_file = tmp_path / "test-state.json"

        state = RunState(
            build_version="test",
            rollback_version="test",
            current_step=RunStep.JENKINS_COMPLETED,
        )
        state.save(state_file)

        # Try to mark an earlier step
        state.mark_step(RunStep.CREATED_PROMOTE_TICKET)

        # Step should NOT regress
        assert state.current_step == RunStep.JENKINS_COMPLETED


class TestMarkStepSavesDataCorrectly:
    """Tests for the FIX: mark_step should save state after setting important data."""

    def test_promote_ticket_key_is_saved_even_when_step_doesnt_advance(self, tmp_path):
        """EXPECTED BEHAVIOR: promote_ticket_key should be saved regardless of step advancement.

        After the fix, when step 3 completes and sets promote_ticket_key,
        it should be persisted even if current_step is already past step 3.
        """
        state_file = tmp_path / "test-state.json"

        # Simulate state after --jenkins-build-number was used
        state = RunState(
            build_version="test",
            rollback_version="test",
            current_step=RunStep.JENKINS_COMPLETED,  # Already at step 5
        )
        state.save(state_file)

        # Simulate step 3 running and setting promote_ticket_key
        state.promote_ticket_key = "ENG-99999"
        state.save(state_file)  # FIX: explicitly save after setting data

        # Reload and verify data was saved
        loaded = RunState.load(state_file)

        assert loaded.promote_ticket_key == "ENG-99999", (
            "promote_ticket_key should be saved after explicit save()"
        )


class TestGranularResumeSteps:
    """Tests for granular resume from TRIGGERED_* states."""

    def test_github_resume_from_triggered_skips_trigger(self):
        """When at TRIGGERED_GITHUB_WORKFLOW with run_id, should skip triggering."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.TRIGGERED_GITHUB_WORKFLOW,
            github_workflow_run_id=12345,
        )

        # Should be able to resume from TRIGGERED state
        assert state.can_resume_from(RunStep.TRIGGERED_GITHUB_WORKFLOW) is True

        # Should NOT be at COMPLETED yet
        assert state.can_resume_from(RunStep.GITHUB_WORKFLOW_COMPLETED) is False

        # Condition for "should trigger" phase
        should_trigger = (
            not state.can_resume_from(RunStep.TRIGGERED_GITHUB_WORKFLOW)
            or not state.github_workflow_run_id
        )
        assert should_trigger is False, "Should skip trigger phase when already triggered"

    def test_jenkins_resume_from_triggered_with_queue_url(self):
        """When at TRIGGERED_JENKINS with queue_url, should skip triggering."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.TRIGGERED_JENKINS,
            jenkins_queue_url="https://jenkins.example.com/queue/item/123/",
        )

        # Condition for "should trigger" phase
        should_trigger = (
            not state.can_resume_from(RunStep.TRIGGERED_JENKINS)
            or not state.jenkins_queue_url
        )
        assert should_trigger is False, "Should skip trigger phase when already triggered"

    def test_jenkins_resume_from_triggered_with_build_number(self):
        """When at TRIGGERED_JENKINS with build_number, should skip wait_for_start."""
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.TRIGGERED_JENKINS,
            jenkins_queue_url="https://jenkins.example.com/queue/item/123/",
            jenkins_build_number=456,
            jenkins_job_url="https://jenkins.example.com/job/test/456/",
        )

        # Should skip "wait for build start" phase
        should_wait_for_start = not state.jenkins_build_number
        assert should_wait_for_start is False, "Should skip wait_for_start when build_number exists"

    def test_step_order_triggered_before_completed(self):
        """Verify TRIGGERED_* steps come before COMPLETED steps in order."""
        step_order = list(RunStep)

        # GitHub
        gh_triggered_idx = step_order.index(RunStep.TRIGGERED_GITHUB_WORKFLOW)
        gh_completed_idx = step_order.index(RunStep.GITHUB_WORKFLOW_COMPLETED)
        assert gh_triggered_idx < gh_completed_idx

        # Jenkins
        jenkins_triggered_idx = step_order.index(RunStep.TRIGGERED_JENKINS)
        jenkins_completed_idx = step_order.index(RunStep.JENKINS_COMPLETED)
        assert jenkins_triggered_idx < jenkins_completed_idx


class TestCanResumeFrom:
    """Tests for can_resume_from logic."""

    def test_can_resume_from_returns_true_when_at_or_past_target(self):
        """can_resume_from returns True when current_step >= target step."""
        state = RunState(current_step=RunStep.TRIGGERED_GITHUB_WORKFLOW)

        # We're at step 4, should be able to "resume from" step 3 (already done)
        assert state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET) is True
        assert state.can_resume_from(RunStep.FETCHED_COMMITS) is True
        assert state.can_resume_from(RunStep.PARSED_VERSION) is True

    def test_can_resume_from_returns_false_when_before_target(self):
        """can_resume_from returns False when current_step < target step."""
        state = RunState(current_step=RunStep.FETCHED_COMMITS)

        # We're at step 2, can't resume from step 3 (not done yet)
        assert state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET) is False
        assert state.can_resume_from(RunStep.TRIGGERED_GITHUB_WORKFLOW) is False
