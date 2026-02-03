"""GitHub API client."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from create_release_ticket.clients.base import BaseClient
from create_release_ticket.config import get_app_config, get_settings

console = Console()


class GitHubClient(BaseClient):
    """Client for GitHub REST API."""

    def __init__(self):
        settings = get_settings()
        config = get_app_config()

        super().__init__(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {settings.github_pat}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        self.github_config = config.github
        self.owner = config.github.owner
        self.repo = config.github.repo

    def validate_credentials(self) -> bool:
        """
        Validate GitHub credentials.

        Returns:
            True if credentials are valid
        """
        try:
            response = self.get("/user")
            if response.status_code == 200:
                user = response.json()
                console.print(
                    f"[green]✓ GitHub: Authenticated as {user.get('login', 'Unknown')}[/green]"
                )
                return True
            return False
        except Exception as e:
            console.print(f"[red]✗ GitHub authentication failed: {e}[/red]")
            return False

    def check_branch_exists(self, branch: str) -> bool:
        """
        Check if a branch exists.

        Args:
            branch: Branch name

        Returns:
            True if branch exists
        """
        response = self.get(f"/repos/{self.owner}/{self.repo}/branches/{branch}")
        return response.status_code == 200

    def compare_commits(self, base: str, head: str) -> list[dict[str, Any]]:
        """
        Compare two branches and get commits between them.

        Args:
            base: Base branch name
            head: Head branch name

        Returns:
            List of commits
        """
        response = self.get(
            f"/repos/{self.owner}/{self.repo}/compare/{base}...{head}",
            params={"per_page": 100},
        )

        if response.status_code != 200:
            raise Exception(
                f"Failed to compare branches {base}...{head}: "
                f"{response.status_code} - {response.text}"
            )

        data = response.json()
        commits = data.get("commits", [])
        console.print(f"[blue]Found {len(commits)} commits between {base} and {head}[/blue]")
        return commits

    def trigger_workflow(
        self,
        workflow_file: str,
        ref: str,
        inputs: dict[str, str],
    ) -> bool:
        """
        Trigger a workflow dispatch event.

        Args:
            workflow_file: Workflow filename (e.g., ep-falcon-distribution.yml)
            ref: Git ref to run workflow on
            inputs: Workflow inputs

        Returns:
            True if triggered successfully
        """
        response = self.post(
            f"/repos/{self.owner}/{self.repo}/actions/workflows/{workflow_file}/dispatches",
            json={
                "ref": ref,
                "inputs": inputs,
            },
        )

        if response.status_code not in (200, 204):
            raise Exception(f"Failed to trigger workflow: {response.status_code} - {response.text}")

        console.print(f"[green]✓ Triggered workflow {workflow_file}[/green]")
        return True

    def get_latest_workflow_run(
        self,
        workflow_file: str,
        wait_seconds: int = 5,
        triggered_after: str | None = None,
        max_attempts: int = 12,
    ) -> dict[str, Any] | None:
        """
        Get the latest workflow run for a workflow file.

        Args:
            workflow_file: Workflow filename
            wait_seconds: Seconds to wait between polling attempts
            triggered_after: ISO timestamp - only return runs created after this time
            max_attempts: Maximum number of polling attempts to find the new run

        Returns:
            Workflow run data or None
        """
        for attempt in range(max_attempts):
            # Wait before querying (to let GitHub register the run)
            time.sleep(wait_seconds)

            response = self.get(
                f"/repos/{self.owner}/{self.repo}/actions/workflows/{workflow_file}/runs",
                params={"per_page": 5, "event": "workflow_dispatch"},
            )

            if response.status_code != 200:
                continue

            runs = response.json().get("workflow_runs", [])
            for run in runs:
                # If we have a triggered_after timestamp, only accept runs created after it
                if triggered_after:
                    run_created_at = run.get("created_at", "")
                    if run_created_at > triggered_after:
                        return run
                else:
                    # No timestamp filter, return the first (most recent) run
                    if runs:
                        return runs[0]

            # Log retry attempt
            if attempt < max_attempts - 1:
                console.print(
                    f"[yellow]Waiting for new workflow run to appear (attempt {attempt + 1}/{max_attempts})...[/yellow]"
                )

        return None

    def get_workflow_run(self, run_id: int) -> dict[str, Any]:
        """
        Get workflow run details.

        Args:
            run_id: Workflow run ID

        Returns:
            Workflow run data
        """
        response = self.get(f"/repos/{self.owner}/{self.repo}/actions/runs/{run_id}")

        if response.status_code != 200:
            raise Exception(f"Failed to get workflow run: {response.status_code}")

        return response.json()

    def poll_workflow_run(
        self,
        run_id: int,
        poll_interval: int = 30,
        timeout_minutes: int = 20,
    ) -> dict[str, Any]:
        """
        Poll workflow run until completion.

        Args:
            run_id: Workflow run ID
            poll_interval: Seconds between polls
            timeout_minutes: Maximum minutes to wait

        Returns:
            Final workflow run data

        Raises:
            Exception if workflow fails or times out
        """
        max_polls = (timeout_minutes * 60) // poll_interval
        html_url = f"https://github.com/{self.owner}/{self.repo}/actions/runs/{run_id}"

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Waiting for workflow run...", total=None)

            for _ in range(max_polls):
                run_data = self.get_workflow_run(run_id)
                status = run_data.get("status")
                conclusion = run_data.get("conclusion")

                progress.update(
                    task,
                    description=f"[cyan]Workflow status: {status} | {html_url}",
                )

                if status == "completed":
                    if conclusion == "success":
                        console.print("[green]✓ Workflow completed successfully[/green]")
                        return run_data
                    else:
                        raise Exception(
                            f"Workflow failed with conclusion: {conclusion}\n" f"See: {html_url}"
                        )

                time.sleep(poll_interval)

        raise Exception(f"Workflow timed out after {timeout_minutes} minutes\nSee: {html_url}")

    def trigger_and_wait_workflow(
        self,
        ref: str,
        inputs: dict[str, str],
        poll_interval: int = 30,
        timeout_minutes: int = 20,
    ) -> dict[str, Any]:
        """
        Trigger workflow and wait for completion.

        Args:
            ref: Git ref to run workflow on
            inputs: Workflow inputs
            poll_interval: Seconds between polls
            timeout_minutes: Maximum minutes to wait

        Returns:
            Final workflow run data
        """
        from datetime import datetime, timezone

        workflow_file = self.github_config.workflow_file

        # Capture timestamp before triggering to filter out stale runs
        triggered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Trigger the workflow
        self.trigger_workflow(workflow_file, ref, inputs)

        # Get the run that was just triggered (must be created after triggered_at)
        run = self.get_latest_workflow_run(
            workflow_file,
            wait_seconds=5,
            triggered_after=triggered_at,
            max_attempts=12,  # Up to 60 seconds of waiting
        )
        if not run:
            raise Exception("Could not find the triggered workflow run after 60 seconds")

        run_id = run["id"]
        console.print(f"[blue]Workflow run ID: {run_id}[/blue]")
        console.print(
            f"[blue]URL: https://github.com/{self.owner}/{self.repo}/actions/runs/{run_id}[/blue]"
        )

        # Poll until completion
        return self.poll_workflow_run(run_id, poll_interval, timeout_minutes)
