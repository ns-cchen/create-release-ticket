# Create Release Ticket

CLI tool (with optional web UI) to automate the QueryService deployment workflow.

## What it does

Automates 7 steps end-to-end:

| Step | Action |
|------|--------|
| 1 | Parse build version → derive branch names |
| 2 | Fetch commits between branches → extract Jira ticket IDs |
| 3 | Create promote ticket in Jira |
| 4 | Trigger GitHub promotion workflow → wait for completion (~10 min) |
| 5 | Trigger Jenkins devint deployment → wait for completion (~42 min) |
| 6 | Create deployment ticket in Jira |
| 7 | Close the promote ticket |

The workflow is resumable — if interrupted at any step, run with `--resume` to pick up where it left off.

## Prerequisites

- Python 3.12+
- [mise](https://mise.jdx.dev/) for version management
- Poetry (installed via mise)
- Node.js 22 (only required for the web UI)

## Setup

### 1. Clone and install

```bash
git clone https://github.com/ns-cchen/create-release-ticket.git
cd create-release-ticket
mise install
poetry install
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env with your credentials
```

### Required credentials

| Variable | Description | How to get it |
|----------|-------------|---------------|
| `JIRA_EMAIL` | Your Atlassian account email | Your login email |
| `JIRA_API_TOKEN` | Jira API token | [Atlassian account settings → Security → API tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |
| `JIRA_USER_ID` | Your Jira account ID | See below |
| `GITHUB_PAT` | GitHub Personal Access Token | [GitHub → Settings → Developer settings → Personal access tokens](https://github.com/settings/tokens) — needs `repo` + `workflow` scopes |
| `JENKINS_URL` | Jenkins base URL | Ask your team |
| `JENKINS_USER` | Jenkins username | Usually your email address |
| `JENKINS_API_TOKEN` | Jenkins API token | Jenkins → top-right profile → Configure → API Token → Add new Token |

#### How to find your Jira User ID

Open this URL while logged in to Jira:

```
https://<your-jira-domain>/rest/api/3/myself
```

Copy the `accountId` value from the JSON response.

### 3. Validate credentials

```bash
poetry run create-release-ticket validate
```

All three services (Jira, GitHub, Jenkins) should show ✓ before proceeding.

## CLI Usage

### Run the full workflow

```bash
poetry run create-release-ticket run \
  --build-version queryservice-release-2025.12.2.0.18496 \
  --rollback-version queryservice-release-2025.12.1.0.18438
```

### Resume an interrupted run

```bash
poetry run create-release-ticket run --resume
```

### Dry run (preview without executing)

```bash
poetry run create-release-ticket run --dry-run \
  --build-version queryservice-release-2025.12.2.0.18496 \
  --rollback-version queryservice-release-2025.12.1.0.18438
```

### Stop after a specific step

Useful for staged deployments or testing individual steps:

```bash
# Stop after GitHub workflow completes (before Jenkins)
poetry run create-release-ticket run --stop-after github ...

# Stop after Jenkins (before creating deployment ticket)
poetry run create-release-ticket run --stop-after jenkins ...
```

### Use an existing build (skip triggering)

If Jenkins or the GitHub workflow was already triggered manually:

```bash
poetry run create-release-ticket run \
  --jenkins-build-number 1234 \
  --jenkins-job-url https://jenkins.example.com/job/my-job/1234/ \
  ...
```

### All options

```
Options:
  -b, --build-version TEXT             Build version (queryservice-release-YYYY.MM.W.P.DRONE)
  -r, --rollback-version TEXT          Rollback version
  --ref TEXT                           Git ref for GitHub workflow (default: develop)
  --previous-branch TEXT               Override previous branch for commit comparison
  --jira-ids TEXT                      Comma-separated Jira IDs (override auto-detection)
  --previous-deployment-ticket TEXT    Previous deployment ticket to relate to (e.g. ENG-857076)
  --dry-run                            Preview all actions without executing
  --stop-after TEXT                    Stop after step: 1-7, or keyword (github/jenkins/deploy)
  --jenkins-build-number INTEGER       Use existing Jenkins build number
  --jenkins-job-url TEXT               Use existing Jenkins job URL
  --github-run-id INTEGER              Use existing GitHub workflow run ID
  --resume                             Resume from last interrupted run
  -v, --verbose                        Enable verbose logging
  --version                            Show version and exit
  --help                               Show this message and exit
```

### Other commands

```bash
# Show current workflow state
poetry run create-release-ticket show-state

# Clean up resources from a failed run (closes tickets, cancels builds)
poetry run create-release-ticket cleanup

# Manually close a Jira ticket
poetry run create-release-ticket close-ticket ENG-123456
```

## Web UI

The web UI provides a browser-based dashboard for managing releases.

### Start the UI

```bash
make install   # first time only — installs frontend dependencies
make dev
```

- Backend: http://localhost:5004
- Frontend: http://localhost:3005

The web UI reads the same `.env` credentials. All workflow operations are available through the browser.

### Individual servers

```bash
make dev-backend    # backend only
make dev-frontend   # frontend only
```

## Configuration

`config.yaml` contains team-wide settings (Jira project IDs, Jenkins job parameters, GitHub repo).
Personal settings go in `.env` and are never committed:

| Env var | Required | Purpose |
|---------|----------|---------|
| `JIRA_USER_ID` | Yes | Your personal Jira account ID |
| `JENKINS_URL` | Yes | Jenkins base URL |
| `GITHUB_NOTIFY_EMAILS` | No | Space-separated emails for workflow notifications |

`config.yaml` values are shared defaults. Override any field there for your local environment.

## Version format

Build versions follow this pattern:

```
queryservice-release-YYYY.MM.W.P.DRONE
```

Example: `queryservice-release-2026.1.5.0.18914`

The previous branch is auto-calculated by decrementing the week number (handles month/year boundaries automatically).
