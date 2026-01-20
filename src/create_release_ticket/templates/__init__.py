"""Ticket templates package."""

from create_release_ticket.templates.deployment_ticket import build_deployment_ticket_payload
from create_release_ticket.templates.promote_ticket import build_promote_ticket_payload

__all__ = ["build_deployment_ticket_payload", "build_promote_ticket_payload"]
