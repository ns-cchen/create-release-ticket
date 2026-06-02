# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment Management (MANDATORY)

- **MUST use mise** to manage ALL language runtimes and tools (Python, Node.js, Poetry, Go, etc.)
- **NEVER use Homebrew, apt, or system package managers** for language runtimes
- **NEVER create `.venv` using system Python** — always use `mise`-managed Python
- When creating or recreating a `.venv`, use: `~/.local/share/mise/installs/python/<version>/bin/python3 -m venv .venv`
- Run `mise install` to set up the environment before any development work

## Commands

```bash
# Install dependencies
poetry install

# Run the CLI
poetry run create-release-ticket <command>

# Run the Web UI (backend + frontend)
make dev

# Lint
poetry run ruff check src/ backend/

# Format
poetry run ruff format src/ backend/

# Run all tests
poetry run pytest

# Run a single test file
poetry run pytest tests/test_promote_ticket.py -v

# Run tests with specific pattern
poetry run pytest -k "test_name_pattern" -v

# Run frontend tests
cd frontend && npm test
```

## Architecture

This project has two interfaces for automating QueryService deployment workflows:
1. **CLI** - Original command-line tool
2. **Web UI** - FastAPI backend + React frontend for browser-based workflows

### Layered Structure

```
src/create_release_ticket/     # CLI and shared business logic
├── cli.py              # Click CLI commands and workflow orchestration
├── config.py           # Pydantic Settings (env vars + config.yaml)
├── state.py            # RunState persistence with RunStep enum
├── utils.py            # Version parsing, Jira ID extraction from commits
├── rollback.py         # Cleanup on error/interrupt with user prompts
├── clients/
│   ├── base.py         # Base HTTP client with exponential backoff retry
│   ├── jira.py         # Jira REST API (create/transition/link issues)
│   ├── github.py       # GitHub API (branch compare, workflow dispatch)
│   └── jenkins.py      # Jenkins API (trigger builds, poll status)
└── templates/
    ├── promote_ticket.py      # Jira payload builder for promote tickets
    └── deployment_ticket.py   # Jira payload builder with ADF formatting

backend/                       # Web UI backend (FastAPI)
├── main.py             # FastAPI app with CORS and routers
├── models/schemas.py   # Pydantic models for API requests/responses
├── routers/releases.py # REST endpoints for release CRUD
└── services/
    ├── workflow_service.py    # Async workflow orchestration
    └── websocket_manager.py   # Real-time step progress updates

frontend/                      # Web UI frontend (React + TypeScript)
├── src/
│   ├── components/     # StepProgress, ReleaseCard, SearchFilter
│   ├── pages/          # ReleaseList, ReleaseDetail, CreateRelease
│   ├── stores/         # Zustand state management
│   └── lib/            # API client, validation utilities
└── vite.config.ts
```

### Key Patterns

- **State Machine**: `RunState` tracks progress through `RunStep` stages, persisted to JSON for resume capability
- **Split-Phase Execution**: GitHub workflow and Jenkins build are split into trigger + poll phases with intermediate states (`TRIGGERED_GITHUB_WORKFLOW`, `TRIGGERED_JENKINS`) to prevent duplicate triggers on resume
- **Retry with Backoff**: `BaseClient` implements configurable exponential backoff (default 3 attempts)
- **Staged Execution**: `--stop-after` flag (CLI) or `stop_after` param (API) allows pausing workflow between steps

### Configuration Hierarchy (highest to lowest priority)

1. **Environment variables** (`.env`) - Credentials only
2. **config.yaml** - Jira project IDs, GitHub repo, Jenkins job params
3. **Code defaults** in `config.py` dataclasses

### Workflow Steps

1. Parse version → extract branch names
2. Fetch commits → compare branches, extract Jira IDs from messages
3. Create promote ticket → Jira ENG project
4. Trigger GitHub workflow → save run_id → wait for completion (~10 min)
5. Trigger Jenkins build → save build_number → wait for completion (~42 min)
6. Create deployment ticket → Jira DINT project
7. Close promote ticket → Resolve Issue transition

### Split-Phase Architecture (Steps 4 & 5)

To prevent duplicate triggers when resuming an interrupted workflow:

```
Step 4 (GitHub):
├── 4a: Trigger workflow (skip if github_workflow_run_id exists)
│       └── Save run_id immediately → TRIGGERED_GITHUB_WORKFLOW
└── 4b: Poll for completion (can resume from here)
        └── Save → GITHUB_WORKFLOW_COMPLETED

Step 5 (Jenkins):
├── 5a: Trigger build (skip if jenkins_build_number exists)
│       └── Save build_number immediately → TRIGGERED_JENKINS
└── 5b: Poll for completion (can resume from here)
        └── Save → JENKINS_COMPLETED
```

The guard pattern `if not state.xxx_id:` ensures external actions are never duplicated.

### Jira Template Notes

- `templates/promote_ticket.py` and `templates/deployment_ticket.py` use Atlassian Document Format (ADF) for rich text fields
- Some custom fields are "resolve-screen-only" (can only be set during Resolve Issue transition, not create)
- ENG workflow requires `fix_version` and `sub_component` when resolving

### Error Recovery

On failure or Ctrl+C, user is prompted:
- **c** - Cleanup (close tickets, cancel Jenkins builds)
- **k** - Keep resources (can resume later with `--resume`)
- **r** - Retry from last completed step

### Version Format

Build version: `queryservice-release-YYYY.MM.W.P.DRONE`
- Example: `queryservice-release-2026.1.5.0.18914`
- Previous branch auto-calculated by decrementing week (handles month/year boundaries)

## Web UI

### Backend (FastAPI)

- **`workflow_service.py`** - Main orchestration logic, reuses CLI clients
- **WebSocket updates** - Real-time step progress via `ws_manager`
- **Dry-run mode** - Uses fake clients from `tests/fakes/clients.py`
- **State persistence** - JSON files in `~/.create-release-ticket/releases/`

### Frontend (React + TypeScript)

- **Zustand** for state management (releaseStore)
- **WebSocket** for real-time step progress updates
- **StepProgress** component renders links for completed steps:
  - Step 3: Promote ticket (Jira)
  - Step 4: GitHub workflow run
  - Step 5: Jenkins build
  - Step 6: Deployment ticket (Jira)

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/releases` | List all releases |
| POST | `/api/releases` | Create new release |
| GET | `/api/releases/{id}` | Get release details |
| POST | `/api/releases/{id}/resume` | Resume paused release |
| POST | `/api/releases/{id}/cleanup` | Clean up failed release |
| DELETE | `/api/releases/purge` | Delete completed releases |
| WS | `/api/releases/{id}/ws` | WebSocket for live updates |
