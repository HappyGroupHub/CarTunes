"""
Pydantic models for CarTunes API
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel


# Request Models
class JoinRoomRequest(BaseModel):
    room_id: str
    user_id: str
    user_name: Optional[str] = None


class AddSongRequest(BaseModel):
    video_id: str
    title: Optional[str] = None
    channel: Optional[str] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None


class AddSongBatchRequest(BaseModel):
    songs: List[AddSongRequest]


class ReorderQueueRequest(BaseModel):
    song_ids: List[str]  # List of song IDs in new order


class UpdatePlaybackRequest(BaseModel):
    is_playing: bool
    current_time: Optional[float] = None  # Current playback time in seconds


# WebSocket Message Types
class WSMessageType(str, Enum):
    # Connection
    CONNECTED = "connected"
    USER_JOINED = "user_joined"
    USER_LEFT = "user_left"

    # Queue updates
    SONG_ADDED = "song_added"
    QUEUE_BATCH_ADDED = "queue_batch_added"
    SONG_REMOVED = "song_removed"
    QUEUE_REORDERED = "queue_reordered"

    # Playback updates
    PLAYBACK_STARTED = "playback_started"
    PLAYBACK_PAUSED = "playback_paused"
    SONG_CHANGED = "song_changed"
    PLAYBACK_PROGRESS = "playback_progress"
    PLAYBACK_SEEKED = "playback_seeked"

    # Room updates
    ROOM_CLOSING = "room_closing"
    ROOM_STATE = "room_state"
    ROOM_STATS_UPDATE = "room_stats_update"

    # Keep-alive messages, used while music is paused
    PING = "ping"
    PONG = "pong"

    # Error messages
    ERROR = "error"


# WebSocket Messages
class WSMessage(BaseModel):
    type: WSMessageType
    data: Dict[str, Any]
    timestamp: datetime = None

    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now()
        super().__init__(**data)


# Data Models
class Member(BaseModel):
    user_id: str
    user_name: str
    joined_at: datetime


class Song(BaseModel):
    id: str
    video_id: str
    title: str
    channel: Optional[str] = None
    duration: int  # in seconds
    thumbnail: str
    requester_id: str
    requester_name: str
    added_at: datetime
    position: int


class PlaybackState(BaseModel):
    is_playing: bool
    current_time: float  # Current playback position in seconds
    last_update: datetime


class Room(BaseModel):
    room_id: str
    created_at: datetime
    creator_id: str
    members: List[Member]
    queue: List[Song]
    current_song: Optional[Song] = None
    playback_state: PlaybackState
    last_activity: datetime  # Updated when users connect or music plays
    active_connections: int = 0  # Number of active WebSocket connections
    autoplay: bool = True
    autoplay_playlist: List[Dict[str, Any]] = []
    quick_play_songs: List[Dict[str, Any]] = []  # Pre-fetched quick play songs


# Response Models
class RoomResponse(BaseModel):
    room_id: str
    created_at: str
    creator_id: str
    members: List[dict]
    queue: List[dict]
    current_song: Optional[dict] = None
    playback_state: dict
    active_users: int
    autoplay: bool
    quick_play_songs: List[dict] = []


class AddSongResponse(BaseModel):
    message: str
    song: dict
    queue_length: int


class AddSongBatchResponse(BaseModel):
    message: str
    songs_added: List[dict]
    songs_failed: List[dict]
    total_added: int
    total_failed: int


class QueueResponse(BaseModel):
    current_song: Optional[dict] = None
    queue: List[dict]
    playback_state: dict
