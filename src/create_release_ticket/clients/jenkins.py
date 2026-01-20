"""Jenkins API client."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from create_release_ticket.clients.base import BaseClient
from create_release_ticket.config import get_app_config, get_settings

console = Console()


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
            console.print(f"[red]✗ Jenkins authentication failed: {e}[/red]")
            return False

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

        response = self.post(
            f"/job/{config.job_name}/buildWithParameters",
            data=params,
        )

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
        """
        # Extract queue ID from URL
        # Queue URL format: https://jenkins.../queue/item/12345/
        api_url = f"{queue_url}api/json"

        response = self.get(api_url.replace(self.base_url, ""))
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
        """
        response = self.get(
            f"/job/{self.jenkins_config.job_name}/{build_number}/api/json"
        )

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
        """
        response = self.post(
            f"/job/{self.jenkins_config.job_name}/{build_number}/stop"
        )

        if response.status_code not in (200, 302):
            console.print(f"[yellow]Warning: Could not cancel build {build_number}[/yellow]")
            return False

        console.print(f"[green]✓ Cancelled build {build_number}[/green]")
        return True

    def poll_build(
        self,
        queue_url: str,
        poll_interval: int | None = None,
        timeout_minutes: int | None = None,
    ) -> dict[str, Any]:
        """
        Poll build until completion.

        Args:
            queue_url: Queue URL from trigger response
            poll_interval: Seconds between polls
            timeout_minutes: Maximum minutes to wait

        Returns:
            Final build data with job_url

        Raises:
            Exception if build fails or times out
        """
        if poll_interval is None:
            poll_interval = self.jenkins_config.poll_interval_seconds
        if timeout_minutes is None:
            timeout_minutes = self.jenkins_config.timeout_minutes

        max_polls = (timeout_minutes * 60) // poll_interval
        build_number: int | None = None
        job_url: str | None = None

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]Waiting in Jenkins queue...", total=None)

            for poll_count in range(max_polls):
                # First, wait for the build to start (get out of queue)
                if build_number is None:
                    try:
                        queue_item = self.get_queue_item(queue_url)

                        if "executable" in queue_item:
                            build_number = queue_item["executable"]["number"]
                            job_url = queue_item["executable"]["url"]
                            progress.update(
                                task,
                                description=f"[cyan]Build #{build_number} started | {job_url}",
                            )
                        elif queue_item.get("cancelled"):
                            raise Exception("Build was cancelled in queue")
                        else:
                            why = queue_item.get("why", "Waiting...")
                            progress.update(
                                task,
                                description=f"[cyan]In queue: {why[:50]}...",
                            )
                            time.sleep(poll_interval)
                            continue
                    except Exception as e:
                        if "Failed to get queue item" in str(e):
                            # Queue item might have expired, try to find build
                            time.sleep(poll_interval)
                            continue
                        raise

                # Now poll the build status
                if build_number is not None:
                    build_data = self.get_build(build_number)
                    building = build_data.get("building", True)
                    result = build_data.get("result")

                    if not building:
                        if result == "SUCCESS":
                            console.print(f"[green]✓ Jenkins build #{build_number} completed successfully[/green]")
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

                    # Still building
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
            f"Jenkins build timed out after {timeout_minutes} minutes\n"
            f"See: {job_url or queue_url}"
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
