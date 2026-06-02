"""Pydantic schemas for the Release Ticket API."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class WSMessageType(str, Enum):
    """WebSocket message types for real-time updates."""

    STEP_START = "step_start"
    STEP_PROGRESS = "step_progress"
    STEP_COMPLETE = "step_complete"
    WORKFLOW_COMPLETE = "workflow_complete"
    WORKFLOW_ERROR = "workflow_error"


class StepInfo(BaseModel):
    """Information about a workflow step."""

    number: int = Field(..., description="Step number (1-7)")
    name: str = Field(..., description="Human-readable step name")
    key: str = Field(..., description="RunStep enum value")
    status: str = Field(default="pending", description="pending | in_progress | completed | error")
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class WSMessage(BaseModel):
    """WebSocket message structure."""

    type: WSMessageType
    release_id: str
    step: StepInfo | None = None
    progress: str | None = None  # Progress message for long-running operations
    error: str | None = None
    data: dict[str, Any] | None = None


class ReleaseCreate(BaseModel):
    """Request to create a new release."""

    build_version: str = Field(
        ...,
        description="Build version (e.g., queryservice-release-2025.12.2.0.18496)",
        pattern=r"^queryservice-release-\d{4}\.\d{1,2}\.\d{1,2}\.\d+\.\d+$"
    )
    rollback_version: str = Field(
        ...,
        description="Rollback version (e.g., queryservice-release-2025.12.1.0.18438)",
        pattern=r"^queryservice-release-\d{4}\.\d{1,2}\.\d{1,2}\.\d+\.\d+$"
    )
    ref: str = Field(default="develop", description="Git ref for GitHub workflow")
    previous_branch: str | None = Field(
        default=None,
        description="Override previous branch for commit comparison"
    )
    jira_ids: list[str] | None = Field(
        default=None,
        description="Comma-separated Jira IDs (override auto-detection)"
    )
    previous_deployment_ticket: str | None = Field(
        default=None,
        description="Previous deployment ticket key to relate to",
        pattern=r"^[A-Z]+-\d+$"
    )
    dry_run: bool = Field(default=False, description="Preview actions without executing")
    max_consecutive_poll_failures: int | None = Field(
        default=None,
        ge=1,
        description="Override max consecutive Jenkins poll failures before aborting (default: from config.yaml)"
    )

    # Start From Step: workflow always runs to completion from this step
    start_from_step: int = Field(default=1, description="Step to start from (1, 4, 5, or 6)")

    # Pre-existing artifacts (required depending on start_from_step)
    promote_ticket_key: str | None = Field(
        default=None,
        description="Existing promote ticket key (required if start_from_step >= 4)"
    )
    github_workflow_run_id: int | None = Field(
        default=None,
        description="Existing GitHub workflow run ID (required at step 5)"
    )
    jenkins_build_number: int | None = Field(
        default=None,
        description="Existing Jenkins build number (required at step 6)"
    )
    jenkins_job_url: str | None = Field(
        default=None,
        description="Existing Jenkins job URL (required at step 6)"
    )

    @model_validator(mode='after')
    def validate_start_from_artifacts(self):
        """Enforce required artifacts based on start_from_step.

        Only steps {1, 4, 5, 6} are valid start points.
        Steps 2, 3 are auto-derivable (no meaningful artifacts to provide).
        Step 7 is trivial and not useful as a start point.
        """
        step = self.start_from_step
        if step not in (1, 4, 5, 6):
            raise ValueError(f"start_from_step must be 1, 4, 5, or 6 (got {step})")
        if step >= 4 and not self.promote_ticket_key:
            raise ValueError("promote_ticket_key required when starting from step 4+")
        if step == 5 and not self.github_workflow_run_id:
            raise ValueError("github_workflow_run_id required when starting from step 5")
        if step == 6 and (not self.jenkins_build_number or not self.jenkins_job_url):
            raise ValueError("jenkins_build_number and jenkins_job_url required when starting from step 6")
        return self


class ReleaseResumeRequest(BaseModel):
    """Request to resume a release — always runs to completion."""

    github_workflow_run_id: int | None = Field(
        default=None,
        description="Use an existing GitHub workflow run ID instead of triggering new"
    )
    jenkins_build_number: int | None = Field(
        default=None,
        description="Use an existing Jenkins build number instead of triggering new"
    )
    jenkins_job_url: str | None = Field(
        default=None,
        description="Use an existing Jenkins job URL"
    )


class ReleaseListItem(BaseModel):
    """Summary of a release for list views."""

    id: str = Field(..., description="Unique release identifier")
    build_version: str
    rollback_version: str
    status: str = Field(..., description="not_started | in_progress | completed | error")
    current_step: str = Field(..., description="Current RunStep value")
    current_step_number: int = Field(..., description="Current step number (0-7)")
    started_at: datetime | None = None
    completed_at: datetime | None = None
    promote_ticket_key: str | None = None
    deployment_ticket_key: str | None = None
    error_message: str | None = None


class ReleaseResponse(BaseModel):
    """Full release details."""

    id: str
    build_version: str
    rollback_version: str
    ref: str
    status: str
    current_step: str
    current_step_number: int

    # Derived values
    current_branch: str | None = None
    previous_branch: str | None = None
    jira_ids: list[str] = Field(default_factory=list)

    # Created resources
    promote_ticket_key: str | None = None
    promote_ticket_id: str | None = None
    deployment_ticket_key: str | None = None
    deployment_ticket_id: str | None = None
    github_workflow_run_id: int | None = None
    jenkins_build_number: int | None = None
    jenkins_job_url: str | None = None
    previous_deployment_ticket_key: str | None = None

    # Timestamps
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Error info
    error_message: str | None = None
    error_step: str | None = None

    # Step details
    steps: list[StepInfo] = Field(default_factory=list)

    # Options
    dry_run: bool = False
    start_from_step: int = 1


class CleanupResponse(BaseModel):
    """Response from cleanup operation."""

    success: bool
    message: str
    cleaned_resources: list[str] = Field(default_factory=list)


class PurgeResponse(BaseModel):
    """Response from purge operation."""

    deleted_count: int
    deleted_ids: list[str] = Field(default_factory=list)
