"""Test datetime imports are correct across all modules.

Regression test for: datetime.UTC AttributeError

When using `from datetime import datetime`, the name `datetime` refers
to the class, not the module. So `datetime.UTC` fails because the
class doesn't have a UTC attribute - use `timezone.utc` instead.
"""


class TestDatetimeTimezoneUsage:
    """Verify timezone.utc is used instead of datetime.UTC."""

    def test_deployment_ticket_can_build_payload(self):
        """deployment_ticket module should not raise AttributeError on timezone.

        Regression test: previously used `datetime.UTC` which fails when
        datetime is imported as `from datetime import datetime`.
        """
        from create_release_ticket.templates.deployment_ticket import (
            build_deployment_ticket_payload,
        )
        # Should not raise: AttributeError: 'datetime.datetime' has no attribute 'UTC'
        payload = build_deployment_ticket_payload(
            build_version="queryservice-release-2026.1.1.0.18000",
            rollback_version="queryservice-release-2026.1.0.0.17900",
            current_branch="queryservice-release-2026.1.1",
            previous_branch="queryservice-release-2026.1.0",
            promote_ticket_key="ENG-123456",
            devint_job_url="https://jenkins.example.com/job/123",
            jira_ids=["DINT-1234"],
        )
        assert payload is not None
        assert "fields" in payload

    def test_datetime_now_with_timezone_utc(self):
        """Verify the correct pattern for UTC timestamps.

        This is the pattern used in github.py and should not raise errors.
        """
        from datetime import datetime, timezone

        # This is the correct way (used after fix)
        now = datetime.now(timezone.utc)
        assert now.tzinfo is timezone.utc

        # Format as ISO string (what github.py does)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert timestamp.endswith("Z")
