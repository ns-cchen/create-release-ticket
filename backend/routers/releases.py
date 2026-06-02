"""REST and WebSocket endpoints for release management."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..models.schemas import (
    CleanupResponse,
    PurgeResponse,
    ReleaseCreate,
    ReleaseListItem,
    ReleaseResponse,
    ReleaseResumeRequest,
)
from ..services.websocket_manager import ws_manager
from ..services.workflow_service import workflow_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/releases", tags=["releases"])


@router.get("", response_model=list[ReleaseListItem])
async def list_releases():
    """List all releases, sorted by most recent first."""
    return workflow_service.list_releases()


@router.delete("/purge", response_model=PurgeResponse)
async def purge_releases(
    dry_run_only: bool = Query(False, description="Only purge dry-run releases"),
    older_than_days: int | None = Query(None, ge=1, description="Only purge releases older than N days"),
):
    """Purge completed release state files.

    Deletes all completed release records matching the given filters.
    This only removes local state files — Jira tickets and Jenkins
    builds are not affected.
    """
    releases_dir = Path.home() / ".create-release-ticket" / "releases"
    if not releases_dir.exists():
        return PurgeResponse(deleted_count=0, deleted_ids=[])

    deleted_ids: list[str] = []
    now = datetime.now(UTC)

    for path in list(releases_dir.glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)

            # Only purge completed releases
            current_step = data.get("current_step", "")
            if current_step != "completed":
                continue

            # Filter: dry_run_only
            if dry_run_only and not data.get("dry_run", False):
                continue

            # Filter: older_than_days
            if older_than_days is not None:
                completed_at = data.get("completed_at")
                if completed_at:
                    completed_dt = datetime.fromisoformat(completed_at)
                    if completed_dt.tzinfo is None:
                        completed_dt = completed_dt.replace(tzinfo=UTC)
                    age_days = (now - completed_dt).days
                    if age_days < older_than_days:
                        continue

            release_id = data.get("_id", path.stem)
            path.unlink()
            deleted_ids.append(release_id)
        except Exception as e:
            logger.error(f"Failed to process {path} during purge: {e}")
            continue

    logger.info(f"Purged {len(deleted_ids)} release(s): {deleted_ids}")
    return PurgeResponse(deleted_count=len(deleted_ids), deleted_ids=deleted_ids)


@router.get("/{release_id}", response_model=ReleaseResponse)
async def get_release(release_id: str):
    """Get detailed information about a specific release."""
    release = workflow_service.get_release(release_id)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    return release


@router.post("", response_model=ReleaseResponse)
async def create_release(request: ReleaseCreate):
    """Start a new release workflow.

    The workflow runs asynchronously. Connect to the WebSocket endpoint
    to receive real-time progress updates.
    """
    return await workflow_service.create_release(request)


@router.post("/{release_id}/resume", response_model=ReleaseResponse)
async def resume_release(release_id: str, request: ReleaseResumeRequest):
    """Resume a paused release workflow.

    Optionally provide Jenkins build details to skip the Jenkins step.
    """
    release = await workflow_service.resume_release(release_id, request)
    if not release:
        raise HTTPException(status_code=404, detail="Release not found")
    return release


@router.post("/{release_id}/skip-jenkins")
async def skip_jenkins(release_id: str):
    """Skip Jenkins build polling and proceed to the next step.

    The Jenkins build continues running but the workflow no longer waits for it.
    Only works when step 5 is actively polling (build already triggered).
    """
    result = workflow_service.skip_jenkins(release_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result


@router.post("/{release_id}/cleanup", response_model=CleanupResponse)
async def cleanup_release(release_id: str):
    """Clean up resources from a failed release.

    This will:
    - Close the promote ticket with 'Won't Fix' resolution
    - Cancel any running Jenkins build
    """
    result = await workflow_service.cleanup_release(release_id)
    return CleanupResponse(**result)


@router.delete("/{release_id}")
async def delete_release(release_id: str):
    """Delete a release record.

    This only removes the local state file. It does not affect
    any Jira tickets or Jenkins builds that were created.
    """
    releases_dir = Path.home() / ".create-release-ticket" / "releases"
    path = releases_dir / f"{release_id}.json"

    if not path.exists():
        raise HTTPException(status_code=404, detail="Release not found")

    path.unlink()
    return {"success": True, "message": f"Deleted release {release_id}"}


# WebSocket endpoint
@router.websocket("/ws/{release_id}")
async def websocket_endpoint(websocket: WebSocket, release_id: str):
    """WebSocket endpoint for real-time release updates.

    Connect to this endpoint to receive live progress updates for a release.

    Message types:
    - step_start: A step has begun
    - step_progress: Progress update within a step
    - step_complete: A step has finished
    - workflow_paused: Workflow stopped at requested step
    - workflow_complete: All steps completed
    - workflow_error: An error occurred
    """
    await ws_manager.connect(release_id, websocket)
    try:
        # Keep connection alive and handle any client messages
        while True:
            # We don't expect messages from client, but keep connection alive
            data = await websocket.receive_text()
            # Could handle ping/pong or commands here if needed
            logger.debug(f"Received message from client: {data}")
    except WebSocketDisconnect:
        await ws_manager.disconnect(release_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(release_id, websocket)
