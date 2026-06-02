"""Fake client implementations for testing resume/interrupt scenarios.

These fakes:
- Track all method calls for assertion
- Can simulate failures at specific points via `fail_on`
- Return realistic-looking fake data (ENG-FAKE-1, etc.)
- Are used by both E2E tests and dry-run mode
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class FakeClientError(Exception):
    """Simulated error for testing interrupt scenarios."""

    pass


@dataclass
class FakeJiraClient:
    """Fake Jira client that tracks calls and returns mock data.

    Usage:
        fake = FakeJiraClient()
        fake.fail_on = "transition_issue"  # Will raise on this method

        # After test:
        assert fake.call_count("create_issue") == 1
    """

    calls: list[tuple[str, Any]] = field(default_factory=list)
    fail_on: str | None = None
    _issue_counter: int = 1
    _issues: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, {"args": args, "kwargs": kwargs}))
        if self.fail_on == method:
            raise FakeClientError(f"Simulated failure in {method}")

    def call_count(self, method: str) -> int:
        """Count how many times a method was called."""
        return sum(1 for m, _ in self.calls if m == method)

    def get_calls(self, method: str) -> list[dict[str, Any]]:
        """Get all calls to a specific method."""
        return [data for m, data in self.calls if m == method]

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a fake issue and return its key/id."""
        self._record("create_issue", payload)
        key = f"ENG-FAKE-{self._issue_counter}"
        issue_id = str(10000 + self._issue_counter)
        self._issue_counter += 1

        issue = {
            "id": issue_id,
            "key": key,
            "self": f"https://jira.example.com/rest/api/3/issue/{issue_id}",
            "fields": {
                "status": {"name": "Open"},
                "summary": payload.get("fields", {}).get("summary", "Fake Issue"),
                "labels": [],
            },
        }
        self._issues[key] = issue
        return {"id": issue_id, "key": key, "self": issue["self"]}

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Get a fake issue by key."""
        self._record("get_issue", issue_key)
        if issue_key in self._issues:
            return self._issues[issue_key]
        # Return a default fake issue if not found
        return {
            "id": "99999",
            "key": issue_key,
            "fields": {
                "status": {"name": "Open"},
                "resolution": None,
                "labels": [],
            },
        }

    def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        """Return fake available transitions."""
        self._record("get_transitions", issue_key)
        return [
            {"id": "11", "name": "Start Progress"},
            {"id": "21", "name": "Resolve Issue"},
            {"id": "31", "name": "Close"},
            {"id": "41", "name": "Done"},
        ]

    def transition_issue(
        self,
        issue_key: str,
        transition_id: str | None = None,
        transition_name: str = "Done",
        resolution: str = "Done",
        fields: dict[str, Any] | None = None,
    ) -> bool:
        """Record transition and update fake issue status."""
        self._record(
            "transition_issue",
            issue_key,
            transition_id=transition_id,
            transition_name=transition_name,
            resolution=resolution,
            fields=fields,
        )
        if issue_key in self._issues:
            self._issues[issue_key]["fields"]["status"]["name"] = transition_name
            if resolution:
                self._issues[issue_key]["fields"]["resolution"] = {"name": resolution}
        return True

    def update_issue_fields(self, issue_key: str, fields: dict[str, Any]) -> bool:
        """Record field update."""
        self._record("update_issue_fields", issue_key, fields=fields)
        if issue_key in self._issues:
            self._issues[issue_key]["fields"].update(fields)
        return True

    def prepare_resolve_fixed(
        self,
        issue_key: str,
        *,
        fix_version_label: str | None,
        sub_component_label: str | None = None,
        add_no_code_label: bool = True,
    ) -> dict[str, Any]:
        """Return fake fields for resolve transition."""
        self._record(
            "prepare_resolve_fixed",
            issue_key,
            fix_version_label=fix_version_label,
            sub_component_label=sub_component_label,
            add_no_code_label=add_no_code_label,
        )
        fields: dict[str, Any] = {
            "labels": ["no-code"] if add_no_code_label else [],
            "customfield_15000": [{"id": "21484"}],
            "customfield_12502": {"id": "10503"},
            "customfield_12503": {"type": "doc", "version": 1, "content": []},
        }
        if fix_version_label:
            fields["fixVersions"] = [{"name": fix_version_label}]
        return fields

    def create_issue_link(
        self,
        *,
        inward_issue_key: str,
        outward_issue_key: str,
        link_type: str = "Relates",
    ) -> bool:
        """Record issue link creation."""
        self._record(
            "create_issue_link",
            inward_issue_key=inward_issue_key,
            outward_issue_key=outward_issue_key,
            link_type=link_type,
        )
        return True

    def delete_issue(self, issue_key: str) -> bool:
        """Record issue deletion."""
        self._record("delete_issue", issue_key)
        self._issues.pop(issue_key, None)
        return True

    def add_comment(self, issue_key: str, comment: str) -> bool:
        """Record comment addition."""
        self._record("add_comment", issue_key, comment=comment)
        return True

    def validate_credentials(self) -> bool:
        """Always return True for fake."""
        self._record("validate_credentials")
        return True


@dataclass
class FakeGitHubClient:
    """Fake GitHub client that tracks calls and returns mock data.

    Usage:
        fake = FakeGitHubClient()
        fake.fail_on = "trigger_and_wait_workflow"  # Simulate GH failure
        fake.mock_commits = [{"sha": "abc", "commit": {"message": "ENG-123 fix"}}]
    """

    calls: list[tuple[str, Any]] = field(default_factory=list)
    fail_on: str | None = None
    mock_commits: list[dict[str, Any]] = field(default_factory=list)
    mock_branches: set[str] = field(default_factory=lambda: {"develop", "main"})
    _workflow_counter: int = 1

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, {"args": args, "kwargs": kwargs}))
        if self.fail_on == method:
            raise FakeClientError(f"Simulated failure in {method}")

    def call_count(self, method: str) -> int:
        return sum(1 for m, _ in self.calls if m == method)

    def get_calls(self, method: str) -> list[dict[str, Any]]:
        return [data for m, data in self.calls if m == method]

    def validate_credentials(self) -> bool:
        self._record("validate_credentials")
        return True

    def check_branch_exists(self, branch: str) -> bool:
        """Check if branch exists (add to mock_branches to make it exist)."""
        self._record("check_branch_exists", branch)
        # Auto-add release branches to simulate they exist
        if branch.startswith("queryservice-release-"):
            return True
        return branch in self.mock_branches

    def compare_commits(self, base: str, head: str) -> list[dict[str, Any]]:
        """Return mock commits or default fake commits."""
        self._record("compare_commits", base, head)
        if self.mock_commits:
            return self.mock_commits
        # Default: return commits with Jira IDs
        return [
            {"sha": "abc123", "commit": {"message": "ENG-11111 Add feature X"}},
            {"sha": "def456", "commit": {"message": "DINT-22222 Fix bug Y"}},
            {"sha": "ghi789", "commit": {"message": "EP-33333 Update Z"}},
        ]

    def trigger_workflow(
        self,
        workflow_file: str,
        ref: str,
        inputs: dict[str, str],
    ) -> bool:
        """Record workflow trigger."""
        self._record("trigger_workflow", workflow_file, ref, inputs=inputs)
        return True

    def get_latest_workflow_run(
        self,
        workflow_file: str,
        wait_seconds: int = 5,
        triggered_after: str | None = None,
        max_attempts: int = 12,
    ) -> dict[str, Any] | None:
        """Return fake workflow run."""
        self._record(
            "get_latest_workflow_run",
            workflow_file,
            wait_seconds=wait_seconds,
            triggered_after=triggered_after,
        )
        run_id = 100000 + self._workflow_counter
        return {
            "id": run_id,
            "status": "queued",
            "conclusion": None,
            "html_url": f"https://github.com/example/repo/actions/runs/{run_id}",
            "created_at": "2026-01-01T00:00:00Z",
        }

    def get_workflow_run(self, run_id: int) -> dict[str, Any]:
        """Return fake workflow run data."""
        self._record("get_workflow_run", run_id)
        return {
            "id": run_id,
            "status": "completed",
            "conclusion": "success",
            "html_url": f"https://github.com/example/repo/actions/runs/{run_id}",
        }

    def poll_workflow_run(
        self,
        run_id: int,
        poll_interval: int = 30,
        timeout_minutes: int = 20,
    ) -> dict[str, Any]:
        """Return completed workflow run."""
        self._record("poll_workflow_run", run_id, poll_interval=poll_interval)
        return {
            "id": run_id,
            "status": "completed",
            "conclusion": "success",
        }

    def trigger_and_wait_workflow(
        self,
        ref: str,
        inputs: dict[str, str],
        poll_interval: int = 30,
        timeout_minutes: int = 20,
    ) -> dict[str, Any]:
        """Trigger and 'wait' for workflow (instant in fake)."""
        self._record(
            "trigger_and_wait_workflow",
            ref,
            inputs=inputs,
            poll_interval=poll_interval,
        )
        run_id = 100000 + self._workflow_counter
        self._workflow_counter += 1
        return {
            "id": run_id,
            "status": "completed",
            "conclusion": "success",
            "html_url": f"https://github.com/example/repo/actions/runs/{run_id}",
        }


@dataclass
class FakeJenkinsClient:
    """Fake Jenkins client that tracks calls and returns mock data.

    Usage:
        fake = FakeJenkinsClient()
        fake.fail_on = "poll_build"  # Simulate Jenkins failure
    """

    calls: list[tuple[str, Any]] = field(default_factory=list)
    fail_on: str | None = None
    _build_counter: int = 1
    _builds: dict[int, dict[str, Any]] = field(default_factory=dict)

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((method, {"args": args, "kwargs": kwargs}))
        if self.fail_on == method:
            raise FakeClientError(f"Simulated failure in {method}")

    def call_count(self, method: str) -> int:
        return sum(1 for m, _ in self.calls if m == method)

    def get_calls(self, method: str) -> list[dict[str, Any]]:
        return [data for m, data in self.calls if m == method]

    def validate_credentials(self) -> bool:
        self._record("validate_credentials")
        return True

    def trigger_build(
        self,
        release_version: str,
        ticket: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Return fake queue URL."""
        self._record(
            "trigger_build",
            release_version,
            ticket,
            extra_params=extra_params,
        )
        queue_id = 50000 + self._build_counter
        return {
            "queue_url": f"https://jenkins.example.com/queue/item/{queue_id}/",
            "params": {"RELEASE": release_version, "TICKET": ticket},
        }

    def get_queue_item(self, queue_url: str) -> dict[str, Any]:
        """Return fake queue item with executable."""
        self._record("get_queue_item", queue_url)
        build_number = self._build_counter
        return {
            "executable": {
                "number": build_number,
                "url": f"https://jenkins.example.com/job/fake-job/{build_number}/",
            }
        }

    def get_build(self, build_number: int) -> dict[str, Any]:
        """Return fake build data."""
        self._record("get_build", build_number)
        if build_number in self._builds:
            return self._builds[build_number]
        return {
            "number": build_number,
            "building": False,
            "result": "SUCCESS",
            "url": f"https://jenkins.example.com/job/fake-job/{build_number}/",
            "duration": 120000,
            "estimatedDuration": 120000,
        }

    def cancel_build(self, build_number: int) -> bool:
        """Record build cancellation."""
        self._record("cancel_build", build_number)
        return True

    def wait_for_build_start(
        self,
        queue_url: str,
        poll_interval: int | None = None,
        timeout_minutes: int = 10,
        max_consecutive_poll_failures: int | None = None,
    ) -> dict[str, Any]:
        """Return immediately with fake build info."""
        self._record("wait_for_build_start", queue_url, poll_interval=poll_interval)
        build_number = self._build_counter
        return {
            "build_number": build_number,
            "job_url": f"https://jenkins.example.com/job/fake-job/{build_number}/",
        }

    def poll_build(
        self,
        queue_url: str,
        poll_interval: int | None = None,
        timeout_minutes: int | None = None,
    ) -> dict[str, Any]:
        """Return completed build immediately."""
        self._record("poll_build", queue_url, poll_interval=poll_interval)
        build_number = self._build_counter
        self._build_counter += 1
        return {
            "build_number": build_number,
            "job_url": f"https://jenkins.example.com/job/fake-job/{build_number}/",
            "result": "SUCCESS",
        }

    def poll_build_by_number(
        self,
        build_number: int,
        poll_interval: int | None = None,
        timeout_minutes: int | None = None,
        max_consecutive_poll_failures: int | None = None,
    ) -> dict[str, Any]:
        """Return completed build for given number."""
        self._record("poll_build_by_number", build_number, poll_interval=poll_interval)
        return {
            "build_number": build_number,
            "job_url": f"https://jenkins.example.com/job/fake-job/{build_number}/",
            "result": "SUCCESS",
        }

    def trigger_and_wait(
        self,
        release_version: str,
        ticket: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Trigger and 'wait' (instant in fake)."""
        self._record(
            "trigger_and_wait",
            release_version,
            ticket,
            extra_params=extra_params,
        )
        build_number = self._build_counter
        self._build_counter += 1
        return {
            "build_number": build_number,
            "job_url": f"https://jenkins.example.com/job/fake-job/{build_number}/",
            "result": "SUCCESS",
        }
