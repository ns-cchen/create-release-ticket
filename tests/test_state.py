"""Tests for RunState: serialization, persistence, clear, error, resources."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from create_release_ticket.state import (
    RunState,
    RunStep,
    create_new_run,
    get_resumable_state,
)


# ── to_dict / from_dict round-trip ───────────────────────────────────────


class TestStateSerialization:
    def test_round_trip_minimal(self):
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
        )
        data = state.to_dict()
        restored = RunState.from_dict(data)
        assert restored.build_version == state.build_version
        assert restored.current_step == RunStep.NOT_STARTED

    def test_round_trip_full(self):
        state = RunState(
            build_version="queryservice-release-2026.1.5.0.18914",
            rollback_version="queryservice-release-2026.1.4.0.18900",
            current_step=RunStep.JENKINS_COMPLETED,
            promote_ticket_key="ENG-FAKE-1",
            promote_ticket_id="10001",
            deployment_ticket_key="ENG-FAKE-2",
            jenkins_build_number=42,
            jenkins_job_url="https://jenkins.example.com/job/test/42/",
            jira_ids=["ENG-111", "DINT-222"],
        )
        data = state.to_dict()
        restored = RunState.from_dict(data)

        assert restored.current_step == RunStep.JENKINS_COMPLETED
        assert restored.promote_ticket_key == "ENG-FAKE-1"
        assert restored.jenkins_build_number == 42
        assert restored.jira_ids == ["ENG-111", "DINT-222"]

    def test_current_step_serializes_as_string(self):
        state = RunState(current_step=RunStep.CREATED_PROMOTE_TICKET)
        data = state.to_dict()
        assert data["current_step"] == "created_promote_ticket"


# ── save / load ──────────────────────────────────────────────────────────


class TestStatePersistence:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "state.json"
        state = RunState(
            build_version="test-v",
            rollback_version="test-r",
            current_step=RunStep.FETCHED_COMMITS,
            jira_ids=["ENG-1"],
        )
        state.save(path)
        loaded = RunState.load(path)

        assert loaded is not None
        assert loaded.build_version == "test-v"
        assert loaded.current_step == RunStep.FETCHED_COMMITS
        assert loaded.jira_ids == ["ENG-1"]

    def test_load_nonexistent_returns_none(self, tmp_path):
        path = tmp_path / "missing.json"
        assert RunState.load(path) is None

    def test_load_corrupt_file_returns_none(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{invalid json")
        assert RunState.load(path) is None

    def test_save_creates_valid_json(self, tmp_path):
        path = tmp_path / "state.json"
        state = RunState(build_version="v1", rollback_version="v0")
        state.save(path)

        data = json.loads(path.read_text())
        assert data["build_version"] == "v1"
        assert data["current_step"] == "not_started"


# ── clear ────────────────────────────────────────────────────────────────


class TestStateClear:
    def test_clear_deletes_file(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{}")
        RunState.clear(path)
        assert not path.exists()

    def test_clear_nonexistent_is_noop(self, tmp_path):
        path = tmp_path / "missing.json"
        RunState.clear(path)  # Should not raise
        assert not path.exists()


# ── mark_error ───────────────────────────────────────────────────────────


class TestMarkError:
    def test_mark_error_sets_fields(self, tmp_path, monkeypatch):
        path = tmp_path / "state.json"
        monkeypatch.setattr("create_release_ticket.state.STATE_FILE", path)
        state = RunState(
            build_version="v1",
            rollback_version="v0",
            current_step=RunStep.FETCHED_COMMITS,
        )
        state.save(path)
        state.mark_error("fetched_commits", "API timeout")

        loaded = RunState.load(path)
        assert loaded.error_step == "fetched_commits"
        assert loaded.error_message == "API timeout"


# ── get_created_resources ────────────────────────────────────────────────


class TestGetCreatedResources:
    def test_no_resources(self):
        state = RunState()
        assert state.get_created_resources() == []

    def test_all_resources(self):
        state = RunState(
            promote_ticket_key="ENG-1",
            deployment_ticket_key="DINT-2",
            jenkins_build_number=99,
            github_workflow_run_id=100001,
        )
        resources = state.get_created_resources()
        assert len(resources) == 4
        labels = [label for label, _ in resources]
        assert "Promote Ticket" in labels
        assert "Deployment Ticket" in labels
        assert "Jenkins Build" in labels
        assert "GitHub Workflow Run" in labels

    def test_partial_resources(self):
        state = RunState(promote_ticket_key="ENG-1")
        resources = state.get_created_resources()
        assert len(resources) == 1
        assert resources[0] == ("Promote Ticket", "ENG-1")


# ── create_new_run / get_resumable_state ────────────────────────────────


class TestRunLifecycle:
    def test_create_new_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr("create_release_ticket.state.STATE_FILE", tmp_path / "state.json")
        state = create_new_run("v-build", "v-rollback", ref="main")

        assert state.build_version == "v-build"
        assert state.rollback_version == "v-rollback"
        assert state.ref == "main"
        assert state.started_at != ""
        assert (tmp_path / "state.json").exists()

    def test_get_resumable_state_returns_in_progress(self, tmp_path, monkeypatch):
        monkeypatch.setattr("create_release_ticket.state.STATE_FILE", tmp_path / "state.json")
        state = RunState(
            build_version="v1",
            rollback_version="v0",
            current_step=RunStep.CREATED_PROMOTE_TICKET,
        )
        state.save(tmp_path / "state.json")

        resumable = get_resumable_state()
        assert resumable is not None
        assert resumable.current_step == RunStep.CREATED_PROMOTE_TICKET

    def test_get_resumable_state_returns_none_when_completed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("create_release_ticket.state.STATE_FILE", tmp_path / "state.json")
        state = RunState(current_step=RunStep.COMPLETED)
        state.save(tmp_path / "state.json")

        assert get_resumable_state() is None

    def test_get_resumable_state_returns_none_when_not_started(self, tmp_path, monkeypatch):
        monkeypatch.setattr("create_release_ticket.state.STATE_FILE", tmp_path / "state.json")
        state = RunState(current_step=RunStep.NOT_STARTED)
        state.save(tmp_path / "state.json")

        assert get_resumable_state() is None

    def test_get_resumable_state_returns_none_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("create_release_ticket.state.STATE_FILE", tmp_path / "nope.json")
        assert get_resumable_state() is None
