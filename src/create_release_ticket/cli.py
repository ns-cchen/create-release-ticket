"""CLI for create-release-ticket."""

from __future__ import annotations

import json
import re
import signal
import sys
from datetime import UTC, datetime
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from create_release_ticket import __version__
from create_release_ticket.clients import GitHubClient, JenkinsClient, JiraClient
from create_release_ticket.config import get_app_config
from create_release_ticket.logging_config import get_logger, setup_logging
from create_release_ticket.rollback import (
    cleanup_resources,
    prompt_cleanup_on_error,
    prompt_cleanup_on_interrupt,
)
from create_release_ticket.state import (
    RunState,
    RunStep,
    create_new_run,
    get_resumable_state,
)
from create_release_ticket.templates import (
    build_deployment_ticket_payload,
    build_promote_ticket_payload,
)
from create_release_ticket.utils import (
    derive_fix_version_label,
    extract_jira_ids,
    format_jira_url,
    parse_build_version,
    validate_version_format,
)

console = Console()
logger = get_logger("cli")


# Global state for interrupt handling
_current_state: RunState | None = None


def _handle_interrupt(signum: int, frame: Any) -> None:
    """Handle Ctrl+C interrupt."""
    if _current_state:
        prompt_cleanup_on_interrupt(_current_state)
    sys.exit(1)


def _parse_stop_after(value: str | None) -> RunStep | None:
    """Parse --stop-after option into a RunStep.

    Accepts either a step number (1-7) or a keyword.
    """
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None

    step_map: dict[str, RunStep] = {
        "1": RunStep.PARSED_VERSION,
        "2": RunStep.FETCHED_COMMITS,
        "3": RunStep.CREATED_PROMOTE_TICKET,
        "4": RunStep.GITHUB_WORKFLOW_COMPLETED,
        "5": RunStep.JENKINS_COMPLETED,
        "6": RunStep.CREATED_DEPLOYMENT_TICKET,
        "7": RunStep.CLOSED_PROMOTE_TICKET,
        "parse": RunStep.PARSED_VERSION,
        "parsed": RunStep.PARSED_VERSION,
        "commits": RunStep.FETCHED_COMMITS,
        "promote": RunStep.CREATED_PROMOTE_TICKET,
        "github": RunStep.GITHUB_WORKFLOW_COMPLETED,
        "jenkins": RunStep.JENKINS_COMPLETED,
        "deploy": RunStep.CREATED_DEPLOYMENT_TICKET,
        "deployment": RunStep.CREATED_DEPLOYMENT_TICKET,
        "close": RunStep.CLOSED_PROMOTE_TICKET,
    }

    # Allow passing full RunStep value, e.g. "github_workflow_completed".
    try:
        return RunStep(normalized)
    except Exception:
        pass

    if normalized in step_map:
        return step_map[normalized]

    raise click.BadParameter(
        "Invalid value for --stop-after. Use 1-7, a keyword (github/jenkins/deploy), "
        "or a RunStep value like 'github_workflow_completed'."
    )


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Create Release Ticket - Automate QueryService deployment workflow."""
    pass


@main.command()
@click.option(
    "--build-version",
    "-b",
    required=False,
    default=None,
    help="Build version (e.g., queryservice-release-2025.12.2.0.18496)",
)
@click.option(
    "--rollback-version",
    "-r",
    required=False,
    default=None,
    help="Rollback version (e.g., queryservice-release-2025.12.1.0.18438)",
)
@click.option(
    "--ref",
    default="develop",
    help="Git ref for GitHub workflow (default: develop)",
)
@click.option(
    "--previous-branch",
    default=None,
    help="Override previous branch for commit comparison",
)
@click.option(
    "--jira-ids",
    default=None,
    help="Comma-separated Jira IDs (override auto-detection)",
)
@click.option(
    "--previous-deployment-ticket",
    default=None,
    help="Previous deployment ticket key to relate to (e.g., ENG-857076)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview actions without executing",
)
@click.option(
    "--stop-after",
    default=None,
    help=(
        "Stop after a step (for staged runs). "
        "Examples: --stop-after github | --stop-after 4 | --stop-after github_workflow_completed"
    ),
)
@click.option(
    "--jenkins-build-number",
    type=int,
    default=None,
    help="Use an existing Jenkins build number instead of triggering a new build",
)
@click.option(
    "--jenkins-job-url",
    default=None,
    help="Use an existing Jenkins job URL instead of triggering a new build",
)
@click.option(
    "--github-run-id",
    type=int,
    default=None,
    help="Use an existing GitHub workflow run ID instead of triggering a new workflow",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from last interrupted run",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
def run(
    build_version: str | None,
    rollback_version: str | None,
    ref: str,
    previous_branch: str | None,
    jira_ids: str | None,
    previous_deployment_ticket: str | None,
    dry_run: bool,
    stop_after: str | None,
    jenkins_build_number: int | None,
    jenkins_job_url: str | None,
    github_run_id: int | None,
    resume: bool,
    verbose: bool,
) -> None:
    """Run the full deployment ticket creation workflow."""
    global _current_state

    # Setup logging
    log_file = setup_logging(verbose=verbose)
    console.print(f"[dim]Log file: {log_file}[/dim]\n")

    # Setup interrupt handler
    signal.signal(signal.SIGINT, _handle_interrupt)

    try:
        # Check for resumable state
        if resume:
            state = get_resumable_state()
            if not state:
                console.print("[yellow]No resumable run found.[/yellow]")
                if not build_version or not rollback_version:
                    raise click.BadParameter(
                        "No resumable run found, and --build-version/--rollback-version were not provided."
                    )
                state = None
            else:
                console.print(f"[green]Resuming from step: {state.current_step.value}[/green]")
                # Override with saved values
                build_version = state.build_version
                rollback_version = state.rollback_version
                ref = state.ref
        else:
            state = None

        if not build_version or not rollback_version:
            raise click.BadParameter(
                "Missing required options: --build-version and --rollback-version"
            )

        # Validate inputs
        if not validate_version_format(build_version):
            raise click.BadParameter(
                f"Invalid build version format: {build_version}\n"
                "Expected: queryservice-release-YYYY.MM.W.P.DRONE"
            )

        if not validate_version_format(rollback_version):
            raise click.BadParameter(
                f"Invalid rollback version format: {rollback_version}\n"
                "Expected: queryservice-release-YYYY.MM.W.P.DRONE"
            )

        # Create or use existing state
        if state is None:
            state = create_new_run(build_version, rollback_version, ref)

        _current_state = state

        # Persist optional relationship target (can be set on new runs or resume).
        if previous_deployment_ticket:
            normalized_prev = previous_deployment_ticket.strip()
            if not re.match(r"^[A-Z]+-\d+$", normalized_prev):
                raise click.BadParameter(
                    f"Invalid Jira ticket key for --previous-deployment-ticket: {previous_deployment_ticket}"
                )
            state.previous_deployment_ticket_key = normalized_prev
            state.save()

        # If the user provides an existing Jenkins build, record it and skip triggering.
        if (jenkins_build_number is not None) or (jenkins_job_url is not None):
            if jenkins_build_number is None or jenkins_job_url is None:
                raise click.BadParameter(
                    "--jenkins-build-number and --jenkins-job-url must be provided together"
                )
            state.jenkins_build_number = jenkins_build_number
            state.jenkins_job_url = jenkins_job_url
            state.mark_step(RunStep.JENKINS_COMPLETED)

        # If the user provides an existing GitHub run ID, record it and skip triggering.
        if github_run_id is not None:
            state.github_workflow_run_id = github_run_id
            state.mark_step(RunStep.GITHUB_WORKFLOW_COMPLETED)

        # Run the workflow
        _run_workflow(
            state=state,
            previous_branch_override=previous_branch,
            jira_ids_override=jira_ids.split(",") if jira_ids else None,
            dry_run=dry_run,
            stop_after=_parse_stop_after(stop_after),
        )

    except Exception as e:
        logger.exception("Run failed")
        if _current_state and not dry_run:
            should_retry = prompt_cleanup_on_error(_current_state, e)
            if should_retry:
                # Recursive call to retry
                run.callback(
                    build_version=_current_state.build_version,
                    rollback_version=_current_state.rollback_version,
                    ref=_current_state.ref,
                    previous_branch=previous_branch,
                    jira_ids=jira_ids,
                    previous_deployment_ticket=previous_deployment_ticket,
                    dry_run=dry_run,
                    stop_after=stop_after,
                    jenkins_build_number=jenkins_build_number,
                    jenkins_job_url=jenkins_job_url,
                    github_run_id=github_run_id,
                    resume=True,
                    verbose=verbose,
                )
        else:
            raise click.ClickException(str(e))


def _run_workflow(
    state: RunState,
    previous_branch_override: str | None = None,
    jira_ids_override: list[str] | None = None,
    dry_run: bool = False,
    stop_after: RunStep | None = None,
) -> None:
    """Execute the deployment workflow."""
    config = get_app_config()

    if dry_run:
        console.print(Panel("[bold yellow]DRY RUN MODE - No actions will be taken[/bold yellow]"))

    def maybe_stop(after_step: RunStep) -> bool:
        if stop_after and after_step == stop_after:
            console.print(
                Panel(
                    f"Stopped after step: {after_step.value}\n"
                    "You can resume later with: create-release-ticket run --resume",
                    title="Stopped",
                    style="yellow",
                )
            )
            return True
        return False

    # Step 1: Parse version
    if not state.can_resume_from(RunStep.PARSED_VERSION) or not state.current_branch:
        console.print("\n[bold]Step 1: Parse build version[/bold]")
        parsed = parse_build_version(state.build_version)
        state.current_branch = parsed.current_branch
        state.previous_branch = previous_branch_override or parsed.previous_branch
        console.print(f"  Current branch: {state.current_branch}")
        console.print(f"  Previous branch: {state.previous_branch}")
        state.save()  # Persist branch data before mark_step
        state.mark_step(RunStep.PARSED_VERSION)
        if maybe_stop(RunStep.PARSED_VERSION):
            return

    # Step 2: Validate and fetch commits
    if not state.can_resume_from(RunStep.FETCHED_COMMITS) or not state.jira_ids:
        console.print("\n[bold]Step 2: Fetch commits and extract Jira IDs[/bold]")

        github = GitHubClient()

        # Check branches exist
        if not dry_run:
            if not github.check_branch_exists(state.current_branch):
                raise Exception(
                    f"Branch '{state.current_branch}' does not exist.\n"
                    f"Please verify or use --previous-branch to override."
                )
            if not github.check_branch_exists(state.previous_branch):
                raise Exception(
                    f"Branch '{state.previous_branch}' does not exist.\n"
                    f"Please use --previous-branch to specify the correct branch."
                )

        if jira_ids_override:
            state.jira_ids = jira_ids_override
            console.print(f"  Using provided Jira IDs: {state.jira_ids}")
        elif dry_run:
            state.jira_ids = ["DINT-0000", "EP-0000"]
            console.print(
                f"  [dim]Would fetch commits from {state.previous_branch}...{state.current_branch}[/dim]"
            )
        else:
            commits = github.compare_commits(state.previous_branch, state.current_branch)
            state.jira_ids = extract_jira_ids(commits)

            if not state.jira_ids:
                raise Exception(
                    f"No Jira IDs found in commits between {state.previous_branch} and {state.current_branch}.\n"
                    "Please use --jira-ids to specify them manually."
                )

        console.print(f"  Jira IDs: {', '.join(state.jira_ids)}")
        state.save()  # Persist jira_ids before mark_step
        state.mark_step(RunStep.FETCHED_COMMITS)
        if maybe_stop(RunStep.FETCHED_COMMITS):
            return

    # Step 3: Create promote ticket
    if not state.can_resume_from(RunStep.CREATED_PROMOTE_TICKET) or not state.promote_ticket_key:
        console.print("\n[bold]Step 3: Create promote ticket[/bold]")

        promote_payload = build_promote_ticket_payload(state.build_version)

        if dry_run:
            console.print("  [dim]Would create promote ticket with payload:[/dim]")
            console.print(
                f"  [dim]{json.dumps(promote_payload['fields']['summary'], indent=2)}[/dim]"
            )
            state.promote_ticket_key = "ENG-DRY-RUN"
            state.promote_ticket_id = "0"
        else:
            jira = JiraClient()
            result = jira.create_issue(promote_payload)
            state.promote_ticket_key = result["key"]
            state.promote_ticket_id = result["id"]
            state.save()  # 立即儲存！API 回傳後第一時間儲存

        console.print(f"  Promote ticket: {format_jira_url(state.promote_ticket_key)}")
        state.mark_step(RunStep.CREATED_PROMOTE_TICKET)
        if maybe_stop(RunStep.CREATED_PROMOTE_TICKET):
            return

    # Step 4: Trigger GitHub workflow (split into TRIGGERED and COMPLETED phases)
    if not state.can_resume_from(RunStep.GITHUB_WORKFLOW_COMPLETED):
        github = GitHubClient()

        # Phase 4a: Trigger workflow (skip if already triggered)
        if (
            not state.can_resume_from(RunStep.TRIGGERED_GITHUB_WORKFLOW)
            or not state.github_workflow_run_id
        ):
            console.print("\n[bold]Step 4a: Trigger GitHub workflow[/bold]")

            workflow_inputs = {
                "release-ticket": state.promote_ticket_key,
                "release-version": state.build_version,
                "destinations": config.github.destinations,
                "manifest-service": config.github.manifest_service,
                "notify-emails": config.github.notify_emails,
            }

            if dry_run:
                console.print("  [dim]Would trigger workflow with inputs:[/dim]")
                for k, v in workflow_inputs.items():
                    console.print(f"    {k}: {v}")
                state.github_workflow_run_id = 0  # Placeholder for dry run
            else:
                # Trigger the workflow
                workflow_file = config.github.workflow_file
                triggered_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                github.trigger_workflow(workflow_file, state.ref, workflow_inputs)

                # Get the run ID
                run = github.get_latest_workflow_run(
                    workflow_file,
                    wait_seconds=5,
                    triggered_after=triggered_at,
                    max_attempts=12,
                )
                if not run:
                    raise Exception("Could not find the triggered workflow run after 60 seconds")

                state.github_workflow_run_id = run["id"]
                console.print(f"  Workflow run ID: {state.github_workflow_run_id}")

            # Save and mark triggered (before waiting)
            state.save()
            state.mark_step(RunStep.TRIGGERED_GITHUB_WORKFLOW)
            if maybe_stop(RunStep.TRIGGERED_GITHUB_WORKFLOW):
                return

        # Phase 4b: Wait for workflow completion
        console.print("\n[bold]Step 4b: Wait for GitHub workflow completion[/bold]")

        if dry_run:
            console.print("  [dim]Would wait for workflow to complete[/dim]")
        else:
            console.print(f"  Resuming poll for workflow run ID: {state.github_workflow_run_id}")
            github.poll_workflow_run(
                state.github_workflow_run_id,
                poll_interval=30,
                timeout_minutes=20,
            )

        state.mark_step(RunStep.GITHUB_WORKFLOW_COMPLETED)
        if maybe_stop(RunStep.GITHUB_WORKFLOW_COMPLETED):
            return

    # Step 5: Trigger Jenkins build (split into TRIGGERED and COMPLETED phases)
    if not state.can_resume_from(RunStep.JENKINS_COMPLETED):
        jenkins = JenkinsClient()

        # Phase 5a: Trigger Jenkins (skip if already triggered)
        if not state.can_resume_from(RunStep.TRIGGERED_JENKINS) or not state.jenkins_queue_url:
            console.print("\n[bold]Step 5a: Trigger Jenkins devint deployment[/bold]")

            if dry_run:
                console.print("  [dim]Would trigger Jenkins job with:[/dim]")
                console.print(f"    RELEASE: {state.build_version}")
                console.print(f"    TICKET: {state.promote_ticket_key}")
                state.jenkins_queue_url = "https://jenkins.example.com/queue/item/0/"
                state.jenkins_build_number = 0
                state.jenkins_job_url = "https://jenkins.example.com/job/dry-run/0/"
            else:
                trigger_result = jenkins.trigger_build(
                    release_version=state.build_version,
                    ticket=state.promote_ticket_key,
                )
                state.jenkins_queue_url = trigger_result["queue_url"]

            # Save and mark triggered (before waiting)
            state.save()
            state.mark_step(RunStep.TRIGGERED_JENKINS)
            if maybe_stop(RunStep.TRIGGERED_JENKINS):
                return

        # Phase 5b: Wait for build to start (get build_number)
        if not state.jenkins_build_number and not dry_run:
            console.print("\n[bold]Step 5b: Wait for Jenkins build to start[/bold]")
            console.print(f"  Resuming from queue URL: {state.jenkins_queue_url}")

            start_info = jenkins.wait_for_build_start(state.jenkins_queue_url)
            state.jenkins_build_number = start_info["build_number"]
            state.jenkins_job_url = start_info["job_url"]
            state.save()  # Save build info immediately

        # Phase 5c: Wait for build completion
        console.print("\n[bold]Step 5c: Wait for Jenkins build completion[/bold]")

        if dry_run:
            console.print("  [dim]Would wait for Jenkins build to complete[/dim]")
        else:
            console.print(f"  Polling build #{state.jenkins_build_number}: {state.jenkins_job_url}")
            result = jenkins.poll_build_by_number(state.jenkins_build_number)
            state.jenkins_job_url = result["job_url"]  # Update with final URL

        console.print(f"  Jenkins job: {state.jenkins_job_url}")
        state.save()
        state.mark_step(RunStep.JENKINS_COMPLETED)
        if maybe_stop(RunStep.JENKINS_COMPLETED):
            return

    # Step 6: Create deployment ticket
    if (
        not state.can_resume_from(RunStep.CREATED_DEPLOYMENT_TICKET)
        or not state.deployment_ticket_key
    ):
        console.print("\n[bold]Step 6: Create deployment ticket[/bold]")

        deployment_payload = build_deployment_ticket_payload(
            build_version=state.build_version,
            rollback_version=state.rollback_version,
            current_branch=state.current_branch,
            previous_branch=state.previous_branch,
            promote_ticket_key=state.promote_ticket_key,
            devint_job_url=state.jenkins_job_url,
            jira_ids=state.jira_ids,
        )

        if dry_run:
            console.print("  [dim]Would create deployment ticket[/dim]")
            state.deployment_ticket_key = "ENG-DRY-RUN-DEPLOY"
            state.deployment_ticket_id = "0"
        else:
            jira = JiraClient()

            # Retry up to 3 times
            max_retries = config.retry.max_attempts
            last_error = None

            for attempt in range(1, max_retries + 1):
                try:
                    result = jira.create_issue(deployment_payload)
                    state.deployment_ticket_key = result["key"]
                    state.deployment_ticket_id = result["id"]
                    state.save()  # 立即儲存！API 回傳後第一時間儲存
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        console.print(f"  [yellow]Attempt {attempt} failed, retrying...[/yellow]")
                    else:
                        console.print(
                            f"  [red]Failed to create deployment ticket after {max_retries} attempts[/red]"
                        )
                        console.print(
                            f"  [yellow]Promote ticket kept open: {format_jira_url(state.promote_ticket_key)}[/yellow]"
                        )
                        raise last_error

        console.print(f"  Deployment ticket: {format_jira_url(state.deployment_ticket_key)}")
        state.mark_step(RunStep.CREATED_DEPLOYMENT_TICKET)
        if maybe_stop(RunStep.CREATED_DEPLOYMENT_TICKET):
            return

    # Optional: Link new deployment ticket to a previous deployment ticket.
    if (
        state.previous_deployment_ticket_key
        and state.deployment_ticket_key
        and not state.deployment_ticket_relates_linked
    ):
        console.print("\n[bold]Link: Relates to previous deployment ticket[/bold]")
        if dry_run:
            console.print(
                f"  [dim]Would link {state.deployment_ticket_key} relates to {state.previous_deployment_ticket_key}[/dim]"
            )
        else:
            jira = JiraClient()
            jira.create_issue_link(
                inward_issue_key=state.previous_deployment_ticket_key,
                outward_issue_key=state.deployment_ticket_key,
                link_type="Relates",
            )

        state.deployment_ticket_relates_linked = True
        state.save()

    # Step 7: Close promote ticket
    if not state.can_resume_from(RunStep.CLOSED_PROMOTE_TICKET):
        console.print("\n[bold]Step 7: Close promote ticket[/bold]")

        if dry_run:
            console.print(
                f"  [dim]Would transition {state.promote_ticket_key} using Resolve Issue[/dim]"
            )
        else:
            jira = JiraClient()

            # Check current ticket status first - skip if already closed
            try:
                issue = jira.get_issue(state.promote_ticket_key)
                current_status = issue["fields"]["status"]["name"]
                resolution = (issue["fields"].get("resolution") or {}).get("name")

                # If ticket is already in a terminal state, skip transition
                if current_status in ("Resolved", "Closed", "Done") or resolution:
                    console.print(
                        f"  [green]✓ Ticket already closed (status={current_status}, "
                        f"resolution={resolution or 'N/A'})[/green]"
                    )
                else:
                    # Ticket still open, proceed with transition
                    fix_version_label = derive_fix_version_label(state.build_version)

                    # ENG promote ticket workflow uses "Resolve Issue".
                    # This project requires a resolution; when a PR is attached Jira enforces
                    # Resolution=Fixed.
                    transition_fields = jira.prepare_resolve_fixed(
                        state.promote_ticket_key,
                        fix_version_label=fix_version_label,
                        sub_component_label="queryservice",
                        add_no_code_label=False,
                    )
                    jira.transition_issue(
                        state.promote_ticket_key,
                        transition_name="Resolve Issue",
                        resolution="Fixed",
                        fields=transition_fields,
                    )
            except Exception as e:
                console.print(
                    f"[yellow]Warning: Could not check/close promote ticket: {e}[/yellow]"
                )
                console.print(
                    f"[yellow]You may need to close {state.promote_ticket_key} manually[/yellow]"
                )

        state.mark_step(RunStep.CLOSED_PROMOTE_TICKET)
        if maybe_stop(RunStep.CLOSED_PROMOTE_TICKET):
            return

    # Complete
    state.completed_at = datetime.now().isoformat()
    state.mark_step(RunStep.COMPLETED)

    # Clear state file on success
    if not dry_run:
        RunState.clear()

    # Print summary
    _print_summary(state, dry_run)


def _print_summary(state: RunState, dry_run: bool = False) -> None:
    """Print final summary."""
    console.print("\n")

    title = "DRY RUN COMPLETE" if dry_run else "DEPLOYMENT WORKFLOW COMPLETE"
    style = "yellow" if dry_run else "green"

    table = Table(title=f"[bold {style}]✓ {title}[/bold {style}]", show_header=False)
    table.add_column("Item", style="cyan")
    table.add_column("Value")

    table.add_row("Build Version", state.build_version)
    table.add_row("Rollback Version", state.rollback_version)
    table.add_row("", "")
    table.add_row(
        "Promote Ticket",
        format_jira_url(state.promote_ticket_key) if state.promote_ticket_key else "N/A",
    )
    table.add_row(
        "Deployment Ticket",
        format_jira_url(state.deployment_ticket_key) if state.deployment_ticket_key else "N/A",
    )
    table.add_row("Jenkins Job", state.jenkins_job_url or "N/A")
    table.add_row("", "")
    table.add_row("Jira IDs", ", ".join(state.jira_ids) if state.jira_ids else "N/A")

    console.print(table)


@main.command()
def validate() -> None:
    """Validate credentials and configuration."""
    console.print("[bold]Validating credentials...[/bold]\n")

    all_valid = True

    # Validate Jira
    try:
        jira = JiraClient()
        if not jira.validate_credentials():
            all_valid = False
    except Exception as e:
        console.print(f"[red]✗ Jira: {e}[/red]")
        all_valid = False

    # Validate GitHub
    try:
        github = GitHubClient()
        if not github.validate_credentials():
            all_valid = False
    except Exception as e:
        console.print(f"[red]✗ GitHub: {e}[/red]")
        all_valid = False

    # Validate Jenkins
    try:
        jenkins = JenkinsClient()
        if not jenkins.validate_credentials():
            all_valid = False
    except Exception as e:
        console.print(f"[red]✗ Jenkins: {e}[/red]")
        all_valid = False

    if all_valid:
        console.print("\n[bold green]✓ All credentials valid![/bold green]")
    else:
        console.print(
            "\n[bold red]✗ Some credentials are invalid. Please check your .env file.[/bold red]"
        )
        sys.exit(1)


@main.command()
def cleanup() -> None:
    """Clean up resources from a failed run."""
    state = RunState.load()

    if not state:
        console.print("[yellow]No state file found. Nothing to clean up.[/yellow]")
        return

    if state.current_step == RunStep.COMPLETED:
        console.print("[yellow]Last run completed successfully. Nothing to clean up.[/yellow]")
        RunState.clear()
        return

    cleanup_resources(state)


@main.command("delete-ticket")
@click.argument("ticket_key")
def delete_ticket(ticket_key: str) -> None:
    """Delete a specific Jira ticket (not supported in most Jira projects)."""
    raise click.ClickException(
        "Delete is not permitted by Jira permissions. Use 'close-ticket' (Resolve Issue) instead."
    )


@main.command("close-ticket")
@click.argument("ticket_key")
@click.option(
    "--fix-version",
    "fix_version",
    default=None,
    help="FixVersion label to set before resolving as Fixed (e.g., 202601.4).",
)
@click.option(
    "--sub-component",
    "sub_component",
    default="queryservice",
    show_default=True,
    help="Sub-Component label to set before resolving (e.g., queryservice).",
)
def close_ticket(ticket_key: str, fix_version: str | None, sub_component: str) -> None:
    """Close a specific Jira ticket (transition via Resolve Issue)."""
    jira = JiraClient()

    transition_fields = jira.prepare_resolve_fixed(
        ticket_key,
        fix_version_label=fix_version,
        sub_component_label=sub_component,
        add_no_code_label=False,
    )
    jira.transition_issue(
        ticket_key,
        transition_name="Resolve Issue",
        resolution="Fixed",
        fields=transition_fields,
    )


@main.command()
def show_state() -> None:
    """Show the current state file contents."""
    state = RunState.load()

    if not state:
        console.print("[yellow]No state file found.[/yellow]")
        return

    console.print(Panel(json.dumps(state.to_dict(), indent=2), title="Current State"))


if __name__ == "__main__":
    main()
