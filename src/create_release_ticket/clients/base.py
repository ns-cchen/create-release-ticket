"""Base HTTP client with retry logic."""

from __future__ import annotations

import time
from typing import Any

import httpx
from rich.console import Console

from create_release_ticket.config import get_app_config

console = Console()


class BaseClient:
    """Base HTTP client with automatic retry on failure."""

    def __init__(
        self,
        base_url: str,
        auth: tuple[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.headers = headers or {}
        self.timeout = timeout
        self.config = get_app_config()

    def _make_request(
        self,
        method: str,
        endpoint: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retry_on_status: tuple[int, ...] = (500, 502, 503, 504),
    ) -> httpx.Response:
        """Make HTTP request with retry logic."""
        url = f"{self.base_url}{endpoint}"
        request_headers = {**self.headers, **(headers or {})}

        max_attempts = self.config.retry.max_attempts
        backoff = self.config.retry.backoff_seconds

        last_exception: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.request(
                        method=method,
                        url=url,
                        json=json,
                        data=data,
                        params=params,
                        headers=request_headers,
                        auth=self.auth,
                    )

                    # Check if we should retry on this status code
                    if response.status_code in retry_on_status and attempt < max_attempts:
                        console.print(
                            f"[yellow]Request failed with status {response.status_code}, "
                            f"retrying ({attempt}/{max_attempts})...[/yellow]"
                        )
                        time.sleep(backoff * attempt)
                        continue

                    return response

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < max_attempts:
                    console.print(
                        f"[yellow]Request failed: {e}, "
                        f"retrying ({attempt}/{max_attempts})...[/yellow]"
                    )
                    time.sleep(backoff * attempt)
                    continue
                raise

        # This shouldn't be reached, but just in case
        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected error in retry logic")

    def get(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make GET request."""
        return self._make_request("GET", endpoint, params=params, headers=headers)

    def post(
        self,
        endpoint: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make POST request."""
        return self._make_request("POST", endpoint, json=json, data=data, headers=headers)

    def put(
        self,
        endpoint: str,
        *,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make PUT request."""
        return self._make_request("PUT", endpoint, json=json, data=data, headers=headers)

    def delete(
        self,
        endpoint: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Make DELETE request."""
        return self._make_request("DELETE", endpoint, headers=headers)
