"""State management for tracking run progress and created resources."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

STATE_FILE = Path(".create-release-ticket-state.json")


class RunStep(str, Enum):
    """Run steps."""

    NOT_STARTED = "not_started"
    PARSED_VERSION = "parsed_version"
    FETCHED_COMMITS = "fetched_commits"
    CREATED_PROMOTE_TICKET = "created_promote_ticket"
    TRIGGERED_GITHUB_WORKFLOW = "triggered_github_workflow"
    GITHUB_WORKFLOW_COMPLETED = "github_workflow_completed"
    TRIGGERED_JENKINS = "triggered_jenkins"
    JENKINS_COMPLETED = "jenkins_completed"
    CREATED_DEPLOYMENT_TICKET = "created_deployment_ticket"
    CLOSED_PROMOTE_TICKET = "closed_promote_ticket"
    COMPLETED = "completed"


@dataclass
class RunState:
    """State of a deployment run."""

    # Input parameters
    build_version: str = ""
    rollback_version: str = ""
    ref: str = "develop"

    # Derived values
    current_branch: str = ""
    previous_branch: str = ""
    jira_ids: list[str] = field(default_factory=list)

    # Current step
    current_step: RunStep = RunStep.NOT_STARTED

    # Created resources (for cleanup)
    promote_ticket_key: str | None = None
    promote_ticket_id: str | None = None
    deployment_ticket_key: str | None = None
    deployment_ticket_id: str | None = None
    previous_deployment_ticket_key: str | None = None
    deployment_ticket_relates_linked: bool = False
    github_workflow_run_id: int | None = None
    jenkins_build_number: int | None = None
    jenkins_job_url: str | None = None

    # Timestamps
    started_at: str = ""
    completed_at: str = ""

    # Error info
    error_message: str | None = None
    error_step: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary."""
        data = asdict(self)
        data["current_step"] = self.current_step.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunState:
        """Create state from dictionary."""
        if "current_step" in data:
            data["current_step"] = RunStep(data["current_step"])
        return cls(**data)

    def save(self, path: Path = STATE_FILE) -> None:
        """Save state to file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> RunState | None:
        """Load state from file."""
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load state file: {e}[/yellow]")
            return None

    @classmethod
    def clear(cls, path: Path = STATE_FILE) -> None:
        """Delete state file."""
        if path.exists():
            path.unlink()
            console.print("[green]✓ Cleared state file[/green]")

    def mark_step(self, step: RunStep) -> None:
        """Mark current step and save state."""
        self.current_step = step
        self.save()

    def mark_error(self, step: str, message: str) -> None:
        """Mark error and save state."""
        self.error_step = step
        self.error_message = message
        self.save()

    def get_created_resources(self) -> list[tuple[str, str]]:
        """Get list of created resources for display."""
        resources = []
        if self.promote_ticket_key:
            resources.append(("Promote Ticket", self.promote_ticket_key))
        if self.deployment_ticket_key:
            resources.append(("Deployment Ticket", self.deployment_ticket_key))
        if self.jenkins_build_number:
            resources.append(("Jenkins Build", str(self.jenkins_build_number)))
        if self.github_workflow_run_id:
            resources.append(("GitHub Workflow Run", str(self.github_workflow_run_id)))
        return resources

    def can_resume_from(self, step: RunStep) -> bool:
        """Check if we can resume from a specific step."""
        step_order = list(RunStep)
        current_idx = step_order.index(self.current_step)
        target_idx = step_order.index(step)
        return current_idx >= target_idx


def create_new_run(
    build_version: str,
    rollback_version: str,
    ref: str = "develop",
) -> RunState:
    """Create a new run state."""
    state = RunState(
        build_version=build_version,
        rollback_version=rollback_version,
        ref=ref,
        started_at=datetime.now().isoformat(),
    )
    state.save()
    return state


def get_resumable_state() -> RunState | None:
    """Get state that can be resumed, if any."""
    state = RunState.load()
    if state and state.current_step not in (RunStep.NOT_STARTED, RunStep.COMPLETED):
        return state
    return None
