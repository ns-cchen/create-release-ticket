"""Workflow service that wraps the existing CLI workflow for the web UI."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from create_release_ticket.clients import GitHubClient, JenkinsClient, JiraClient
from create_release_ticket.config import get_app_config
from create_release_ticket.state import RunState, RunStep
from create_release_ticket.templates import (
    build_deployment_ticket_payload,
    build_promote_ticket_payload,
)
from create_release_ticket.utils import (
    derive_fix_version_label,
    extract_jira_ids,
    format_jira_url,
    parse_build_version,
)

from ..models.schemas import (
    ReleaseCreate,
    ReleaseListItem,
    ReleaseResponse,
    ReleaseResumeRequest,
    StepInfo,
)
from .websocket_manager import ws_manager

if TYPE_CHECKING:
    from tests.fakes.clients import FakeGitHubClient, FakeJenkinsClient, FakeJiraClient


# Protocol for type hints (duck typing)
class JiraClientProtocol(Protocol):
    """Protocol for Jira client (real or fake)."""

    def create_issue(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def get_issue(self, issue_key: str) -> dict[str, Any]: ...
    def transition_issue(
        self,
        issue_key: str,
        transition_id: str | None = None,
        transition_name: str = "Done",
        resolution: str = "Done",
        fields: dict[str, Any] | None = None,
    ) -> bool: ...
    def prepare_resolve_fixed(
        self,
        issue_key: str,
        *,
        fix_version_label: str | None,
        sub_component_label: str | None = None,
        add_no_code_label: bool = True,
    ) -> dict[str, Any]: ...
    def create_issue_link(
        self,
        *,
        inward_issue_key: str,
        outward_issue_key: str,
        link_type: str = "Relates",
    ) -> bool: ...


class GitHubClientProtocol(Protocol):
    """Protocol for GitHub client (real or fake)."""

    def check_branch_exists(self, branch: str) -> bool: ...
    def compare_commits(self, base: str, head: str) -> list[dict[str, Any]]: ...
    def trigger_workflow(
        self,
        workflow_file: str,
        ref: str,
        inputs: dict[str, str],
    ) -> bool: ...
    def get_latest_workflow_run(
        self,
        workflow_file: str,
        wait_seconds: int = 5,
        triggered_after: str | None = None,
        max_attempts: int = 12,
    ) -> dict[str, Any] | None: ...
    def poll_workflow_run(
        self,
        run_id: int,
        poll_interval: int = 30,
        timeout_minutes: int = 20,
    ) -> dict[str, Any]: ...
    def trigger_and_wait_workflow(
        self,
        ref: str,
        inputs: dict[str, str],
        poll_interval: int = 30,
        timeout_minutes: int = 20,
    ) -> dict[str, Any]: ...


class JenkinsClientProtocol(Protocol):
    """Protocol for Jenkins client (real or fake)."""

    def trigger_build(
        self,
        release_version: str,
        ticket: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...
    def get_queue_item(self, queue_url: str) -> dict[str, Any]: ...
    def wait_for_build_start(
        self,
        queue_url: str,
        poll_interval: int | None = None,
        timeout_minutes: int = 10,
        max_consecutive_poll_failures: int | None = None,
    ) -> dict[str, Any]: ...
    def poll_build_by_number(
        self,
        build_number: int,
        poll_interval: int | None = None,
        timeout_minutes: int | None = None,
        max_consecutive_poll_failures: int | None = None,
    ) -> dict[str, Any]: ...
    def trigger_and_wait(
        self,
        release_version: str,
        ticket: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...
    def get_build(self, build_number: int) -> dict[str, Any]: ...
    def cancel_build(self, build_number: int) -> bool: ...

logger = logging.getLogger(__name__)

# Storage directory for release states
RELEASES_DIR = Path.home() / ".create-release-ticket" / "releases"


# Step definitions with human-readable names
STEPS = [
    (1, "Parse Version", RunStep.PARSED_VERSION),
    (2, "Fetch Commits", RunStep.FETCHED_COMMITS),
    (3, "Create Promote Ticket", RunStep.CREATED_PROMOTE_TICKET),
    (4, "GitHub Workflow", RunStep.GITHUB_WORKFLOW_COMPLETED),
    (5, "Jenkins Build", RunStep.JENKINS_COMPLETED),
    (6, "Create Deployment Ticket", RunStep.CREATED_DEPLOYMENT_TICKET),
    (7, "Close Promote Ticket", RunStep.CLOSED_PROMOTE_TICKET),
]

# Map start_from_step to the RunStep that should be "already completed"
# so the workflow begins at the right place.
# Only steps {1, 4, 5, 6} are valid start points.
STEP_TO_RUNSTEP = {
    1: RunStep.NOT_STARTED,
    4: RunStep.CREATED_PROMOTE_TICKET,
    5: RunStep.GITHUB_WORKFLOW_COMPLETED,
    6: RunStep.JENKINS_COMPLETED,
}


def _step_number_from_key(key: str) -> int:
    """Get step number from RunStep key.

    Maps intermediate states (triggered_*) to their parent step number.
    Returns 8 for 'completed' state (higher than all steps).
    """
    # Map intermediate states to their parent step
    intermediate_map = {
        "triggered_github_workflow": 4,
        "triggered_jenkins": 5,
    }
    if key in intermediate_map:
        return intermediate_map[key]

    # 'completed' state means all steps are done, return higher than any step
    if key == "completed":
        return 8

    for num, _, step in STEPS:
        if step.value == key:
            return num
    return 0


def _step_name_from_key(key: str) -> str:
    """Get step name from RunStep key."""
    for _, name, step in STEPS:
        if step.value == key:
            return name
    return key


def _get_fake_clients() -> tuple[
    FakeJiraClient, FakeGitHubClient, FakeJenkinsClient
]:
    """Import and instantiate fake clients for dry-run mode.

    Fakes are imported lazily to avoid test dependencies in production.
    """
    from tests.fakes.clients import FakeGitHubClient, FakeJenkinsClient, FakeJiraClient

    return FakeJiraClient(), FakeGitHubClient(), FakeJenkinsClient()


class WorkflowService:
    """Service for managing release workflows."""

    def __init__(self):
        RELEASES_DIR.mkdir(parents=True, exist_ok=True)
        self._skip_events: dict[str, asyncio.Event] = {}

    def skip_jenkins(self, release_id: str) -> dict[str, Any]:
        """Signal the workflow to skip Jenkins polling for a release.

        Returns success/failure dict.
        """
        state = self._load_release(release_id)
        if not state:
            return {"success": False, "message": "Release not found"}

        # Only allow skipping during step 5 polling (build already triggered)
        raw = self._load_raw_data(release_id) or {}
        if raw.get("current_step") not in ("triggered_jenkins",):
            return {"success": False, "message": "Jenkins build is not currently being polled"}

        if not state.jenkins_build_number:
            return {"success": False, "message": "Jenkins build has not started yet"}

        event = self._skip_events.get(release_id)
        if event is None:
            return {"success": False, "message": "No active polling to skip"}

        event.set()
        return {"success": True, "message": "Jenkins polling skipped — proceeding to next step"}

    def _get_release_path(self, release_id: str) -> Path:
        """Get the path to a release state file."""
        return RELEASES_DIR / f"{release_id}.json"

    def _load_raw_data(self, release_id: str) -> dict | None:
        """Load raw JSON data for a release (without RunState parsing)."""
        path = self._get_release_path(release_id)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    def _load_release(self, release_id: str) -> RunState | None:
        """Load a release state from file."""
        path = self._get_release_path(release_id)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            # Filter out extra keys not part of RunState
            extra_keys = {"_id", "dry_run", "start_from_step", "stop_after", "paused"}
            state_data = {k: v for k, v in data.items() if k not in extra_keys}
            return RunState.from_dict(state_data)
        except Exception as e:
            logger.error(f"Failed to load release {release_id}: {e}")
            return None

    def _save_release(self, release_id: str, state: RunState, extra: dict | None = None) -> None:
        """Save a release state to file."""
        path = self._get_release_path(release_id)
        data = state.to_dict()
        data["_id"] = release_id
        if extra:
            data.update(extra)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def _state_to_response(
        self,
        release_id: str,
        state: RunState,
        extra: dict | None = None
    ) -> ReleaseResponse:
        """Convert RunState to ReleaseResponse."""
        extra = extra or {}

        # Determine status (no more "paused" — treat legacy paused as in_progress)
        if state.error_message:
            status = "error"
        elif state.current_step == RunStep.COMPLETED:
            status = "completed"
        elif state.current_step == RunStep.NOT_STARTED:
            status = "not_started"
        else:
            status = "in_progress"

        current_step_number = _step_number_from_key(state.current_step.value)

        # Build step info list with results for completed steps
        config = get_app_config()
        steps = []
        for num, name, step in STEPS:
            step_status = "pending"
            if _step_number_from_key(state.current_step.value) > num:
                step_status = "completed"
            elif _step_number_from_key(state.current_step.value) == num:
                # The STEPS tuple stores the "completed" RunStep for each step.
                # If current_step matches it exactly, the step is done (e.g.
                # GITHUB_WORKFLOW_COMPLETED = step 4 done). Otherwise it's an
                # intermediate state (e.g. TRIGGERED_GITHUB_WORKFLOW = step 4
                # still running).
                if state.current_step == step:
                    step_status = "completed"
                elif state.error_message:
                    step_status = "error"
                else:
                    step_status = "in_progress"

            # Populate result from state for completed steps (so links persist after refresh)
            step_result = None
            if step_status == "completed":
                if num == 3 and state.promote_ticket_key:
                    step_result = {
                        "promote_ticket_key": state.promote_ticket_key,
                        "url": format_jira_url(state.promote_ticket_key),
                    }
                elif num == 4 and state.github_workflow_run_id:
                    step_result = {
                        "github_workflow_run_id": state.github_workflow_run_id,
                        "url": f"https://github.com/{config.github.owner}/{config.github.repo}/actions/runs/{state.github_workflow_run_id}",
                    }
                elif num == 5 and state.jenkins_build_number:
                    step_result = {
                        "jenkins_build_number": state.jenkins_build_number,
                        "jenkins_job_url": state.jenkins_job_url,
                    }
                elif num == 6 and state.deployment_ticket_key:
                    step_result = {
                        "deployment_ticket_key": state.deployment_ticket_key,
                        "url": format_jira_url(state.deployment_ticket_key),
                    }

            steps.append(StepInfo(
                number=num,
                name=name,
                key=step.value,
                status=step_status,
                result=step_result,
            ))

        # Read start_from_step from extra, with backward compat for old stop_after
        start_from_step = extra.get("start_from_step", 1)

        return ReleaseResponse(
            id=release_id,
            build_version=state.build_version,
            rollback_version=state.rollback_version,
            ref=state.ref,
            status=status,
            current_step=state.current_step.value,
            current_step_number=current_step_number,
            current_branch=state.current_branch or None,
            previous_branch=state.previous_branch or None,
            jira_ids=state.jira_ids,
            promote_ticket_key=state.promote_ticket_key,
            promote_ticket_id=state.promote_ticket_id,
            deployment_ticket_key=state.deployment_ticket_key,
            deployment_ticket_id=state.deployment_ticket_id,
            github_workflow_run_id=state.github_workflow_run_id,
            jenkins_build_number=state.jenkins_build_number,
            jenkins_job_url=state.jenkins_job_url,
            previous_deployment_ticket_key=state.previous_deployment_ticket_key,
            started_at=datetime.fromisoformat(state.started_at) if state.started_at else None,
            completed_at=datetime.fromisoformat(state.completed_at) if state.completed_at else None,
            error_message=state.error_message,
            error_step=state.error_step,
            steps=steps,
            dry_run=extra.get("dry_run", False),
            start_from_step=start_from_step,
        )

    def list_releases(self) -> list[ReleaseListItem]:
        """List all releases."""
        releases = []
        extra_keys = {"_id", "dry_run", "start_from_step", "stop_after", "paused"}
        for path in RELEASES_DIR.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                state_data = {k: v for k, v in data.items() if k not in extra_keys}
                state = RunState.from_dict(state_data)
                release_id = data.get("_id", path.stem)

                # Determine status (no more "paused" — treat legacy paused as in_progress)
                if state.error_message:
                    status = "error"
                elif state.current_step == RunStep.COMPLETED:
                    status = "completed"
                elif state.current_step == RunStep.NOT_STARTED:
                    status = "not_started"
                else:
                    status = "in_progress"

                releases.append(ReleaseListItem(
                    id=release_id,
                    build_version=state.build_version,
                    rollback_version=state.rollback_version,
                    status=status,
                    current_step=state.current_step.value,
                    current_step_number=_step_number_from_key(state.current_step.value),
                    started_at=datetime.fromisoformat(state.started_at) if state.started_at else None,
                    completed_at=datetime.fromisoformat(state.completed_at) if state.completed_at else None,
                    promote_ticket_key=state.promote_ticket_key,
                    deployment_ticket_key=state.deployment_ticket_key,
                    error_message=state.error_message,
                ))
            except Exception as e:
                logger.error(f"Failed to load release from {path}: {e}")
                continue

        # Sort by started_at descending (newest first)
        releases.sort(key=lambda r: r.started_at or datetime.min, reverse=True)
        return releases

    def get_release(self, release_id: str) -> ReleaseResponse | None:
        """Get a release by ID."""
        path = self._get_release_path(release_id)
        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)
        # Separate extra fields from RunState fields
        extra_keys = {"_id", "dry_run", "start_from_step", "stop_after", "paused"}
        extra = {k: v for k, v in data.items() if k in extra_keys}
        state_data = {k: v for k, v in data.items() if k not in extra_keys}
        state = RunState.from_dict(state_data)
        return self._state_to_response(release_id, state, extra)

    async def create_release(self, request: ReleaseCreate) -> ReleaseResponse:
        """Create and start a new release workflow."""
        release_id = str(uuid.uuid4())[:8]

        # Create initial state
        state = RunState(
            build_version=request.build_version,
            rollback_version=request.rollback_version,
            ref=request.ref,
            started_at=datetime.now().isoformat(),
        )

        if request.previous_deployment_ticket:
            state.previous_deployment_ticket_key = request.previous_deployment_ticket

        if request.jira_ids:
            state.jira_ids = request.jira_ids

        # Pre-populate state from artifacts when start_from_step > 1
        if request.start_from_step > 1:
            # Parse version immediately to populate branches
            parsed = parse_build_version(state.build_version)
            state.current_branch = parsed.current_branch
            state.previous_branch = request.previous_branch or parsed.previous_branch

            # Pre-populate provided artifacts
            if request.promote_ticket_key:
                state.promote_ticket_key = request.promote_ticket_key
            if request.github_workflow_run_id:
                state.github_workflow_run_id = request.github_workflow_run_id
            if request.jenkins_build_number:
                state.jenkins_build_number = request.jenkins_build_number
            if request.jenkins_job_url:
                state.jenkins_job_url = request.jenkins_job_url
            # Set current_step based on start_from_step
            state.current_step = STEP_TO_RUNSTEP[request.start_from_step]

        # Save initial state
        extra = {
            "dry_run": request.dry_run,
            "start_from_step": request.start_from_step,
            "previous_branch_override": request.previous_branch,
        }
        self._save_release(release_id, state, extra)

        # Start workflow in background
        asyncio.create_task(self._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=request.dry_run,
            previous_branch_override=request.previous_branch,
            jira_ids_override=request.jira_ids,
            max_consecutive_poll_failures=request.max_consecutive_poll_failures,
        ))

        return self._state_to_response(release_id, state, extra)

    async def resume_release(
        self,
        release_id: str,
        request: ReleaseResumeRequest
    ) -> ReleaseResponse | None:
        """Resume a release — always runs to completion."""
        path = self._get_release_path(release_id)
        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)
        # Filter out extra keys not part of RunState
        extra_keys = {"_id", "dry_run", "start_from_step", "stop_after", "paused"}
        state_data = {k: v for k, v in data.items() if k not in extra_keys}
        state = RunState.from_dict(state_data)

        # Apply GitHub override if provided
        # Set to TRIGGERED_GITHUB_WORKFLOW so the workflow will poll the run instead of triggering
        if request.github_workflow_run_id is not None:
            state.github_workflow_run_id = request.github_workflow_run_id
            state.current_step = RunStep.TRIGGERED_GITHUB_WORKFLOW
            state.error_message = None
            state.error_step = None

        # Apply Jenkins override if provided
        # Set to TRIGGERED_JENKINS so the workflow will poll the build instead of skipping
        if request.jenkins_build_number is not None and request.jenkins_job_url is not None:
            state.jenkins_build_number = request.jenkins_build_number
            state.jenkins_job_url = request.jenkins_job_url
            state.current_step = RunStep.TRIGGERED_JENKINS
            # Clear error state since we're recovering
            state.error_message = None
            state.error_step = None

        # Clear legacy paused flag if present
        data.pop("paused", None)
        # Clear legacy stop_after if present
        data.pop("stop_after", None)

        self._save_release(release_id, state, data)

        # Resume workflow in background — always runs to completion
        asyncio.create_task(self._run_workflow(
            release_id=release_id,
            state=state,
            dry_run=data.get("dry_run", False),
            previous_branch_override=data.get("previous_branch_override"),
            jira_ids_override=state.jira_ids if state.jira_ids else None,
        ))

        return self._state_to_response(release_id, state, data)

    async def cleanup_release(self, release_id: str) -> dict[str, Any]:
        """Clean up resources from a failed release."""
        state = self._load_release(release_id)
        if not state:
            return {"success": False, "message": "Release not found"}

        cleaned = []

        try:
            jira = JiraClient()

            # Close promote ticket if it exists and isn't closed
            if state.promote_ticket_key:
                try:
                    issue = jira.get_issue(state.promote_ticket_key)
                    status = issue["fields"]["status"]["name"]
                    if status not in ("Resolved", "Closed", "Done"):
                        jira.transition_issue(
                            state.promote_ticket_key,
                            transition_name="Resolve Issue",
                            resolution="Won't Fix",
                        )
                        cleaned.append(f"Closed promote ticket {state.promote_ticket_key}")
                except Exception as e:
                    logger.warning(f"Could not close promote ticket: {e}")

            # Cancel Jenkins build if running
            if state.jenkins_build_number:
                try:
                    jenkins = JenkinsClient()
                    build = jenkins.get_build(state.jenkins_build_number)
                    if build.get("building"):
                        jenkins.cancel_build(state.jenkins_build_number)
                        cleaned.append(f"Cancelled Jenkins build #{state.jenkins_build_number}")
                except Exception as e:
                    logger.warning(f"Could not cancel Jenkins build: {e}")

            # Mark release as cleaned up
            state.error_message = "Cleaned up"
            self._save_release(release_id, state, {"cleaned": True})

            return {
                "success": True,
                "message": "Cleanup completed",
                "cleaned_resources": cleaned,
            }

        except Exception as e:
            logger.exception("Cleanup failed")
            return {"success": False, "message": str(e)}

    async def _run_workflow(
        self,
        release_id: str,
        state: RunState,
        dry_run: bool = False,
        previous_branch_override: str | None = None,
        jira_ids_override: list[str] | None = None,
        max_consecutive_poll_failures: int | None = None,
        # DI for testing - if not provided, will be created based on dry_run flag
        jira_client: JiraClientProtocol | None = None,
        github_client: GitHubClientProtocol | None = None,
        jenkins_client: JenkinsClientProtocol | None = None,
    ) -> None:
        """Execute the deployment workflow with WebSocket updates.

        The workflow always runs to completion from the current step.

        Args:
            release_id: Unique release identifier
            state: Current workflow state
            dry_run: If True, use fake clients instead of real APIs
            previous_branch_override: Override auto-detected previous branch
            jira_ids_override: Override auto-detected Jira IDs
            jira_client: Optional injected Jira client (for testing)
            github_client: Optional injected GitHub client (for testing)
            jenkins_client: Optional injected Jenkins client (for testing)
        """
        config = get_app_config()

        # Initialize clients - use fakes for dry_run, real clients otherwise
        if dry_run and not (jira_client or github_client or jenkins_client):
            # No clients injected, create fakes for dry-run
            fake_jira, fake_github, fake_jenkins = _get_fake_clients()
            jira = jira_client or fake_jira
            github = github_client or fake_github
            jenkins = jenkins_client or fake_jenkins
        else:
            # Use injected clients or create real ones lazily
            jira = jira_client
            github = github_client
            jenkins = jenkins_client

        def save_state():
            self._save_release(release_id, state, {
                "dry_run": dry_run,
            })

        try:
            # Step 1: Parse version
            if not state.can_resume_from(RunStep.PARSED_VERSION) or not state.current_branch:
                await ws_manager.send_step_start(release_id, 1, "Parse Version", "parsed_version")

                parsed = parse_build_version(state.build_version)
                state.current_branch = parsed.current_branch
                state.previous_branch = previous_branch_override or parsed.previous_branch

                state.current_step = RunStep.PARSED_VERSION
                save_state()

                await ws_manager.send_step_complete(
                    release_id, 1, "Parse Version", "parsed_version",
                    {"current_branch": state.current_branch, "previous_branch": state.previous_branch}
                )

            # Step 2: Fetch commits
            # Re-run if we haven't passed this step, or if jira_ids is empty
            # but only when we're still before step 3 (start_from_step may skip this)
            if not state.can_resume_from(RunStep.FETCHED_COMMITS) or (
                not state.jira_ids and not state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET)
            ):
                await ws_manager.send_step_start(release_id, 2, "Fetch Commits", "fetched_commits")

                if jira_ids_override:
                    state.jira_ids = jira_ids_override
                else:
                    # Use injected/fake client or create real one
                    gh = github or GitHubClient()

                    # Check branches exist
                    await ws_manager.send_step_progress(release_id, 2, "Checking branch existence...")
                    if not gh.check_branch_exists(state.current_branch):
                        raise Exception(f"Branch '{state.current_branch}' does not exist.")
                    if not gh.check_branch_exists(state.previous_branch):
                        raise Exception(f"Branch '{state.previous_branch}' does not exist.")

                    await ws_manager.send_step_progress(release_id, 2, "Fetching commits...")
                    commits = gh.compare_commits(state.previous_branch, state.current_branch)
                    state.jira_ids = extract_jira_ids(commits)

                    if not state.jira_ids:
                        raise Exception(
                            f"No Jira IDs found in commits between {state.previous_branch} and {state.current_branch}."
                        )

                state.current_step = RunStep.FETCHED_COMMITS
                save_state()

                await ws_manager.send_step_complete(
                    release_id, 2, "Fetch Commits", "fetched_commits",
                    {"jira_ids": state.jira_ids}
                )

            # Step 3: Create promote ticket
            if not state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET) or not state.promote_ticket_key:
                await ws_manager.send_step_start(release_id, 3, "Create Promote Ticket", "created_promote_ticket")

                promote_payload = build_promote_ticket_payload(state.build_version)

                # Use injected/fake client or create real one
                jira_cli = jira or JiraClient()
                result = jira_cli.create_issue(promote_payload)
                state.promote_ticket_key = result["key"]
                state.promote_ticket_id = result["id"]
                save_state()  # Save ticket key immediately to prevent duplicates on resume
                logger.info(f"Created promote ticket: {state.promote_ticket_key}")

                state.current_step = RunStep.CREATED_PROMOTE_TICKET
                save_state()

                await ws_manager.send_step_complete(
                    release_id, 3, "Create Promote Ticket", "created_promote_ticket",
                    {"promote_ticket_key": state.promote_ticket_key, "url": format_jira_url(state.promote_ticket_key)}
                )

            # Step 4: GitHub workflow (split into trigger + poll to avoid duplicate triggers on resume)
            if not state.can_resume_from(RunStep.GITHUB_WORKFLOW_COMPLETED):
                # Use injected/fake client or create real one
                gh = github or GitHubClient()
                loop = asyncio.get_event_loop()

                # Step 4a: Trigger workflow (skip if already triggered)
                if not state.github_workflow_run_id:
                    await ws_manager.send_step_start(release_id, 4, "GitHub Workflow", "github_workflow_completed")
                    await ws_manager.send_step_progress(release_id, 4, "Triggering workflow...")

                    workflow_inputs = {
                        "release-ticket": state.promote_ticket_key,
                        "release-version": state.build_version,
                        "destinations": config.github.destinations,
                        "manifest-service": config.github.manifest_service,
                        "notify-emails": config.github.notify_emails,
                    }

                    from datetime import timezone
                    triggered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                    # Trigger workflow (non-blocking)
                    await loop.run_in_executor(
                        None,
                        lambda: gh.trigger_workflow(
                            config.github.workflow_file,
                            state.ref,
                            workflow_inputs,
                        )
                    )

                    # Get the workflow run ID
                    run = await loop.run_in_executor(
                        None,
                        lambda: gh.get_latest_workflow_run(
                            config.github.workflow_file,
                            wait_seconds=5,
                            triggered_after=triggered_at,
                            max_attempts=12,
                        )
                    )
                    if not run:
                        raise Exception("Could not find the triggered workflow run after 60 seconds")

                    state.github_workflow_run_id = run["id"]
                    state.current_step = RunStep.TRIGGERED_GITHUB_WORKFLOW
                    save_state()  # Save immediately after trigger

                    workflow_url = f"https://github.com/{config.github.owner}/{config.github.repo}/actions/runs/{state.github_workflow_run_id}"
                    await ws_manager.send_step_progress(release_id, 4, f"Workflow triggered: {workflow_url}")

                # Step 4b: Wait for completion (can resume from here if interrupted)
                if state.github_workflow_run_id:
                    await ws_manager.send_step_progress(release_id, 4, "Waiting for workflow to complete...")

                    run_result = await loop.run_in_executor(
                        None,
                        lambda: gh.poll_workflow_run(
                            state.github_workflow_run_id,
                            poll_interval=30,
                            timeout_minutes=20,
                        )
                    )

                    state.current_step = RunStep.GITHUB_WORKFLOW_COMPLETED
                    save_state()

                    workflow_url = f"https://github.com/{config.github.owner}/{config.github.repo}/actions/runs/{state.github_workflow_run_id}"
                    await ws_manager.send_step_complete(
                        release_id, 4, "GitHub Workflow", "github_workflow_completed",
                        {"github_workflow_run_id": state.github_workflow_run_id, "url": workflow_url}
                    )

            # Step 5: Jenkins build (split into trigger + poll to avoid duplicate triggers on resume)
            if not state.can_resume_from(RunStep.JENKINS_COMPLETED):
                # Use injected/fake client or create real one
                jenkins_cli = jenkins or JenkinsClient()
                loop = asyncio.get_event_loop()

                # Step 5a: Trigger build (skip if already triggered)
                if not state.jenkins_build_number:
                    await ws_manager.send_step_start(release_id, 5, "Jenkins Build", "jenkins_completed")

                    # Try to recover build number from queue URL if we have one
                    # This handles the case where trigger succeeded but we lost connection
                    # before getting the build number
                    if state.jenkins_queue_url:
                        await ws_manager.send_step_progress(
                            release_id, 5, "Recovering build from previous queue..."
                        )
                        try:
                            queue_item = await loop.run_in_executor(
                                None, lambda: jenkins_cli.get_queue_item(state.jenkins_queue_url)
                            )
                            if "executable" in queue_item:
                                state.jenkins_build_number = queue_item["executable"]["number"]
                                state.jenkins_job_url = queue_item["executable"]["url"]
                                state.current_step = RunStep.TRIGGERED_JENKINS
                                save_state()
                                await ws_manager.send_step_progress(
                                    release_id, 5,
                                    f"Recovered build #{state.jenkins_build_number}: {state.jenkins_job_url}"
                                )
                                logger.info(
                                    f"Recovered Jenkins build #{state.jenkins_build_number} from queue URL"
                                )
                        except Exception as e:
                            logger.warning(f"Could not recover from queue URL: {e}")
                            # Clear stale queue URL so we can trigger fresh
                            state.jenkins_queue_url = None
                            save_state()

                    # If still no build number (recovery failed or no queue URL), trigger new build
                    if not state.jenkins_build_number:
                        await ws_manager.send_step_progress(release_id, 5, "Triggering Jenkins build...")

                        # Trigger build (returns queue URL)
                        trigger_result = await loop.run_in_executor(
                            None,
                            lambda: jenkins_cli.trigger_build(
                                release_version=state.build_version,
                                ticket=state.promote_ticket_key,
                            )
                        )
                        state.jenkins_queue_url = trigger_result["queue_url"]
                        save_state()  # Save queue URL in case of interruption

                        # Wait for build to start (get build number)
                        await ws_manager.send_step_progress(release_id, 5, "Waiting for build to start...")
                        start_info = await loop.run_in_executor(
                            None,
                            lambda: jenkins_cli.wait_for_build_start(
                                state.jenkins_queue_url,
                                timeout_minutes=10,
                                max_consecutive_poll_failures=max_consecutive_poll_failures,
                            )
                        )
                        state.jenkins_build_number = start_info["build_number"]
                        state.jenkins_job_url = start_info["job_url"]
                        state.current_step = RunStep.TRIGGERED_JENKINS
                        save_state()  # Save build number immediately after getting it

                        await ws_manager.send_step_progress(
                            release_id, 5,
                            f"Build #{state.jenkins_build_number} started: {state.jenkins_job_url}"
                        )

                # Step 5b: Wait for completion (can resume from here if interrupted)
                # Races polling against a skip event so the user can proceed without waiting
                if state.jenkins_build_number:
                    await ws_manager.send_step_progress(release_id, 5, "Waiting for build to complete...")

                    skip_event = self._skip_events.setdefault(release_id, asyncio.Event())
                    poll_future = loop.run_in_executor(
                        None,
                        lambda: jenkins_cli.poll_build_by_number(
                            state.jenkins_build_number,
                            max_consecutive_poll_failures=max_consecutive_poll_failures,
                        )
                    )
                    skip_future = asyncio.ensure_future(skip_event.wait())

                    done, pending = await asyncio.wait(
                        {poll_future, skip_future}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in pending:
                        task.cancel()

                    jenkins_skipped = skip_future in done

                    if not jenkins_skipped:
                        result = poll_future.result()
                        # Update job_url in case it wasn't set (e.g., resumed from older state)
                        state.jenkins_job_url = result.get("job_url", state.jenkins_job_url)

                    # Clean up skip event
                    self._skip_events.pop(release_id, None)

                    state.current_step = RunStep.JENKINS_COMPLETED
                    save_state()

                    step_result = {
                        "jenkins_build_number": state.jenkins_build_number,
                        "jenkins_job_url": state.jenkins_job_url,
                    }
                    if jenkins_skipped:
                        step_result["skipped"] = True

                    await ws_manager.send_step_complete(
                        release_id, 5, "Jenkins Build", "jenkins_completed",
                        step_result
                    )

            # Step 6: Create deployment ticket
            if not state.can_resume_from(RunStep.CREATED_DEPLOYMENT_TICKET) or not state.deployment_ticket_key:
                await ws_manager.send_step_start(release_id, 6, "Create Deployment Ticket", "created_deployment_ticket")

                deployment_payload = build_deployment_ticket_payload(
                    build_version=state.build_version,
                    rollback_version=state.rollback_version,
                    current_branch=state.current_branch,
                    previous_branch=state.previous_branch,
                    promote_ticket_key=state.promote_ticket_key,
                    devint_job_url=state.jenkins_job_url,
                    jira_ids=state.jira_ids,
                )

                # Use injected/fake client or create real one
                jira_cli = jira or JiraClient()
                result = jira_cli.create_issue(deployment_payload)
                state.deployment_ticket_key = result["key"]
                state.deployment_ticket_id = result["id"]
                save_state()  # Save ticket key immediately to prevent duplicates on resume
                logger.info(f"Created deployment ticket: {state.deployment_ticket_key}")

                # Link to previous deployment ticket if specified (non-fatal on failure)
                if state.previous_deployment_ticket_key and not state.deployment_ticket_relates_linked:
                    try:
                        jira_cli.create_issue_link(
                            inward_issue_key=state.previous_deployment_ticket_key,
                            outward_issue_key=state.deployment_ticket_key,
                            link_type="Relates",
                        )
                        state.deployment_ticket_relates_linked = True
                        save_state()
                        logger.info(
                            f"Linked {state.deployment_ticket_key} to previous: "
                            f"{state.previous_deployment_ticket_key}"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to link tickets (non-fatal): {e}")

                state.current_step = RunStep.CREATED_DEPLOYMENT_TICKET
                save_state()

                await ws_manager.send_step_complete(
                    release_id, 6, "Create Deployment Ticket", "created_deployment_ticket",
                    {"deployment_ticket_key": state.deployment_ticket_key, "url": format_jira_url(state.deployment_ticket_key)}
                )

            # Step 7: Close promote ticket
            if not state.can_resume_from(RunStep.CLOSED_PROMOTE_TICKET):
                await ws_manager.send_step_start(release_id, 7, "Close Promote Ticket", "closed_promote_ticket")

                # Use injected/fake client or create real one
                jira_cli = jira or JiraClient()
                try:
                    issue = jira_cli.get_issue(state.promote_ticket_key)
                    current_status = issue["fields"]["status"]["name"]
                    resolution = (issue["fields"].get("resolution") or {}).get("name")

                    if current_status not in ("Resolved", "Closed", "Done") and not resolution:
                        fix_version_label = derive_fix_version_label(state.build_version)
                        transition_fields = jira_cli.prepare_resolve_fixed(
                            state.promote_ticket_key,
                            fix_version_label=fix_version_label,
                            sub_component_label="queryservice",
                            add_no_code_label=False,
                        )
                        jira_cli.transition_issue(
                            state.promote_ticket_key,
                            transition_name="Resolve Issue",
                            resolution="Fixed",
                            fields=transition_fields,
                        )
                except Exception as e:
                    logger.warning(f"Could not close promote ticket: {e}")

                state.current_step = RunStep.CLOSED_PROMOTE_TICKET
                save_state()

                await ws_manager.send_step_complete(
                    release_id, 7, "Close Promote Ticket", "closed_promote_ticket",
                    {}
                )

            # Complete
            state.completed_at = datetime.now().isoformat()
            state.current_step = RunStep.COMPLETED
            save_state()

            await ws_manager.send_workflow_complete(release_id, {
                "build_version": state.build_version,
                "promote_ticket_key": state.promote_ticket_key,
                "deployment_ticket_key": state.deployment_ticket_key,
                "jenkins_job_url": state.jenkins_job_url,
                "promote_url": format_jira_url(state.promote_ticket_key) if state.promote_ticket_key else None,
                "deployment_url": format_jira_url(state.deployment_ticket_key) if state.deployment_ticket_key else None,
            })

        except Exception as e:
            logger.exception(f"Workflow failed for release {release_id}")
            state.error_message = str(e)
            state.error_step = state.current_step.value
            save_state()

            step_num = _step_number_from_key(state.current_step.value)
            await ws_manager.send_workflow_error(release_id, str(e), step_num)


# Global instance
workflow_service = WorkflowService()
