"""
VIGIL-AI: Central Multi-User Dashboard Event Bus.
Manages active WebSocket connections for the Laptop SOC Dashboard (/ws/dashboard)
and per-call channels (/ws/calls/{call_id}).
Enforces multi-tenant isolation: Events for User A are delivered only to User A's dashboard.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Any, List
from fastapi import WebSocket
from app.core.logging import logger


class DashboardEventBus:
    """Thread-safe, non-blocking pub/sub event bus with per-user tenant isolation."""

    def __init__(self):
        # Global dashboard listeners (unscoped / demo)
        self._global_clients: Set[WebSocket] = set()
        # Per-user dashboard listeners: user_id -> Set[WebSocket]
        self._user_clients: Dict[str, Set[WebSocket]] = {}
        # Per-call listeners: call_id -> Set[WebSocket]
        self._call_clients: Dict[str, Set[WebSocket]] = {}
        # Active call sessions cache: call_id -> call_metadata
        self._active_calls: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @property
    def _dashboard_clients(self) -> Set[WebSocket]:
        all_clients = set(self._global_clients)
        for user_set in self._user_clients.values():
            all_clients.update(user_set)
        return all_clients

    async def register_dashboard_client(self, websocket: WebSocket, user_id: Optional[str] = None):
        async with self._lock:
            if user_id:
                if user_id not in self._user_clients:
                    self._user_clients[user_id] = set()
                self._user_clients[user_id].add(websocket)
                logger.info(f"User dashboard client registered for user {user_id}. Count: {len(self._user_clients[user_id])}")
            else:
                self._global_clients.add(websocket)
                logger.info(f"Global dashboard client registered. Count: {len(self._global_clients)}")

    async def unregister_dashboard_client(self, websocket: WebSocket, user_id: Optional[str] = None):
        async with self._lock:
            if user_id and user_id in self._user_clients:
                self._user_clients[user_id].discard(websocket)
                if not self._user_clients[user_id]:
                    del self._user_clients[user_id]
            self._global_clients.discard(websocket)

    async def register_call_client(self, call_id: str, websocket: WebSocket):
        async with self._lock:
            if call_id not in self._call_clients:
                self._call_clients[call_id] = set()
            self._call_clients[call_id].add(websocket)
        logger.info(f"Call-specific listener registered for {call_id}")

    async def unregister_call_client(self, call_id: str, websocket: WebSocket):
        async with self._lock:
            if call_id in self._call_clients:
                self._call_clients[call_id].discard(websocket)
                if not self._call_clients[call_id]:
                    del self._call_clients[call_id]

    def set_active_call(self, call_id: str, data: Dict[str, Any]):
        self._active_calls[call_id] = data

    def get_active_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        return self._active_calls.get(call_id)

    def get_all_active_calls(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if user_id:
            return [c for c in self._active_calls.values() if c.get("user_id") == user_id]
        return list(self._active_calls.values())

    def remove_active_call(self, call_id: str):
        self._active_calls.pop(call_id, None)

    async def broadcast_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        call_id: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """
        Broadcasts an event to target recipients.
        If user_id is provided, sends to that specific user's dashboard sessions
        plus global sessions.
        """
        message = {
            "event": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload
        }
        if call_id:
            message["call_id"] = call_id
            if call_id in self._active_calls:
                self._active_calls[call_id].update(payload)
                self._active_calls[call_id]["last_event"] = event_type
                self._active_calls[call_id]["last_updated"] = message["timestamp"]

        if user_id:
            message["user_id"] = user_id

        message_text = json.dumps(message)

        # Determine recipient dashboard websockets
        recipients: Set[WebSocket] = set()
        if user_id and user_id in self._user_clients:
            recipients.update(self._user_clients[user_id])
        # Also notify global listeners (e.g. SOC admin view)
        recipients.update(self._global_clients)

        # Resilient fallback: If no exact user-specific websocket is connected, broadcast to all active
        # dashboard sessions so that live call screening events are never missed on local/paired consoles
        if not recipients:
            for user_ws_set in self._user_clients.values():
                recipients.update(user_ws_set)

        dead_clients = []
        for ws in list(recipients):
            try:
                await ws.send_text(message_text)
            except Exception as e:
                logger.debug(f"Failed to send to dashboard client: {e}")
                dead_clients.append(ws)

        if dead_clients:
            async with self._lock:
                for ws in dead_clients:
                    self._global_clients.discard(ws)
                    if user_id and user_id in self._user_clients:
                        self._user_clients[user_id].discard(ws)

        # Broadcast to call-specific subscribers
        if call_id and call_id in self._call_clients:
            call_recipients = list(self._call_clients[call_id])
            dead_call_clients = []
            for ws in call_recipients:
                try:
                    await ws.send_text(message_text)
                except Exception as e:
                    logger.debug(f"Failed to send to call client {call_id}: {e}")
                    dead_call_clients.append(ws)

            if dead_call_clients:
                async with self._lock:
                    for ws in dead_call_clients:
                        if call_id in self._call_clients:
                            self._call_clients[call_id].discard(ws)


# Global Singleton Instances
dashboard_event_bus = DashboardEventBus()
dashboard_bus = dashboard_event_bus
