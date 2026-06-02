"""WebSocket connection manager for real-time updates."""

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections for release updates."""

    def __init__(self):
        # Map of release_id -> list of connected websockets
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, release_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection for a release."""
        await websocket.accept()
        async with self._lock:
            if release_id not in self._connections:
                self._connections[release_id] = []
            self._connections[release_id].append(websocket)
        logger.info(f"WebSocket connected for release {release_id}")

    async def disconnect(self, release_id: str, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        async with self._lock:
            if release_id in self._connections:
                try:
                    self._connections[release_id].remove(websocket)
                    if not self._connections[release_id]:
                        del self._connections[release_id]
                except ValueError:
                    pass
        logger.info(f"WebSocket disconnected for release {release_id}")

    async def broadcast(self, release_id: str, message: dict[str, Any]) -> None:
        """Send a message to all connections for a release."""
        async with self._lock:
            connections = self._connections.get(release_id, []).copy()

        if not connections:
            return

        message_str = json.dumps(message, default=str)
        disconnected = []

        for websocket in connections:
            try:
                await websocket.send_text(message_str)
            except Exception as e:
                logger.warning(f"Failed to send message to websocket: {e}")
                disconnected.append(websocket)

        # Clean up disconnected websockets
        if disconnected:
            async with self._lock:
                for ws in disconnected:
                    try:
                        self._connections[release_id].remove(ws)
                    except (ValueError, KeyError):
                        pass

    async def send_step_start(
        self,
        release_id: str,
        step_number: int,
        step_name: str,
        step_key: str
    ) -> None:
        """Send step start notification."""
        await self.broadcast(release_id, {
            "type": "step_start",
            "release_id": release_id,
            "step": {
                "number": step_number,
                "name": step_name,
                "key": step_key,
                "status": "in_progress",
            }
        })

    async def send_step_progress(
        self,
        release_id: str,
        step_number: int,
        progress: str
    ) -> None:
        """Send progress update for a step."""
        await self.broadcast(release_id, {
            "type": "step_progress",
            "release_id": release_id,
            "step": {"number": step_number, "status": "in_progress"},
            "progress": progress,
        })

    async def send_step_complete(
        self,
        release_id: str,
        step_number: int,
        step_name: str,
        step_key: str,
        result: dict[str, Any] | None = None
    ) -> None:
        """Send step completion notification."""
        await self.broadcast(release_id, {
            "type": "step_complete",
            "release_id": release_id,
            "step": {
                "number": step_number,
                "name": step_name,
                "key": step_key,
                "status": "completed",
                "result": result,
            }
        })

    async def send_workflow_paused(
        self,
        release_id: str,
        step_number: int,
        step_key: str
    ) -> None:
        """Send workflow paused notification."""
        await self.broadcast(release_id, {
            "type": "workflow_paused",
            "release_id": release_id,
            "step": {"number": step_number, "key": step_key},
            "data": {"message": f"Workflow paused after step {step_number}"}
        })

    async def send_workflow_complete(
        self,
        release_id: str,
        data: dict[str, Any]
    ) -> None:
        """Send workflow completion notification."""
        await self.broadcast(release_id, {
            "type": "workflow_complete",
            "release_id": release_id,
            "data": data,
        })

    async def send_workflow_error(
        self,
        release_id: str,
        error: str,
        step_number: int | None = None
    ) -> None:
        """Send workflow error notification."""
        await self.broadcast(release_id, {
            "type": "workflow_error",
            "release_id": release_id,
            "error": error,
            "step": {"number": step_number} if step_number else None,
        })

    def get_connection_count(self, release_id: str) -> int:
        """Get the number of active connections for a release."""
        return len(self._connections.get(release_id, []))


# Global instance
ws_manager = WebSocketManager()
