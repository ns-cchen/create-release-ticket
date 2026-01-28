"""Rollback and cleanup logic."""

from __future__ import annotations

from rich.console import Console

from create_release_ticket.clients.jenkins import JenkinsClient
from create_release_ticket.clients.jira import JiraClient
from create_release_ticket.state import RunState

console = Console()


def cleanup_resources(
    state: RunState,
    close_tickets: bool = True,
    cancel_jenkins: bool = True,
) -> None:
    """Clean up resources created during a failed run.

    Notes:
    - Only closes promote ticket (temporary workflow trigger).
    - Keeps deployment ticket open (tracks actual deployment, close manually after deployment).
    - Most Jira projects do not allow deleting issues; we close (resolve) instead.
    - For Story tickets with PR attached, resolution must be Fixed.
    """

    resources = state.get_created_resources()
    if not resources:
        console.print("[yellow]No resources to clean up[/yellow]")
        return

    console.print("\n[bold red]Resources to clean up:[/bold red]")
    for resource_type, resource_id in resources:
        console.print(f"  • {resource_type}: {resource_id}")

    if close_tickets:
        jira = JiraClient()

        # Note: We do NOT close the deployment ticket here.
        # Deployment tickets track actual production deployment and should remain open
        # until deployment is complete. Close them manually after deployment.
        if state.deployment_ticket_key:
            console.print(
                f"[yellow]Keeping deployment ticket open: {state.deployment_ticket_key} "
                f"(close manually after deployment)[/yellow]"
            )

        # Close promote ticket (temporary workflow trigger ticket)
        if state.promote_ticket_key:
            try:
                transition_fields = jira.prepare_resolve_fixed(
                    state.promote_ticket_key,
                    fix_version_label=None,
                    sub_component_label="queryservice",
                    add_no_code_label=True,
                )
                jira.transition_issue(
                    state.promote_ticket_key,
                    transition_name="Resolve Issue",
                    resolution="Fixed",
                    fields=transition_fields,
                )
            except Exception as e:
                console.print(f"[yellow]Could not close {state.promote_ticket_key}: {e}[/yellow]")

    if cancel_jenkins and state.jenkins_build_number:
        try:
            jenkins = JenkinsClient()
            jenkins.cancel_build(state.jenkins_build_number)
            state.jenkins_build_number = None
        except Exception as e:
            console.print(f"[yellow]Could not cancel Jenkins build: {e}[/yellow]")

    RunState.clear()
    console.print("[green]✓ Cleanup completed[/green]")


def prompt_cleanup_on_error(state: RunState, error: Exception) -> bool:
    """Prompt user for action when an error occurs.

    Returns:
        True if user wants to retry, False otherwise.
    """

    console.print(f"\n[bold red]Error occurred:[/bold red] {error}")

    resources = state.get_created_resources()
    if resources:
        console.print("\n[bold yellow]Created resources:[/bold yellow]")
        for resource_type, resource_id in resources:
            if resource_type in ("Promote Ticket", "Deployment Ticket"):
                url = f"https://netskope.atlassian.net/browse/{resource_id}"
                console.print(f"  • {resource_type}: [link={url}]{resource_id}[/link]")
            else:
                console.print(f"  • {resource_type}: {resource_id}")

    console.print("\n[bold]Options:[/bold]")
    console.print("  [cyan]c[/cyan] - Clean up (close tickets, cancel builds)")
    console.print("  [cyan]k[/cyan] - Keep resources and exit")
    console.print("  [cyan]r[/cyan] - Retry from last step (resume)")

    while True:
        try:
            choice = console.input("\n[bold]Choose an option [c/k/r]: [/bold]").lower().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Resources kept.[/yellow]")
            return False

        if choice == "c":
            cleanup_resources(state)
            return False
        if choice == "k":
            console.print("\n[yellow]Resources kept. You can resume with:[/yellow]")
            console.print("  create-release-ticket run --resume")
            console.print("\n[yellow]Or clean up later with:[/yellow]")
            console.print("  create-release-ticket cleanup")
            return False
        if choice == "r":
            return True

        console.print("[red]Invalid choice. Please enter 'c', 'k', or 'r'[/red]")


def prompt_cleanup_on_interrupt(state: RunState) -> None:
    """Prompt user for action when interrupted (Ctrl+C)."""

    console.print("\n\n[bold yellow]Interrupted![/bold yellow]")

    resources = state.get_created_resources()
    if not resources:
        console.print("[yellow]No resources to clean up[/yellow]")
        return

    console.print("\n[bold yellow]Created resources:[/bold yellow]")
    for resource_type, resource_id in resources:
        console.print(f"  • {resource_type}: {resource_id}")

    console.print("\n[bold]Options:[/bold]")
    console.print("  [cyan]c[/cyan] - Clean up (close tickets, cancel builds)")
    console.print("  [cyan]k[/cyan] - Keep resources and exit")

    while True:
        try:
            choice = console.input("\n[bold]Choose an option [c/k]: [/bold]").lower().strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Resources kept.[/yellow]")
            return

        if choice == "c":
            cleanup_resources(state)
            return
        if choice == "k":
            console.print("\n[yellow]Resources kept.[/yellow]")
            return

        console.print("[red]Invalid choice. Please enter 'c' or 'k'[/red]")
        continue
