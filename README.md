# Create Release Ticket

CLI tool to automate QueryService deployment workflow.

## Features

- **Automated Ticket Creation**: Creates promote and deployment tickets in Jira
- **GitHub Workflow Integration**: Triggers build promotion workflow
- **Jenkins Integration**: Triggers devint deployment and waits for completion
- **Auto-detect Jira IDs**: Extracts ticket numbers from commit messages
- **Resume Support**: Can resume interrupted runs
- **Cleanup on Error**: Offers to clean up created resources on failure
- **Dry Run Mode**: Preview all actions before executing

## Installation

### Prerequisites

- Python 3.12+
- [mise](https://mise.jdx.dev/) for version management
- Poetry for dependency management

### Setup

1. Clone the repository and navigate to the directory:

  ```bash
  cd create-release-ticket
  ```

1. Install mise and activate:

  ```bash
  mise install
  mise activate
  ```

1. Install dependencies:

  ```bash
  poetry install
  ```

1. Copy and configure environment variables:

  ```bash
  cp .env.example .env
  # Edit .env with your credentials
  ```

1. (Optional) Customize configuration:

  ```bash
  # Edit config.yaml to change default values
  ```

## Configuration

### Environment Variables (.env)

```bash
# Jira
JIRA_EMAIL=your-email@netskope.com
JIRA_API_TOKEN=your-jira-api-token

# GitHub
GITHUB_PAT=ghp_your-github-personal-access-token

# Jenkins
JENKINS_URL=https://cdjenkins.betaskope.iad0.netskope.com
JENKINS_USER=your-jenkins-username
JENKINS_API_TOKEN=your-jenkins-api-token
```

### Application Config (config.yaml)

Customize default values for:

- Jira project/component IDs
- GitHub workflow settings
- Jenkins job parameters
- Retry settings

## Usage

### Quickstart

Validate credentials:

```bash
poetry run create-release-ticket validate
```

Run the full workflow (recommended, verbose):

```bash
poetry run create-release-ticket run \
  --build-version queryservice-release-YYYY.MM.W.P.DRONE \
  --rollback-version queryservice-release-YYYY.MM.W.P.DRONE \
  --previous-branch queryservice-release-YYYY.MM.W \
  --ref queryservice-release-YYYY.MM.W \
  --previous-deployment-ticket ENG-857076 \
  -v
```

### Dry Run (No Side Effects)

```bash
poetry run create-release-ticket run \
  --build-version queryservice-release-YYYY.MM.W.P.DRONE \
  --rollback-version queryservice-release-YYYY.MM.W.P.DRONE \
  --dry-run
```

### Resume / Staged Run

Stop after GitHub (so you can review before Jenkins):

```bash
poetry run create-release-ticket run \
  --build-version queryservice-release-YYYY.MM.W.P.DRONE \
  --rollback-version queryservice-release-YYYY.MM.W.P.DRONE \
  --previous-branch queryservice-release-YYYY.MM.W \
  --ref queryservice-release-YYYY.MM.W \
  --stop-after github
```

Resume later:

```bash
poetry run create-release-ticket run --resume
```

If Jenkins was run manually and you want to continue without re-triggering Jenkins:

```bash
poetry run create-release-ticket run \
  --resume \
  --jenkins-build-number 1729 \
  --jenkins-job-url https://cdjenkins.betaskope.iad0.netskope.com/job/one_button_queryservice/1729/
```

### Overrides

```bash
# Override Jira IDs (skip auto-detection)
poetry run create-release-ticket run \
  --build-version queryservice-release-YYYY.MM.W.P.DRONE \
  --rollback-version queryservice-release-YYYY.MM.W.P.DRONE \
  --jira-ids "DINT-1234,EP-5678,ENG-9999"
```

### Cleanup / Utilities

```bash
poetry run create-release-ticket cleanup
poetry run create-release-ticket show-state
```

Close a ticket (Resolve Issue). ENG workflow may require extra required fields:

```bash
poetry run create-release-ticket close-ticket ENG-123456 --fix-version 202601.4 --sub-component queryservice
```

## Workflow Steps

The tool executes the following steps:

1. **Parse Version** - Extract branch info from build version
2. **Fetch Commits** - Compare branches and extract Jira IDs from commit messages
3. **Create Promote Ticket** - Create Jira ticket for build promotion
4. **Trigger GitHub Workflow** - Dispatch promote workflow and wait (~10 min)
5. **Trigger Jenkins** - Start devint deployment and wait (~42 min)
6. **Create Deployment Ticket** - Create Jira deployment ticket with all info
7. **Close Promote Ticket** - Transition promote ticket via Resolve Issue (Resolution=Fixed)

## Error Handling

On error, the CLI will prompt:

- **c** - Clean up (close tickets, cancel Jenkins)
- **k** - Keep resources and exit
- **r** - Retry from last step

On Ctrl+C interrupt:

- **c** - Clean up
- **k** - Keep resources

## Logs

Logs are saved to `./logs/YYYY-MM-DD_HHMMSS.log`

## Development

```bash
# Run linting
poetry run ruff check src/

# Run tests
poetry run pytest

# Format code
poetry run ruff format src/
```

## Version Format

Build version format: `queryservice-release-YYYY.MM.W.P.DRONE`

- `YYYY` - Year
- `MM` - Month
- `W` - Week of month (1-4)
- `P` - Patch number
- `DRONE` - Drone build number

Example: `queryservice-release-2025.12.2.0.18496`
