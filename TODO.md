# Create Release Ticket - TODO

## Status: Pending UI Development

This project is currently a CLI-only tool. It needs a Web UI before it can be integrated into SkopeHub portal.

## Planned Work

1. [ ] Design Web UI for the release workflow
2. [ ] Create FastAPI backend to wrap CLI functionality
3. [ ] Create Next.js frontend with form-based interface
4. [ ] Integrate with SkopeHub portal

## Current Usage (CLI)

```bash
cd apps/create-release-ticket
poetry install
poetry run create-release-ticket --help
```

## Target Port

When UI is ready, it will use:
- Frontend: 3005 (defined in ports.env as RELEASE_TICKET_FRONTEND_PORT)
