# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
poetry install

# Run the CLI
poetry run create-release-ticket <command>

# Lint
poetry run ruff check src/

# Format
poetry run ruff format src/

# Run all tests
poetry run pytest

# Run a single test file
poetry run pytest tests/test_promote_ticket.py -v

# Run tests with specific pattern
poetry run pytest -k "test_name_pattern" -v
```

## Architecture

This is a CLI tool for automating QueryService deployment workflows, integrating with Jira, GitHub, and Jenkins.

### Layered Structure

```
src/create_release_ticket/
├── cli.py              # Click CLI commands and workflow orchestration
├── config.py           # Pydantic Settings (env vars + config.yaml)
├── state.py            # RunState persistence with RunStep enum (10 steps)
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
```

### Key Patterns

- **State Machine**: `RunState` tracks progress through 10 `RunStep` stages, persisted to `.create-release-ticket-state.json` for resume capability
- **Retry with Backoff**: `BaseClient` implements configurable exponential backoff (default 3 attempts)
- **Staged Execution**: `--stop-after` flag allows pausing workflow between steps (e.g., after GitHub before Jenkins)

### Configuration Hierarchy (highest to lowest priority)

1. **Environment variables** (`.env`) - Credentials only
2. **config.yaml** - Jira project IDs, GitHub repo, Jenkins job params
3. **Code defaults** in `config.py` dataclasses

### Workflow Steps (run command)

1. Parse version → extract branch names
2. Fetch commits → compare branches, extract Jira IDs from messages
3. Create promote ticket → Jira ENG project
4. Trigger GitHub workflow → wait ~10 min
5. Trigger Jenkins build → wait ~42 min
6. Create deployment ticket → Jira DINT project
7. Close promote ticket → Resolve Issue transition

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
