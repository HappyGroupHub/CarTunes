"""
WebSocket connection management for real-time updates
"""

import logging
from datetime import datetime
from typing import Dict, Set, Any

from fastapi import WebSocket

import utilities as utils
from models import WSMessage, WSMessageType

logger = logging.getLogger(__name__)
config = utils.read_config()


class ConnectionManager:
    def __init__(self):
        # room_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # websocket -> (room_id, user_id)
        self.connection_info: Dict[WebSocket, tuple] = {}

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str, room_manager=None):
        """Add new WebSocket connection"""
        await websocket.accept()

        if room_id not in self.active_connections:
            self.active_connections[room_id] = set()

        self.active_connections[room_id].add(websocket)
        self.connection_info[websocket] = (room_id, user_id)

        # Cancel both timers since room now has connections
        if room_manager:
            room_manager.cancel_pause_timer(room_id)
            room_manager.cancel_cleanup_timer(room_id)

        logger.info(f"WebSocket connected: {user_id} to room {room_id}")

    def disconnect(self, websocket: WebSocket, room_manager=None) -> tuple[Any, Any] | tuple[
        None, None]:
        """Remove WebSocket connection and return room_id, user_id"""
        connection_data = self.connection_info.pop(websocket, None)

        if connection_data:
            room_id, user_id = connection_data

            if room_id in self.active_connections:
                self.active_connections[room_id].discard(websocket)

                # If room has no more connections, start both timers
                if len(self.active_connections[room_id]) == 0:
                    if room_manager:
                        # Start pause timer (short delay)
                        room_manager.start_pause_timer(room_id,
                                                       config['pause_music_after_no_connections'])
                        # Start cleanup timer (long delay)
                        room_manager.start_cleanup_timer(room_id)

                # Clean up empty room from connections
                if not self.active_connections[room_id]:
                    del self.active_connections[room_id]

            logger.info(f"WebSocket disconnected: {user_id} from room {room_id}")
            return room_id, user_id

        return None, None

    async def send_personal_message(self, message: WSMessage, websocket: WebSocket):
        """Send message to specific connection"""
        try:
            await websocket.send_text(message.json())
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")
            # Remove broken connection
            self.disconnect(websocket)

    async def broadcast_to_room(self, room_id: str, message: WSMessage, exclude: WebSocket = None):
        """Broadcast message to all connections in a room"""
        if room_id not in self.active_connections:
            return

        disconnected = set()

        for connection in self.active_connections[
            room_id].copy():  # Use copy to avoid modification during iteration
            if connection != exclude:
                try:
                    await connection.send_text(message.json())
                except Exception as e:
                    logger.error(f"Error broadcasting to connection: {e}")
                    disconnected.add(connection)

        # Clean up disconnected connections
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_user_joined(self, room_id: str, user_id: str, user_name: str):
        """Notify room when user joins"""
        message = WSMessage(
            type=WSMessageType.USER_JOINED,
            data={
                "user_id": user_id,
                "user_name": user_name,
                "timestamp": datetime.now().isoformat()
            }
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_user_left(self, room_id: str, user_id: str, user_name: str):
        """Notify room when user leaves"""
        message = WSMessage(
            type=WSMessageType.USER_LEFT,
            data={
                "user_id": user_id,
                "user_name": user_name,
                "timestamp": datetime.now().isoformat()
            }
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_song_added(self, room_id: str, song: dict):
        """Notify room when song is added"""
        message = WSMessage(
            type=WSMessageType.SONG_ADDED,
            data={"song": song}
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_song_removed(self, room_id: str, song_id: str):
        """Notify room when song is removed"""
        message = WSMessage(
            type=WSMessageType.SONG_REMOVED,
            data={"song_id": song_id}
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_queue_reordered(self, room_id: str, queue: list):
        """Notify room when queue is reordered"""
        message = WSMessage(
            type=WSMessageType.QUEUE_REORDERED,
            data={"queue": queue}
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_playback_state(self, room_id: str, is_playing: bool,
                                       current_time: float = None):
        """Notify room of playback state change"""
        msg_type = WSMessageType.PLAYBACK_STARTED if is_playing else WSMessageType.PLAYBACK_PAUSED
        message = WSMessage(
            type=msg_type,
            data={
                "is_playing": is_playing,
                "current_time": current_time
            }
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_song_changed(self, room_id: str, current_song: dict = None):
        """Notify room when current song changes"""
        message = WSMessage(
            type=WSMessageType.SONG_CHANGED,
            data={"current_song": current_song}
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_playback_progress(self, room_id: str, current_time: float, duration: int):
        """Broadcast current playback progress"""
        message = WSMessage(
            type=WSMessageType.PLAYBACK_PROGRESS,
            data={
                "current_time": current_time,
                "duration": duration,
                "percentage": (current_time / duration * 100) if duration > 0 else 0
            }
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_room_state(self, room_id: str, room_data: dict):
        """Send complete room state"""
        message = WSMessage(
            type=WSMessageType.ROOM_STATE,
            data={"room": room_data}
        )
        await self.broadcast_to_room(room_id, message)

    async def broadcast_room_closing(self, room_id: str, reason: str):
        """Notify room is closing"""
        message = WSMessage(
            type=WSMessageType.ROOM_CLOSING,
            data={"reason": reason}
        )
        await self.broadcast_to_room(room_id, message)

    def get_room_connection_count(self, room_id: str) -> int:
        """Get number of active connections in a room"""
        return len(self.active_connections.get(room_id, set()))

    def get_all_rooms_with_connections(self) -> Set[str]:
        """Get all room IDs that have active connections"""
        return set(self.active_connections.keys())
