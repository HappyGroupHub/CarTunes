"""
Room management logic for CarTunes with inactivity tracking
"""

import asyncio
import logging
import secrets
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from models import Room, Member, Song, PlaybackState

logger = logging.getLogger(__name__)


class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self.user_rooms: Dict[str, str] = {}  # user_id -> room_id mapping

    def generate_room_id(self) -> str:
        """Generate a unique 6-character room ID

        Contains only uppercase letters and numbers, excluding I, O, 0, 1 for readability.
        """
        while True:
            room_id = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
            if room_id not in self.rooms:
                return room_id

    def create_room(self, user_id: str, user_name: str = "User") -> Room:
        """Create a new room (called from LINE bot)"""
        room_id = self.generate_room_id()

        room = Room(
            room_id=room_id,
            created_at=datetime.now(),
            creator_id=user_id,
            members=[
                Member(
                    user_id=user_id,
                    user_name=user_name,
                    joined_at=datetime.now()
                )
            ],
            queue=[],
            current_song=None,
            playback_state=PlaybackState(
                is_playing=False,
                current_time=0.0,
                last_update=datetime.now()
            ),
            last_activity=datetime.now(),
            active_connections=0
        )

        self.rooms[room_id] = room
        self.user_rooms[user_id] = room_id

        logger.info(f"Room {room_id} created by user {user_id}")
        return room

    def join_room(self, room_id: str, user_id: str, user_name: str = "User") -> Optional[Room]:
        """Join an existing room"""
        if room_id not in self.rooms:
            return None

        room = self.rooms[room_id]

        # Check if user already in room
        if not any(m.user_id == user_id for m in room.members):
            new_member = Member(
                user_id=user_id,
                user_name=user_name,
                joined_at=datetime.now()
            )
            room.members.append(new_member)
            self.user_rooms[user_id] = room_id
            logger.info(f"User {user_id} joined room {room_id}")

        # Update activity
        room.last_activity = datetime.now()

        return room

    def get_room(self, room_id: str) -> Optional[Room]:
        """Get room by ID"""
        return self.rooms.get(room_id)

    def get_user_room(self, user_id: str) -> Optional[Room]:
        """Get the room a user is currently in"""
        room_id = self.user_rooms.get(user_id)
        if room_id:
            return self.rooms.get(room_id)
        return None

    def get_room_stats(self, room_id: str) -> Optional[dict]:
        """Get room statistics"""
        room = self.rooms.get(room_id)
        if not room:
            return None

        total_duration = sum(s.duration for s in room.queue)
        if room.current_song:
            total_duration += room.current_song.duration - self.get_current_playback_time(room_id)

        return {
            "room_id": room_id,
            "member_count": len(room.members),
            "queue_length": len(room.queue),
            "total_duration": total_duration,
            "active_connections": room.active_connections,
            "created_at": room.created_at.isoformat(),
            "last_activity": room.last_activity.isoformat()
        }

    def update_room_activity(self, room_id: str):
        """Update room's last activity timestamp"""
        if room_id in self.rooms:
            self.rooms[room_id].last_activity = datetime.now()

    def update_active_connections(self, room_id: str, count: int):
        """Update the number of active WebSocket connections"""
        if room_id in self.rooms:
            self.rooms[room_id].active_connections = count
            if count > 0:
                self.update_room_activity(room_id)

    def leave_room(self, room_id: str, user_id: str) -> bool:
        """Remove user from room"""
        if room_id not in self.rooms:
            return False

        room = self.rooms[room_id]

        # Remove user from room
        room.members = [m for m in room.members if m.user_id != user_id]
        self.user_rooms.pop(user_id, None)

        # If room is empty, delete it
        if not room.members:
            self.rooms.pop(room_id, None)
            logger.info(f"Room {room_id} deleted (no members)")

        return True

    def get_upcoming_video_ids(self, room_id: str, limit: int = 5) -> List[str]:
        """Get video IDs of upcoming songs in queue for preloading"""
        room = self.rooms.get(room_id)
        if not room:
            return []

        video_ids = []

        # Add current song if playing
        if room.current_song:
            video_ids.append(room.current_song.video_id)

        # Add queue songs
        for song in room.queue[:limit]:
            video_ids.append(song.video_id)

        return video_ids[:limit]

    def add_song_to_queue(self, room_id: str, song_data: dict, user_id: str, user_name: str) -> \
            Optional[Song]:
        """Add a song to the room queue"""
        room = self.rooms.get(room_id)
        if not room:
            return None

        # Create song entry
        song = Song(
            id=f"{room_id}_{len(room.queue)}_{song_data['video_id']}",
            video_id=song_data['video_id'],
            title=song_data['title'],
            artist=song_data.get('artist'),
            duration=song_data.get('duration', 0),
            thumbnail=song_data.get('thumbnail', ''),
            requester_id=user_id,
            requester_name=user_name,
            added_at=datetime.now(),
            position=len(room.queue)
        )

        room.queue.append(song)

        # If no current song, set this as current
        if not room.current_song and not room.playback_state.is_playing:
            room.current_song = room.queue.pop(0)
            room.playback_state.is_playing = False
            room.playback_state.current_time = 0.0
            room.playback_state.last_update = datetime.now()
            self._update_queue_positions(room)

        # Update activity
        room.last_activity = datetime.now()

        logger.info(f"Song {song_data['video_id']} added to room {room_id}")
        return song

    def skip_to_next_song(self, room_id: str) -> Optional[Song]:
        """Skip to the next song in queue"""
        room = self.rooms.get(room_id)
        if not room:
            return None

        if room.queue:
            room.current_song = room.queue.pop(0)
            room.playback_state.current_time = 0.0
            room.playback_state.last_update = datetime.now()
            self._update_queue_positions(room)
        else:
            room.current_song = None
            room.playback_state.is_playing = False

        # Update activity
        room.last_activity = datetime.now()

        return room.current_song

    def update_playback_state(self, room_id: str, is_playing: bool,
                              current_time: float = None) -> bool:
        """Update playback state (play/pause)"""
        room = self.rooms.get(room_id)
        if not room:
            return False

        room.playback_state.is_playing = is_playing
        if current_time is not None:
            room.playback_state.current_time = current_time
        room.playback_state.last_update = datetime.now()

        # Update activity
        room.last_activity = datetime.now()

        return True

    def get_current_playback_time(self, room_id: str) -> float:
        """Calculate current playback time based on last update"""
        room = self.rooms.get(room_id)
        if not room or not room.current_song:
            return 0.0

        if room.playback_state.is_playing:
            # Calculate elapsed time since last update
            elapsed = (datetime.now() - room.playback_state.last_update).total_seconds()
            current_time = room.playback_state.current_time + elapsed

            # Don't exceed song duration
            if current_time > room.current_song.duration:
                return float(room.current_song.duration)

            return current_time
        else:
            return room.playback_state.current_time

    def remove_song(self, room_id: str, song_id: str) -> bool:
        """Remove a song from the queue"""
        room = self.rooms.get(room_id)
        if not room:
            return False

        # Find and remove song
        song_index = next(
            (i for i, s in enumerate(room.queue) if s.id == song_id),
            None
        )

        if song_index is not None:
            room.queue.pop(song_index)
            self._update_queue_positions(room)
            room.last_activity = datetime.now()
            return True

        return False

    def reorder_queue(self, room_id: str, song_ids: List[str]) -> bool:
        """Reorder songs in the queue"""
        room = self.rooms.get(room_id)
        if not room:
            return False

        # Create a mapping of song_id to song
        song_map = {song.id: song for song in room.queue}

        # Validate all song IDs exist
        if not all(sid in song_map for sid in song_ids):
            return False

        # Reorder queue
        room.queue = [song_map[sid] for sid in song_ids]
        self._update_queue_positions(room)
        room.last_activity = datetime.now()

        return True

    def _update_queue_positions(self, room: Room):
        """Update position numbers for all songs in queue"""
        for i, song in enumerate(room.queue):
            song.position = i

    def check_room_inactivity(self, room_id: str) -> bool:
        """Check if room should be closed due to inactivity"""
        room = self.rooms.get(room_id)
        if not room:
            return False

        # Room should be closed if:
        # 1. No active connections
        # 2. Not playing music
        # 3. No activity for 30 minutes
        if (room.active_connections == 0 and
                not room.playback_state.is_playing and
                datetime.now() - room.last_activity > timedelta(minutes=30)):
            return True

        return False

    async def cleanup_inactive_rooms(self):
        """Periodically check and remove inactive rooms"""
        while True:
            try:
                inactive_rooms = []

                for room_id in list(self.rooms.keys()):
                    if self.check_room_inactivity(room_id):
                        inactive_rooms.append(room_id)

                for room_id in inactive_rooms:
                    room = self.rooms[room_id]
                    # Remove user mappings
                    for member in room.members:
                        self.user_rooms.pop(member.user_id, None)
                    # Remove room
                    self.rooms.pop(room_id, None)
                    logger.info(f"Closed inactive room: {room_id}")

            except Exception as e:
                logger.error(f"Error in room cleanup: {e}")

            # Check every 5 minutes
            await asyncio.sleep(300)
