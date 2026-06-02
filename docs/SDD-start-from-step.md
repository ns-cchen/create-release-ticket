# SDD: Start From Step — Flexible Workflow Entry Point

## Problem

Currently, the create release workflow **always starts from step 1** regardless of what the user has already done externally. The "Stop After Step" feature controls where the workflow pauses, but there's no way to tell the system where to **start**.

**Real-world scenario**: A user has already created a promote ticket (DINT-2057) and triggered a GitHub workflow externally. They want the app to monitor the existing workflow and continue from there — but the app forces them through steps 1-3 again, creating duplicate tickets.

## Goals

1. **Replace "Stop After Step"** with **"Start From Step"** — workflow always runs to completion
2. **Dynamic artifact inputs** — when starting from step N, require artifacts from steps 1 through N-1
3. **Resume preserves state** — resuming a failed/paused release continues from the last successful step with all prior artifacts intact

## Workflow Steps Reference

| Step | Name | Produces |
|------|------|----------|
| 1 | Parse Version | `current_branch`, `previous_branch` |
| 2 | Fetch Commits | `jira_ids[]` |
| 3 | Create Promote Ticket | `promote_ticket_key` |
| 4 | GitHub Workflow | `github_workflow_run_id` |
| 5 | Jenkins Build | `jenkins_build_number`, `jenkins_job_url` |
| 6 | Create Deployment Ticket | `deployment_ticket_key` |
| 7 | Close Promote Ticket | _(resolves promote ticket)_ |

## Design

### 1. Create Release — "Start From Step"

Replace `stop_after: int` with `start_from_step: int` (default: 1).

When `start_from_step > 1`, the user must provide artifacts produced by prior steps:

| Start From | Required Artifacts |
|---|---|
| Step 1 | _(none — normal flow)_ |
| Step 2 | _(none — branches auto-derived from build_version)_ |
| Step 3 | _(none — jira_ids auto-fetched or user-provided)_ |
| Step 4 | `promote_ticket_key` |
| Step 5 | `promote_ticket_key`, `github_workflow_run_id` |
| Step 6 | `promote_ticket_key`, `github_workflow_run_id`, `jenkins_build_number`, `jenkins_job_url` |
| Step 7 | `promote_ticket_key`, `deployment_ticket_key` |

**Note**: Steps 1-2 are always auto-derivable from `build_version`, so starting from step 3 or 4 doesn't require manually providing branches or jira_ids (though the user can still override them).

### 2. Backend Schema Changes

#### `ReleaseCreate` (replace `stop_after`)

```python
class ReleaseCreate(BaseModel):
    # ... existing required fields ...
    build_version: str
    rollback_version: str
    ref: str = "develop"

    # ... existing optional fields ...
    previous_branch: str | None = None
    jira_ids: list[str] | None = None
    previous_deployment_ticket: str | None = None
    dry_run: bool = False

    # NEW: Replace stop_after with start_from_step
    start_from_step: int = Field(default=1, ge=1, le=7)

    # NEW: Pre-existing artifacts (required depending on start_from_step)
    promote_ticket_key: str | None = None       # Required if start_from_step >= 4
    github_workflow_run_id: int | None = None    # Required if start_from_step >= 5
    jenkins_build_number: int | None = None      # Required if start_from_step >= 6
    jenkins_job_url: str | None = None           # Required if start_from_step >= 6
    deployment_ticket_key: str | None = None     # Required if start_from_step >= 7
```

Add a Pydantic `model_validator` to enforce required artifacts based on `start_from_step`:

```python
@model_validator(mode='after')
def validate_start_from_artifacts(self):
    if self.start_from_step >= 4 and not self.promote_ticket_key:
        raise ValueError("promote_ticket_key required when starting from step 4+")
    if self.start_from_step >= 5 and not self.github_workflow_run_id:
        raise ValueError("github_workflow_run_id required when starting from step 5+")
    if self.start_from_step >= 6 and (not self.jenkins_build_number or not self.jenkins_job_url):
        raise ValueError("jenkins_build_number and jenkins_job_url required when starting from step 6+")
    if self.start_from_step >= 7 and not self.deployment_ticket_key:
        raise ValueError("deployment_ticket_key required when starting from step 7+")
    return self
```

#### `ReleaseResumeRequest` (simplify — remove `stop_after`)

```python
class ReleaseResumeRequest(BaseModel):
    jenkins_build_number: int | None = None
    jenkins_job_url: str | None = None
```

### 3. Backend Workflow Changes

#### `create_release()` in `workflow_service.py`

When `start_from_step > 1`:
1. Parse version immediately to populate `current_branch` / `previous_branch`
2. Pre-populate state with provided artifacts
3. Set `current_step` to the step *before* `start_from_step` so the workflow begins at the right place

```python
# Map start_from_step to the RunStep that should be "already completed"
STEP_TO_RUNSTEP = {
    1: RunStep.NOT_STARTED,
    2: RunStep.PARSED_VERSION,
    3: RunStep.FETCHED_COMMITS,
    4: RunStep.CREATED_PROMOTE_TICKET,
    5: RunStep.GITHUB_WORKFLOW_COMPLETED,  # Skip trigger+poll, start fresh at step 5
    6: RunStep.JENKINS_COMPLETED,
    7: RunStep.CREATED_DEPLOYMENT_TICKET,
}
```

Special cases:
- **Start from 5**: Set `current_step = GITHUB_WORKFLOW_COMPLETED` (not `TRIGGERED`). The user already has a completed workflow, so skip all of step 4.
- **Start from 4 with `github_workflow_run_id`**: Set `current_step = TRIGGERED_GITHUB_WORKFLOW` and `github_workflow_run_id` on state. The workflow will skip the trigger (4a) and go straight to polling (4b).

Wait — the user might start from step 4 to **monitor** an in-progress GitHub workflow. In that case:
- `start_from_step = 4` + `github_workflow_run_id` provided → skip trigger, poll existing run
- `start_from_step = 4` without `github_workflow_run_id` → trigger a new workflow

So `github_workflow_run_id` at step 4 is **optional** (trigger new vs. monitor existing):

| Start From | `github_workflow_run_id` | Behavior |
|---|---|---|
| Step 4 | not provided | Trigger new GitHub workflow |
| Step 4 | provided | Skip trigger, poll existing run |
| Step 5+ | required | Must have completed workflow |

Similarly for `jenkins_build_number` at step 5:

| Start From | `jenkins_build_number` | Behavior |
|---|---|---|
| Step 5 | not provided | Trigger new Jenkins build |
| Step 5 | provided | Skip trigger, poll existing build |
| Step 6+ | required | Must have completed build |

Updated artifact requirements:

| Start From | Required | Optional (skip trigger) |
|---|---|---|
| 1-3 | _(none)_ | — |
| 4 | `promote_ticket_key` | `github_workflow_run_id` |
| 5 | `promote_ticket_key`, `github_workflow_run_id` | `jenkins_build_number`, `jenkins_job_url` |
| 6 | `promote_ticket_key`, `jenkins_build_number`, `jenkins_job_url` | — |
| 7 | `promote_ticket_key`, `deployment_ticket_key` | — |

#### `resume_release()` — simplify

Remove `stop_after` support. On resume, the workflow always runs to completion from the current step.

#### Remove `maybe_stop()` from `_run_workflow()`

The `maybe_stop()` function and all `stop_after` logic can be removed since the workflow always runs to completion.

### 4. Frontend Changes

#### Types (`types/api.ts`)

```typescript
export interface ReleaseCreateInput {
  build_version: string
  rollback_version: string
  ref?: string
  previous_branch?: string
  jira_ids?: string[]
  previous_deployment_ticket?: string
  dry_run?: boolean

  // NEW: Replace stop_after
  start_from_step?: number  // 1-7, default 1

  // NEW: Pre-existing artifacts
  promote_ticket_key?: string
  github_workflow_run_id?: number
  jenkins_build_number?: number
  jenkins_job_url?: string
  deployment_ticket_key?: string
}

export interface ReleaseResumeInput {
  jenkins_build_number?: number
  jenkins_job_url?: string
  // stop_after removed
}
```

#### Create Form (`NewRelease.tsx`)

Replace "Stop After Step" dropdown with **"Start From Step"** dropdown:

```
Start From Step: [Step 1: Parse Version (default)]
                  Step 2: Fetch Commits
                  Step 3: Create Promote Ticket
                  Step 4: GitHub Workflow
                  Step 5: Jenkins Build
                  Step 6: Create Deployment Ticket
                  Step 7: Close Promote Ticket
```

**Dynamic artifact fields**: Show/hide input fields based on selected step:

- **Start from 4+**: Show "Promote Ticket Key" input (required)
- **Start from 4**: Show "GitHub Workflow Run ID" input (optional — leave empty to trigger new)
- **Start from 5+**: Show "GitHub Workflow Run ID" input (required)
- **Start from 5**: Show "Jenkins Build Number" + "Jenkins Job URL" inputs (optional — leave empty to trigger new)
- **Start from 6+**: Show "Jenkins Build Number" + "Jenkins Job URL" inputs (required)
- **Start from 7+**: Show "Deployment Ticket Key" input (required)

For `github_workflow_run_id`, accept either:
- A numeric ID: `21885316894`
- A full URL: `https://github.com/netSkope/query-engine/actions/runs/21885316894` → parse to extract the numeric run ID

#### Resume Form (`ReleaseDetail.tsx`)

Simplify: remove "Stop After Step" dropdown from resume form. Keep only Jenkins override fields.

### 5. API Response Changes

#### `ReleaseResponse` — replace `stop_after` with `start_from_step`

```python
class ReleaseResponse(BaseModel):
    # ... existing fields ...
    start_from_step: int = 1   # NEW (replaces stop_after)
    dry_run: bool = False
```

### 6. State Persistence

The JSON file for each release stores extra metadata. Replace `stop_after` and `paused` with `start_from_step`:

```json
{
  "_id": "abc12345",
  "dry_run": false,
  "start_from_step": 4,
  "build_version": "...",
  "current_step": "triggered_github_workflow",
  "promote_ticket_key": "DINT-2057",
  "github_workflow_run_id": 21885316894,
  ...
}
```

Remove `paused` field — workflow never pauses, only errors or completes.

### 7. Status Simplification

Current statuses: `not_started | in_progress | paused | completed | error`

New statuses: `not_started | in_progress | completed | error`

Remove `paused` — it no longer exists since `stop_after` is gone.

## Migration

- Existing release JSON files with `stop_after` / `paused` fields: treat as backward-compatible. On load, ignore `stop_after`. If `paused`, treat as `in_progress` (resume will run to completion).

## Files to Modify

| File | Changes |
|------|---------|
| `backend/models/schemas.py` | Replace `stop_after` with `start_from_step` + artifact fields, add validator |
| `backend/services/workflow_service.py` | Pre-populate state in `create_release()`, remove `maybe_stop()`, remove `stop_after` from `_run_workflow()` |
| `frontend/src/types/api.ts` | Update `ReleaseCreateInput`, `ReleaseResumeInput`, `ReleaseResponse` |
| `frontend/src/pages/NewRelease.tsx` | Replace "Stop After Step" with "Start From Step" + dynamic artifact fields |
| `frontend/src/pages/ReleaseDetail.tsx` | Simplify resume form (remove stop_after dropdown) |

## Verification

1. **Start from step 1**: Normal flow — create release, all 7 steps run
2. **Start from step 4**: Provide promote ticket → steps 1-3 skipped, step 4 triggers new workflow, runs through 7
3. **Start from step 4 with run ID**: Provide promote ticket + workflow URL → step 4 polls existing run, continues through 7
4. **Start from step 5**: Provide promote ticket + workflow run ID → steps 1-4 skipped, Jenkins triggered, runs through 7
5. **Resume after error**: Error at step 5 → click Resume → continues from step 5 with all prior state intact
6. **Existing tests pass**: `poetry run pytest` and `cd frontend && npm test`
