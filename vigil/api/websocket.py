"""WebSocket support for real-time iteration progress streaming."""

import asyncio
import json
import logging
import queue

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

_event_queue: queue.Queue | None = None
_loop: asyncio.AbstractEventLoop | None = None


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        log.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)
        log.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        payload = json.dumps(message)
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def broadcast_event(event_type: str, data: dict) -> None:
    """Thread-safe broadcast from orchestrator thread into the async event loop."""
    if _loop is None or _event_queue is None:
        return
    message = {"type": event_type, "data": data}
    try:
        _event_queue.put_nowait(message)
    except Exception:
        pass


async def _queue_consumer() -> None:
    """Polls the thread-safe queue and broadcasts to WebSocket clients."""
    while True:
        try:
            message = _event_queue.get_nowait()
            await manager.broadcast(message)
        except queue.Empty:
            await asyncio.sleep(0.25)


async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def start_queue_consumer(loop: asyncio.AbstractEventLoop) -> None:
    """Schedule the queue consumer on the given event loop (called from server startup)."""
    global _event_queue, _loop
    _event_queue = queue.Queue()
    _loop = loop
    loop.create_task(_queue_consumer())
