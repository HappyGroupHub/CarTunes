"""
Room management logic for CarTunes with inactivity tracking
"""

import asyncio
import logging
import secrets
from datetime import datetime
from typing import Dict, Optional, List

import httpx

import utilities as utils
from innertube.recommendations import get_yt_recommendations, get_yt_music_recommendations
from models import Room, Member, Song, PlaybackState

logger = logging.getLogger(__name__)
config = utils.read_config()


class RoomManager:
    def __init__(self, maximum_room: int = 10):
        self.rooms: Dict[str, Room] = {}
        self.user_rooms: Dict[str, str] = {}  # user_id -> room_id
        self.pause_timers: Dict[str, asyncio.Task] = {}  # room_id -> timer task
        self.cleanup_timers: Dict[str, asyncio.Task] = {}  # room_id -> cleanup timer task
        self.maximum_room = maximum_room

    # ===== Room Creation =====

    def generate_room_id(self) -> str:
        """Generate a unique 6-character room ID"""
        if config['numeric_room_code']:  # Use numeric codes only
            while True:
                room_id = ''.join(secrets.choice('0123456789') for _ in range(6))
                if room_id not in self.rooms:
                    return room_id
        else:  # Contains only uppercase letters and numbers, excluding I, O, 0, 1 for readability.
            while True:
                room_id = ''.join(
                    secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))
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
            active_connections=0,
            autoplay=config['autoplay_default'],
            autoplay_playlist=[]
        )

        self.rooms[room_id] = room
        self.user_rooms[user_id] = room_id

        logger.info(f"Room {room_id} created by user {user_id}")
        self.start_cleanup_timer(room_id, is_new_room=True)
        return room

    def can_create_room(self) -> bool:
        return len(self.rooms) < self.maximum_room

    # ===== Room Information =====

    def get_room(self, room_id: str) -> Optional[Room]:
        """Get room by ID"""
        return self.rooms.get(room_id)

    def get_user_room(self, user_id: str) -> Optional[Room]:
        """Get the room a user is currently in"""
        room_id = self.user_rooms.get(user_id)
        if room_id:
            return self.rooms.get(room_id)
        return None

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

    # ===== Room Actions - Info =====

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

    # ===== Room Actions - Queue =====

    def start_audio_ready_playback(self, room_id: str, video_id: str):
        """Start playback when audio is confirmed ready"""
        room = self.get_room(room_id)
        if (room and room.current_song and
                room.current_song.video_id == video_id and
                hasattr(room, '_waiting_for_audio') and room._waiting_for_audio):
            # Audio is ready, start the countdown
            room.playback_state.is_playing = True
            room.playback_state.current_time = -1.0  # Start countdown
            room.playback_state.last_update = datetime.now()
            room._has_ever_played = True
            delattr(room, '_waiting_for_audio')

            logger.info(f"Started audio-ready playback for room {room_id}, video {video_id}")
            return True
        return False

    def add_song_to_queue(self, room_id: str, song_data: dict, user_id: str, user_name: str) -> \
            tuple[Optional[Song], bool]:
        """Add a song to the room queue"""
        room = self.rooms.get(room_id)
        if not room:
            return None

        # Remove autoplay queue if someone added a song
        autoplay_removed = False
        if len(room.queue) == 1 and room.queue[0].requester_name == "自動播放":
            removed_song = room.queue.pop(0)
            logger.info(
                f"Removed autoplay song '{removed_song.title}' in queue for room {room_id}.")
            room.autoplay_playlist = []  # Clear autoplay_playlist
            autoplay_removed = True

        # Create song entry
        song = Song(
            id=f"{room_id}_{len(room.queue)}_{song_data['video_id']}",
            video_id=song_data['video_id'],
            title=song_data['title'],
            channel=song_data.get('channel', 'Unknown Artist'),
            duration=song_data.get('duration', 0),
            thumbnail=song_data.get('thumbnail', ''),
            requester_id=user_id,
            requester_name=user_name,
            added_at=datetime.now(),
            position=len(room.queue)
        )

        room.queue.append(song)

        # Check if room has no current song
        if not room.current_song:
            room.current_song = room.queue.pop(0)
            self._update_queue_positions(room)

            if hasattr(room, '_has_ever_played') and room._has_ever_played:
                # Room ran out of music - wait for audio ready before playing
                room.playback_state.current_time = -abs(config['song_start_delay_seconds'])
                room.playback_state.is_playing = False  # Don't start until audio ready
                room._waiting_for_audio = True  # Flag to track waiting state
            else:
                # Newly created room - don't auto-play
                room.playback_state.current_time = 0.0
                room.playback_state.is_playing = False

            room.playback_state.last_update = datetime.now()

        # Update activity
        room.last_activity = datetime.now()
        logger.info(f"Song {song_data['video_id']} added to room {room_id}")
        return song, autoplay_removed

    def add_songs_batch_to_queue(self, room_id: str, songs_data: List[Dict], user_id: str,
                                 user_name: str) -> tuple[List[Song], List[Dict], int]:
        """Add multiple songs to queue in batch
        Returns: (successful_songs, failed_songs, autoplay_removed_count)
        """
        room = self.get_room(room_id)
        if not room:
            return [], songs_data, 0

        successful_songs = []
        failed_songs = []
        autoplay_removed_count = 0

        for song_data in songs_data:
            try:
                # Remove autoplay songs only for the first real song added
                if not successful_songs and room.queue and room.queue[
                    0].requester_id == "autoplay_system":
                    removed_song = room.queue.pop(0)
                    logger.info(f"Removed autoplay song: {removed_song.title}")
                    autoplay_removed_count += 1

                # Create new song
                new_song = Song(
                    id=f"{room_id}_{len(room.queue)}_{song_data['video_id']}",
                    video_id=song_data['video_id'],
                    title=song_data['title'],
                    channel=song_data.get('channel', 'Unknown Artist'),
                    duration=song_data.get('duration', 0),
                    thumbnail=song_data.get('thumbnail', ''),
                    requester_id=user_id,
                    requester_name=user_name,
                    added_at=datetime.now(),
                    position=len(room.queue)
                )

                room.queue.append(new_song)
                successful_songs.append(new_song)

            except Exception as e:
                logger.error(f"Error adding song {song_data.get('title', 'Unknown')}: {e}")
                failed_songs.append({**song_data, 'reason': str(e)})

        # Update queue positions once after all additions
        if successful_songs:
            self._update_queue_positions(room)

            # Set first song as current if no current song
            if not room.current_song and not room.playback_state.is_playing and room.queue:
                room.current_song = room.queue.pop(0)
                room.playback_state.is_playing = False
                logger.info(f"Set current song to: {room.current_song.title}")

            room.last_activity = datetime.now()

        return successful_songs, failed_songs, autoplay_removed_count

    def skip_to_next_song(self, room_id: str) -> Optional[Song]:
        """Skip to the next song in queue"""
        room = self.rooms.get(room_id)
        if not room:
            return None

        if room.queue:
            room.current_song = room.queue.pop(0)
            # Always wait for audio ready before starting
            room.playback_state.current_time = -abs(config['song_start_delay_seconds'])
            room.playback_state.is_playing = False  # Don't start until audio ready
            room.playback_state.last_update = datetime.now()
            room._waiting_for_audio = True
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

        # Track that this room has been played at least once
        if is_playing:
            room._has_ever_played = True

        # Update activity
        room.last_activity = datetime.now()

        return True

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

    @staticmethod
    def _update_queue_positions(room: Room):
        """Update position numbers for all songs in queue"""
        for i, song in enumerate(room.queue):
            song.position = i

    # ===== Autoplay Related =====

    def toggle_autoplay(self, room_id: str) -> Optional[bool]:
        """Toggle autoplay setting for a room"""
        room = self.get_room(room_id)
        if not room:
            return None

        room.autoplay = not room.autoplay

        # Clear autoplay playlist when disabling
        if not room.autoplay:
            room.autoplay_playlist = []

        logger.info(f"Room {room_id} autoplay toggled to: {room.autoplay}")
        return room.autoplay

    async def check_and_add_autoplay_song(self, room_id: str) -> Optional[Song]:
        """Check if autoplay should add a song, add it if needed"""
        room = self.get_room(room_id)
        if not room or not room.autoplay:
            return None

        # Check if conditions are met: current song playing and no songs in queue
        if not room.current_song or len(room.queue) > 0:
            return None

        # First check if we have songs in autoplay_playlist
        if room.autoplay_playlist:
            # Get first song from playlist
            next_song_data = room.autoplay_playlist.pop(0)
            new_song = Song(
                id=f"{room_id}_autoplay_{len(room.queue)}_{next_song_data['video_id']}",
                video_id=next_song_data['video_id'],
                title=next_song_data['title'],
                channel=next_song_data.get('channel', 'Unknown Artist'),
                duration=utils.convert_duration_to_seconds(next_song_data['duration']) or 0,
                thumbnail=next_song_data.get('thumbnail', ''),
                requester_id="autoplay_system",
                requester_name="自動播放",
                added_at=datetime.now(),
                position=len(room.queue)
            )
            room.queue.append(new_song)
            logger.info(f"Added autoplay song from playlist: {new_song.title}")
            return new_song

        # No songs in autoplay_playlist, need to fetch recommendations
        search_engine = config['autoplay_search_engine']

        if search_engine == 'youtube_music':
            recommendations = await get_yt_music_recommendations(room.current_song.video_id)
            if recommendations:
                valid_songs = []
                for rec in recommendations:
                    if rec.get('duration') and utils.check_video_duration(rec['duration']):
                        valid_songs.append({
                            'video_id': rec['id'],
                            'title': rec['title'],
                            'channel': rec.get('channel', 'Unknown Artist'),
                            'duration': rec['duration'],
                            'thumbnail': rec.get('thumbnail', '')
                        })
                if valid_songs:
                    # Add first song to queue
                    first_song = valid_songs[0]
                    new_song = Song(
                        id=f"{room_id}_autoplay_{len(room.queue)}_{first_song['video_id']}",
                        video_id=first_song['video_id'],
                        title=first_song['title'],
                        channel=first_song['channel'],
                        duration=utils.convert_duration_to_seconds(first_song['duration']) or 0,
                        thumbnail=first_song['thumbnail'],
                        requester_id="autoplay_system",
                        requester_name="自動播放",
                        added_at=datetime.now(),
                        position=len(room.queue)
                    )
                    room.queue.append(new_song)

                    # Save rest to autoplay_playlist
                    room.autoplay_playlist = valid_songs[1:]
                    logger.info(f"Added autoplay song from YouTube Music for room {room_id}")
                    return new_song

        else:  # youtube search
            recommendations = await get_yt_recommendations(room.current_song.video_id)
            if recommendations:
                for rec in recommendations:
                    if rec.get('duration') and utils.check_video_duration(rec['duration']):
                        new_song = Song(
                            id=f"{room_id}_autoplay_{len(room.queue)}_{rec['video_id']}",
                            video_id=rec['id'],
                            title=rec['title'],
                            channel=rec.get('channel', 'Unknown Artist'),
                            duration=utils.convert_duration_to_seconds(rec['duration']) or 0,
                            thumbnail=rec.get('thumbnail', ''),
                            requester_id="autoplay_system",
                            requester_name="自動播放",
                            added_at=datetime.now(),
                            position=len(room.queue)
                        )
                        room.queue.append(new_song)
                        logger.info(f"Added autoplay song from YouTube for room {room_id}")
                        return new_song

        return None

    # ===== Song Auto-paused Timer =====

    async def _pause_timer_task(self, room_id: str, delay_seconds: int):
        """Timer task that pauses music after delay"""
        try:
            await asyncio.sleep(delay_seconds)
            # Timer completed, pause music
            success = self.pause_music_for_no_connections(room_id)
            if success:
                from app import ws_manager
                room = self.get_room(room_id)
                if room:
                    await ws_manager.broadcast_playback_state(
                        room_id,
                        False,
                        room.playback_state.current_time
                    )
            # Remove completed timer
            self.pause_timers.pop(room_id, None)
        except asyncio.CancelledError:
            # Timer was canceled (new connection joined)
            self.pause_timers.pop(room_id, None)
        except Exception as e:
            logger.error(f"Error in pause timer for room {room_id}: {e}")
            self.pause_timers.pop(room_id, None)

    def start_pause_timer(self, room_id: str, delay_seconds: int):
        """Start countdown timer to pause music when no connections"""
        # Cancel existing timer if any
        self.cancel_pause_timer(room_id)

        room = self.get_room(room_id)
        if room and room.current_song and room.playback_state.is_playing:
            # Only start timer if room has music playing
            timer_task = asyncio.create_task(self._pause_timer_task(room_id, delay_seconds))
            self.pause_timers[room_id] = timer_task
            logger.info(f"Started pause timer for room {room_id} ({delay_seconds}s)")

    def cancel_pause_timer(self, room_id: str):
        """Cancel pause timer when new connection joins"""
        if room_id in self.pause_timers:
            self.pause_timers[room_id].cancel()
            self.pause_timers.pop(room_id, None)
            logger.info(f"Cancelled pause timer for room {room_id}")

    def pause_music_for_no_connections(self, room_id: str) -> bool:
        """Pause music in room due to no active connections"""
        room = self.rooms.get(room_id)
        if not room:
            return False

        if room.current_song and room.playback_state.is_playing:
            # Update current time before pausing
            current_time = self.get_current_playback_time(room_id)
            room.playback_state.is_playing = False
            room.playback_state.current_time = current_time
            room.playback_state.last_update = datetime.now()
            logger.info(f"Music paused in room {room_id} due to no active connections")
            return True

        return False

    # ===== Inactive Room Cleanup Timer =====

    async def _cleanup_timer_task(self, room_id: str, delay_seconds: int):
        """Timer task that deletes room after delay"""
        try:
            await asyncio.sleep(delay_seconds)
            # Timer completed, delete room
            room = self.rooms.get(room_id)
            if room:
                # Remove user mappings and rich menus
                for member in room.members:
                    self.user_rooms.pop(member.user_id, None)
                    try:  # Remove user from line_bot.py's local user_rooms mappings
                        with httpx.Client() as client:
                            client.delete(
                                f"http://localhost:{config['line_webhook_port']}/api/room/leave",
                                params={"user_id": member.user_id}
                            )
                    except Exception as e:
                        logger.error(
                            f"Error removing user {member.user_id} from room {room_id}: {e}")

                # Cancel pause timer if exists
                self.cancel_pause_timer(room_id)

                # Remove room
                self.rooms.pop(room_id, None)
                logger.info(f"Closed inactive room: {room_id}")

            # Remove completed timer
            self.cleanup_timers.pop(room_id, None)
        except asyncio.CancelledError:
            self.cleanup_timers.pop(room_id, None)
        except Exception as e:
            logger.error(f"Error in cleanup timer for room {room_id}: {e}")
            self.cleanup_timers.pop(room_id, None)

    def start_cleanup_timer(self, room_id: str, is_new_room: bool = False):
        """Start cleanup timer when room has no connections

        :param room_id: ID of the room to start timer for
        :param is_new_room: There's no need to log countdown if the room was newly created
        """
        # Cancel existing timer if any
        self.cancel_cleanup_timer(room_id)

        delay_seconds = config['room_cleanup_after_inactivity'] * 60  # Convert minutes to seconds
        timer_task = asyncio.create_task(self._cleanup_timer_task(room_id, delay_seconds))
        self.cleanup_timers[room_id] = timer_task
        if not is_new_room:
            logger.info(f"Started cleanup timer for room {room_id} ({delay_seconds}s)")

    def cancel_cleanup_timer(self, room_id: str):
        """Cancel cleanup timer when room gets connections"""
        if room_id in self.cleanup_timers:
            self.cleanup_timers[room_id].cancel()
            self.cleanup_timers.pop(room_id, None)
            logger.info(f"Cancelled cleanup timer for room {room_id}")
