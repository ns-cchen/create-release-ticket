"""Jenkins API client."""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import nullcontext
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

logger = logging.getLogger(__name__)

from create_release_ticket.clients.base import BaseClient
from create_release_ticket.config import get_app_config, get_settings

console = Console()


class JenkinsConnectionError(Exception):
    """User-friendly Jenkins connection error.

    Raised when network operations fail with a helpful message
    explaining what went wrong and how to fix it.
    """
    pass


def _is_interactive() -> bool:
    """Check if running in an interactive terminal."""
    return sys.stdout.isatty() and os.environ.get("TERM") is not None


class JenkinsClient(BaseClient):
    """Client for Jenkins REST API."""

    def __init__(self):
        settings = get_settings()
        config = get_app_config()

        super().__init__(
            base_url=settings.jenkins_url,
            auth=(settings.jenkins_user, settings.jenkins_api_token),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=60.0,
        )
        self.jenkins_config = config.jenkins
        self.base_job_url = f"{settings.jenkins_url}/job/{config.jenkins.job_name}"

    def validate_credentials(self) -> bool:
        """
        Validate Jenkins credentials.

        Returns:
            True if credentials are valid
        """
        try:
            response = self.get("/api/json")
            if response.status_code == 200:
                console.print("[green]✓ Jenkins: Authentication successful[/green]")
                return True
            return False
        except Exception as e:
            error_msg = self._format_connection_error(e)
            console.print(f"[red]✗ Jenkins: {error_msg}[/red]")
            return False

    def _format_connection_error(self, error: Exception) -> str:
        """
        Format connection errors into user-friendly messages.

        Args:
            error: The exception that occurred

        Returns:
            A helpful error message explaining what went wrong
        """
        import socket
        from urllib.parse import urlparse

        import httpx

        # Extract hostname from base_url for context
        hostname = urlparse(self.base_url).hostname or self.base_url

        error_str = str(error)

        # DNS resolution failure (Errno 8)
        if isinstance(error, socket.gaierror) or "nodename nor servname" in error_str:
            return (
                f"Cannot resolve hostname '{hostname}'\n"
                f"  → Check your VPN connection\n"
                f"  → Verify JENKINS_URL in your .env file is correct"
            )

        # Connection refused
        if isinstance(error, ConnectionRefusedError) or "Connection refused" in error_str:
            return (
                f"Connection refused to '{hostname}'\n"
                f"  → Jenkins server may not be running\n"
                f"  → Check if the port is correct"
            )

        # Timeout
        if isinstance(error, httpx.TimeoutException) or "timed out" in error_str.lower():
            return (
                f"Connection timed out to '{hostname}'\n"
                f"  → Network may be slow or server unresponsive\n"
                f"  → Check your VPN connection"
            )

        # SSL/TLS errors
        if "SSL" in error_str or "certificate" in error_str.lower():
            return (
                f"SSL/TLS error connecting to '{hostname}'\n"
                f"  → Certificate may be invalid or expired\n"
                f"  → Check if you need to update your CA certificates"
            )

        # Generic network error
        if isinstance(error, (httpx.NetworkError, OSError)):
            return (
                f"Network error connecting to '{hostname}'\n"
                f"  → Check your internet/VPN connection\n"
                f"  → Error: {error}"
            )

        # Unknown error - include original for debugging
        return f"Connection failed: {error}"

    def trigger_build(
        self,
        release_version: str,
        ticket: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Trigger a Jenkins build.

        Args:
            release_version: Release version (e.g., queryservice-release-2025.12.2.0.18496)
            ticket: Jira ticket (e.g., ENG-123456)
            extra_params: Additional parameters to pass

        Returns:
            Dict with queue_url and other info

        Raises:
            JenkinsConnectionError: If connection to Jenkins fails
        """
        config = self.jenkins_config

        # Build parameters
        params = {
            "REGIONS": config.regions,
            "POP_TYPES": config.pop_types,
            "POPS": config.pops,
            "RELEASE": release_version,
            "STORK_RELEASE": release_version,
            "STORK_COMPONENT_NAME": config.stork_component_name,
            "SLACK_CHANNEL": config.slack_channel,
            "TICKET": ticket,
            "RUN_QE_PDV": config.run_qe_pdv,
            "PDV_CONFIG_IMAGE_TAG": config.pdv_config_image_tag,
        }

        if extra_params:
            params.update(extra_params)

        try:
            response = self.post(
                f"/job/{config.job_name}/buildWithParameters",
                data=params,
            )
        except Exception as e:
            raise JenkinsConnectionError(self._format_connection_error(e)) from e

        if response.status_code not in (200, 201):
            raise Exception(
                f"Failed to trigger Jenkins build: {response.status_code} - {response.text}"
            )

        # Get queue URL from Location header
        queue_url = response.headers.get("Location", "")

        console.print("[green]✓ Triggered Jenkins build[/green]")
        console.print(f"[blue]Queue URL: {queue_url}[/blue]")

        return {
            "queue_url": queue_url,
            "params": params,
        }

    def get_queue_item(self, queue_url: str) -> dict[str, Any]:
        """
        Get queue item info.

        Args:
            queue_url: Queue URL from trigger response

        Returns:
            Queue item data

        Raises:
            JenkinsConnectionError: If connection to Jenkins fails
        """
        # Extract queue ID from URL
        # Queue URL format: https://jenkins.../queue/item/12345/
        api_url = f"{queue_url}api/json"

        try:
            response = self.get(api_url.replace(self.base_url, ""))
        except Exception as e:
            raise JenkinsConnectionError(self._format_connection_error(e)) from e

        if response.status_code != 200:
            raise Exception(f"Failed to get queue item: {response.status_code}")

        return response.json()

    def get_build(self, build_number: int) -> dict[str, Any]:
        """
        Get build info.

        Args:
            build_number: Build number

        Returns:
            Build data

        Raises:
            JenkinsConnectionError: If connection to Jenkins fails
        """
        try:
            response = self.get(f"/job/{self.jenkins_config.job_name}/{build_number}/api/json")
        except Exception as e:
            raise JenkinsConnectionError(self._format_connection_error(e)) from e

        if response.status_code != 200:
            raise Exception(f"Failed to get build {build_number}: {response.status_code}")

        return response.json()

    def cancel_build(self, build_number: int) -> bool:
        """
        Cancel a running build.

        Args:
            build_number: Build number

        Returns:
            True if cancelled successfully

        Raises:
            JenkinsConnectionError: If connection to Jenkins fails
        """
        try:
            response = self.post(f"/job/{self.jenkins_config.job_name}/{build_number}/stop")
        except Exception as e:
            raise JenkinsConnectionError(self._format_connection_error(e)) from e

        if response.status_code not in (200, 302):
            console.print(f"[yellow]Warning: Could not cancel build {build_number}[/yellow]")
            return False

        console.print(f"[green]✓ Cancelled build {build_number}[/green]")
        return True

    def wait_for_build_start(
        self,
        queue_url: str,
        poll_interval: int | None = None,
        timeout_minutes: int = 10,
        max_consecutive_poll_failures: int | None = None,
    ) -> dict[str, Any]:
        """
        Wait for build to start and return build info.

        This is phase 1 of the build process - waiting in queue until build starts.

        Args:
            queue_url: Queue URL from trigger response
            poll_interval: Seconds between polls
            timeout_minutes: Maximum minutes to wait for build to start

        Returns:
            Dict with build_number and job_url

        Raises:
            JenkinsConnectionError: If connection to Jenkins fails
            Exception: If build doesn't start within timeout
        """
        if poll_interval is None:
            poll_interval = self.jenkins_config.poll_interval_seconds

        max_polls = (timeout_minutes * 60) // poll_interval
        max_failures = max_consecutive_poll_failures or self.jenkins_config.max_consecutive_poll_failures
        consecutive_failures = 0

        # Use Progress only in interactive terminals to avoid "Only one live display" error
        use_progress = _is_interactive()
        progress_ctx = (
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
            )
            if use_progress
            else nullcontext()
        )

        with progress_ctx as progress:
            task = None
            if use_progress and progress:
                task = progress.add_task("[cyan]Waiting in Jenkins queue...", total=None)

            for _ in range(max_polls):
                try:
                    queue_item = self.get_queue_item(queue_url)
                    consecutive_failures = 0  # reset on success

                    if "executable" in queue_item:
                        build_number = queue_item["executable"]["number"]
                        job_url = queue_item["executable"]["url"]
                        console.print(f"[green]✓ Build #{build_number} started[/green]")
                        console.print(f"[blue]URL: {job_url}[/blue]")
                        return {
                            "build_number": build_number,
                            "job_url": job_url,
                        }
                    elif queue_item.get("cancelled"):
                        raise Exception("Build was cancelled in queue")
                    else:
                        if use_progress and progress and task is not None:
                            why = queue_item.get("why", "Waiting...")
                            progress.update(
                                task,
                                description=f"[cyan]In queue: {why[:60]}...",
                            )
                except JenkinsConnectionError as e:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        raise JenkinsConnectionError(
                            f"Jenkins unreachable after {max_failures} consecutive poll failures "
                            f"(~{max_failures * poll_interval}s). Last error:\n{e}"
                        ) from e
                    logger.warning(
                        "Transient connection error polling queue (%d/%d): %s",
                        consecutive_failures, max_failures, e,
                    )
                    if use_progress and progress and task is not None:
                        progress.update(
                            task,
                            description=(
                                f"[yellow]Queue poll — connection issue "
                                f"({consecutive_failures}/{max_failures}), retrying..."
                            ),
                        )
                except Exception as e:
                    if "Failed to get queue item" not in str(e):
                        raise
                    # Queue item might have expired, continue trying

                time.sleep(poll_interval)

        raise Exception(
            f"Build did not start within {timeout_minutes} minutes\n" f"Queue URL: {queue_url}"
        )

    def poll_build(
        self,
        queue_url: str,
        poll_interval: int | None = None,
        timeout_minutes: int | None = None,
    ) -> dict[str, Any]:
        """
        Poll build until completion (legacy method that combines both phases).

        Args:
            queue_url: Queue URL from trigger response
            poll_interval: Seconds between polls
            timeout_minutes: Maximum minutes to wait

        Returns:
            Final build data with job_url

        Raises:
            JenkinsConnectionError: If connection to Jenkins fails
            Exception: If build fails or times out
        """
        # Phase 1: Wait for build to start
        start_info = self.wait_for_build_start(queue_url, poll_interval, timeout_minutes=10)

        # Phase 2: Poll until completion
        return self.poll_build_by_number(
            start_info["build_number"],
            poll_interval,
            timeout_minutes,
        )

    def poll_build_by_number(
        self,
        build_number: int,
        poll_interval: int | None = None,
        timeout_minutes: int | None = None,
        max_consecutive_poll_failures: int | None = None,
    ) -> dict[str, Any]:
        """
        Poll an existing build by number until completion.

        Use this when resuming from a previously triggered build.

        Args:
            build_number: Build number to poll
            poll_interval: Seconds between polls
            timeout_minutes: Maximum minutes to wait

        Returns:
            Final build data with job_url

        Raises:
            JenkinsConnectionError: If connection to Jenkins fails
            Exception: If build fails or times out
        """
        if poll_interval is None:
            poll_interval = self.jenkins_config.poll_interval_seconds
        if timeout_minutes is None:
            timeout_minutes = self.jenkins_config.timeout_minutes

        max_polls = (timeout_minutes * 60) // poll_interval
        job_url = f"{self.base_job_url}/{build_number}/"

        # Use Progress only in interactive terminals to avoid "Only one live display" error
        use_progress = _is_interactive()
        progress_ctx = (
            Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
            )
            if use_progress
            else nullcontext()
        )

        max_failures = max_consecutive_poll_failures or self.jenkins_config.max_consecutive_poll_failures
        consecutive_failures = 0

        with progress_ctx as progress:
            task = None
            if use_progress and progress:
                task = progress.add_task(
                    f"[cyan]Resuming poll for build #{build_number}...",
                    total=None,
                )

            for _ in range(max_polls):
                try:
                    build_data = self.get_build(build_number)
                    consecutive_failures = 0  # reset on success
                except JenkinsConnectionError as e:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        raise JenkinsConnectionError(
                            f"Jenkins unreachable after {max_failures} consecutive poll failures "
                            f"(~{max_failures * poll_interval}s). Last error:\n{e}"
                        ) from e
                    logger.warning(
                        "Transient connection error polling build #%d (%d/%d): %s",
                        build_number, consecutive_failures, max_failures, e,
                    )
                    if use_progress and progress and task is not None:
                        progress.update(
                            task,
                            description=(
                                f"[yellow]Build #{build_number} — connection issue "
                                f"({consecutive_failures}/{max_failures}), retrying..."
                            ),
                        )
                    time.sleep(poll_interval)
                    continue

                building = build_data.get("building", True)
                result = build_data.get("result")

                if not building:
                    if result == "SUCCESS":
                        console.print(
                            f"[green]✓ Jenkins build #{build_number} completed successfully[/green]"
                        )
                        console.print(f"[blue]URL: {job_url}[/blue]")
                        return {
                            "build_number": build_number,
                            "job_url": job_url,
                            "result": result,
                            "data": build_data,
                        }
                    else:
                        raise Exception(
                            f"Jenkins build #{build_number} failed with result: {result}\n"
                            f"See: {job_url}"
                        )

                # Still building - update progress if interactive
                if use_progress and progress and task is not None:
                    duration_ms = build_data.get("duration", 0)
                    estimated_ms = build_data.get("estimatedDuration", 0)
                    if estimated_ms > 0:
                        pct = min(100, int(duration_ms / estimated_ms * 100))
                        progress.update(
                            task,
                            description=f"[cyan]Build #{build_number} running ({pct}%) | {job_url}",
                        )
                    else:
                        progress.update(
                            task,
                            description=f"[cyan]Build #{build_number} running... | {job_url}",
                        )

                time.sleep(poll_interval)

        raise Exception(
            f"Jenkins build timed out after {timeout_minutes} minutes\n" f"See: {job_url}"
        )

    def trigger_and_wait(
        self,
        release_version: str,
        ticket: str,
        extra_params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Trigger build and wait for completion.

        Args:
            release_version: Release version
            ticket: Jira ticket
            extra_params: Additional parameters

        Returns:
            Final build data with job_url
        """
        trigger_result = self.trigger_build(release_version, ticket, extra_params)
        return self.poll_build(trigger_result["queue_url"])
