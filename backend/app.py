"""
Main FastAPI Backend Server with WebSocket support
Real-time collaborative music queue
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from innertube.audio_extractor import get_audio_stream_info
from models import (
    JoinRoomRequest, AddSongRequest, UpdatePlaybackRequest,
    ReorderQueueRequest, RoomResponse, AddSongResponse, QueueResponse
)
from room_manager import RoomManager
from websocket_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

room_manager = RoomManager()
ws_manager = ConnectionManager()

background_tasks = set()


# App lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cleanup_task = asyncio.create_task(room_manager.cleanup_inactive_rooms())
    background_tasks.add(cleanup_task)

    # Start playback progress updater
    progress_task = asyncio.create_task(broadcast_playback_progress())
    background_tasks.add(progress_task)

    yield

    # Shutdown
    for task in background_tasks:
        task.cancel()


# Initialize FastAPI app
app = FastAPI(
    title="CarTunes API",
    description="Real-time collaborative music queue for road trips",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://localhost:3000",
        # Add production URLs here
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Background Tasks =====

async def broadcast_playback_progress():
    """Periodically broadcast playback progress to all rooms"""
    while True:
        try:
            for room_id in ws_manager.get_all_rooms_with_connections():
                room = room_manager.get_room(room_id)
                if room and room.current_song and room.playback_state.is_playing:
                    current_time = room_manager.get_current_playback_time(room_id)

                    # Check if song ended
                    if current_time >= room.current_song.duration:
                        # Auto-skip to next song
                        next_song = room_manager.skip_to_next_song(room_id)
                        await ws_manager.broadcast_song_changed(
                            room_id,
                            next_song.dict() if next_song else None
                        )
                    else:
                        # Broadcast progress
                        await ws_manager.broadcast_playback_progress(
                            room_id,
                            current_time,
                            room.current_song.duration
                        )
        except Exception as e:
            logger.error(f"Error in playback progress broadcast: {e}")

        # Update every second
        await asyncio.sleep(1)


# ===== Basic Endpoints =====

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "CarTunes API",
        "version": "2.0.0",
        "status": "running",
        "active_rooms": len(room_manager.rooms),
        "features": ["real-time-sync", "websocket", "auto-cleanup"]
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


# ===== Audio Endpoints =====

@app.get("/api/audio/{video_id}")
async def get_audio_info(video_id: str):
    """Get audio information for a video"""
    try:
        logger.info(f"Getting audio info for video: {video_id}")

        audio_info = get_audio_stream_info(video_id)

        if not audio_info:
            raise HTTPException(status_code=404, detail="Video not found")

        return {
            "success": True,
            "video_id": video_id,
            "title": audio_info.get('title', 'Unknown'),
            "duration": audio_info.get('duration', 0),
            "thumbnail": audio_info.get('thumbnail', ''),
            "formats": audio_info.get('audio_formats', []),
            "best_audio_url": audio_info['audio_formats'][0]['url'] if audio_info.get(
                'audio_formats') else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting audio info: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/stream/{video_id}")
async def stream_audio(video_id: str, format_id: Optional[str] = None):
    """Redirect to YouTube audio stream URL for direct playback"""
    try:
        audio_info = get_audio_stream_info(video_id)

        if not audio_info or not audio_info.get('audio_formats'):
            raise HTTPException(status_code=404, detail="No audio stream available")

        # Select audio format
        audio_url = None
        if format_id:
            for fmt in audio_info['audio_formats']:
                if fmt.get('format_id') == format_id:
                    audio_url = fmt['url']
                    break
        else:
            audio_url = audio_info['audio_formats'][0]['url']

        if not audio_url:
            raise HTTPException(status_code=404, detail="Audio format not found")

        return RedirectResponse(url=audio_url, status_code=302)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming audio: {str(e)}")
        raise HTTPException(status_code=500, detail="Streaming error")


# ===== Room Endpoints =====

@app.post("/api/room/create", response_model=RoomResponse)
async def create_room(
        request: Request,
        user_id: str = Query(...),
        user_name: str = Query("User")
):
    """
    Create a new room
    Only allow creation by internal calls (called by line_bot.py)
    """
    # Only allow requests from localhost
    client_ip = request.client.host
    if client_ip != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Forbidden: Internal use only")

    room = room_manager.create_room(
        user_id=user_id,
        user_name=user_name
    )

    return RoomResponse(
        room_id=room.room_id,
        created_at=room.created_at.isoformat(),
        creator_id=room.creator_id,
        members=[m.dict() for m in room.members],
        queue=[s.dict() for s in room.queue],
        current_song=room.current_song.dict() if room.current_song else None,
        playback_state=room.playback_state.dict(),
        active_users=room.active_connections
    )

@app.post("/api/room/join", response_model=RoomResponse)
async def join_room(request: JoinRoomRequest):
    """Join an existing room"""
    room = room_manager.join_room(
        room_id=request.room_id,
        user_id=request.user_id,
        user_name=request.user_name or "User"
    )

    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    return RoomResponse(
        room_id=room.room_id,
        created_at=room.created_at.isoformat(),
        creator_id=room.creator_id,
        members=[m.dict() for m in room.members],
        queue=[s.dict() for s in room.queue],
        current_song=room.current_song.dict() if room.current_song else None,
        playback_state=room.playback_state.dict(),
        active_users=room.active_connections
    )


@app.get("/api/room/{room_id}", response_model=RoomResponse)
async def get_room(room_id: str):
    """Get room information"""
    room = room_manager.get_room(room_id)

    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Update activity when room is accessed
    room_manager.update_room_activity(room_id)

    return RoomResponse(
        room_id=room.room_id,
        created_at=room.created_at.isoformat(),
        creator_id=room.creator_id,
        members=[m.dict() for m in room.members],
        queue=[s.dict() for s in room.queue],
        current_song=room.current_song.dict() if room.current_song else None,
        playback_state={
            **room.playback_state.dict(),
            "current_time": room_manager.get_current_playback_time(room_id)
        },
        active_users=room.active_connections
    )


@app.delete("/api/room/{room_id}/leave")
async def leave_room(room_id: str, user_id: str = Query(...)):
    """Leave a room"""
    success = room_manager.leave_room(room_id, user_id)

    if not success:
        raise HTTPException(status_code=404, detail="Room not found")

    return {"message": "Left room successfully"}


# ===== Queue Endpoints =====

@app.post("/api/room/{room_id}/queue/add", response_model=AddSongResponse)
async def add_song_to_queue(
        room_id: str,
        request: AddSongRequest,
        user_id: str = Query(...),
        user_name: str = Query("User")
):
    """Add a song to the queue"""
    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if user is in room
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    # Get song info if not provided
    song_data = {
        'video_id': request.video_id,
        'title': request.title,
        'artist': request.artist,
        'duration': request.duration,
        'thumbnail': request.thumbnail
    }

    if not request.title:
        audio_info = get_audio_stream_info(request.video_id)
        if not audio_info:
            raise HTTPException(status_code=400, detail="Invalid video ID")

        song_data['title'] = audio_info.get('title', 'Unknown')
        song_data['duration'] = audio_info.get('duration', 0)
        song_data['thumbnail'] = audio_info.get('thumbnail', '')

    # Add song
    song = room_manager.add_song_to_queue(room_id, song_data, user_id, user_name)

    if not song:
        raise HTTPException(status_code=500, detail="Failed to add song")

    # Broadcast to room
    await ws_manager.broadcast_song_added(room_id, song.dict())

    # If this became the current song, broadcast that too
    if room.current_song and room.current_song.id == song.id:
        await ws_manager.broadcast_song_changed(room_id, song.dict())

    return AddSongResponse(
        message="Song added to queue",
        song=song.dict(),
        queue_length=len(room.queue)
    )


@app.get("/api/room/{room_id}/queue", response_model=QueueResponse)
async def get_queue(room_id: str):
    """Get the current queue"""
    room = room_manager.get_room(room_id)

    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    return QueueResponse(
        current_song=room.current_song.dict() if room.current_song else None,
        queue=[s.dict() for s in room.queue],
        playback_state={
            **room.playback_state.dict(),
            "current_time": room_manager.get_current_playback_time(room_id)
        }
    )


@app.post("/api/room/{room_id}/queue/next")
async def skip_to_next_song(
        room_id: str,
        user_id: str = Query(...)
):
    """Skip to next song"""
    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if user is in room
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    next_song = room_manager.skip_to_next_song(room_id)

    # Broadcast to room
    await ws_manager.broadcast_song_changed(
        room_id,
        next_song.dict() if next_song else None
    )

    return {
        "current_song": next_song.dict() if next_song else None,
        "queue_length": len(room.queue),
        "is_playing": room.playback_state.is_playing
    }


@app.delete("/api/room/{room_id}/queue/{song_id}")
async def remove_song_from_queue(
        room_id: str,
        song_id: str,
        user_id: str = Query(...)
):
    """Remove a song from queue"""
    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if user is in room
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    success = room_manager.remove_song(room_id, song_id)

    if not success:
        raise HTTPException(status_code=404, detail="Song not found")

    # Broadcast to room
    await ws_manager.broadcast_song_removed(room_id, song_id)

    return {
        "message": "Song removed",
        "queue_length": len(room.queue)
    }


@app.put("/api/room/{room_id}/queue/reorder")
async def reorder_queue(
        room_id: str,
        request: ReorderQueueRequest,
        user_id: str = Query(...)
):
    """Reorder the queue"""
    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if user is in room
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    success = room_manager.reorder_queue(room_id, request.song_ids)

    if not success:
        raise HTTPException(status_code=400, detail="Invalid song order")

    # Broadcast to room
    await ws_manager.broadcast_queue_reordered(
        room_id,
        [s.dict() for s in room.queue]
    )

    return {
        "message": "Queue reordered",
        "queue": [s.dict() for s in room.queue]
    }


# ===== Playback Control Endpoints =====

@app.post("/api/room/{room_id}/playback")
async def update_playback(
        room_id: str,
        request: UpdatePlaybackRequest,
        user_id: str = Query(...)
):
    """Update playback state (play/pause)"""
    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if user is in room
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    success = room_manager.update_playback_state(
        room_id,
        request.is_playing,
        request.current_time
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to update playback")

    # Broadcast to room
    await ws_manager.broadcast_playback_state(
        room_id,
        request.is_playing,
        request.current_time
    )

    return {
        "is_playing": request.is_playing,
        "current_time": request.current_time or room.playback_state.current_time
    }


@app.post("/api/room/{room_id}/playback/seek")
async def seek_playback(
        room_id: str,
        seek_time: float = Query(..., ge=0, description="Seek time in seconds"),
        user_id: str = Query(...)
):
    """Seek to specific time in current song"""
    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Check if user is in room
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    # Check if there's a current song
    if not room.current_song:
        raise HTTPException(status_code=400, detail="No song currently playing")

    # Validate seek time
    if seek_time > room.current_song.duration:
        raise HTTPException(
            status_code=400,
            detail=f"Seek time exceeds song duration ({room.current_song.duration}s)"
        )

    # Update playback state
    success = room_manager.update_playback_state(
        room_id,
        room.playback_state.is_playing,
        seek_time
    )

    if not success:
        raise HTTPException(status_code=500, detail="Failed to seek")

    # Broadcast to room
    await ws_manager.broadcast_playback_state(
        room_id,
        room.playback_state.is_playing,
        seek_time
    )

    return {
        "success": True,
        "seek_time": seek_time,
        "is_playing": room.playback_state.is_playing
    }


# ===== User Endpoints =====

@app.get("/api/user/{user_id}/current-room")
async def get_user_current_room(user_id: str):
    """Get user's current room"""
    room = room_manager.get_user_room(user_id)

    if not room:
        return {"room_id": None, "in_room": False}

    return {
        "room_id": room.room_id,
        "in_room": True,
        "room": RoomResponse(
            room_id=room.room_id,
            created_at=room.created_at.isoformat(),
            creator_id=room.creator_id,
            members=[m.dict() for m in room.members],
            queue=[s.dict() for s in room.queue],
            current_song=room.current_song.dict() if room.current_song else None,
            playback_state={
                **room.playback_state.dict(),
                "current_time": room_manager.get_current_playback_time(room.room_id)
            },
            active_users=room.active_connections
        )
    }


# ===== WebSocket Endpoint =====

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, user_id: str = Query(...)):
    """WebSocket connection for real-time updates"""
    # Verify room exists
    room = room_manager.get_room(room_id)
    if not room:
        await websocket.close(code=4004, reason="Room not found")
        return

    # Connect
    await ws_manager.connect(websocket, room_id, user_id)

    # Update connection count
    connection_count = ws_manager.get_room_connection_count(room_id)
    room_manager.update_active_connections(room_id, connection_count)

    # Get user info
    member = next((m for m in room.members if m.user_id == user_id), None)
    if member:
        await ws_manager.broadcast_user_joined(room_id, user_id, member.user_name)

    # Send current room state to the connected user
    await ws_manager.broadcast_room_state(room_id, {
        "room_id": room.room_id,
        "members": [m.dict() for m in room.members],
        "queue": [s.dict() for s in room.queue],
        "current_song": room.current_song.dict() if room.current_song else None,
        "playback_state": {
            **room.playback_state.dict(),
            "current_time": room_manager.get_current_playback_time(room_id)
        }
    })

    try:
        while True:
            # Wait for messages from client
            data = await websocket.receive_text()
            message = json.loads(data)

            # Handle client messages if needed
            if message.get('type') == 'ping':
                await websocket.send_text(json.dumps({'type': 'pong'}))

    except WebSocketDisconnect:
        # Disconnect
        room_id_disconnected, user_id_disconnected = ws_manager.disconnect(websocket)

        if room_id_disconnected:
            # Update connection count
            connection_count = ws_manager.get_room_connection_count(room_id_disconnected)
            room_manager.update_active_connections(room_id_disconnected, connection_count)

            # Notify others
            if member:
                await ws_manager.broadcast_user_left(room_id_disconnected, user_id,
                                                     member.user_name)


if __name__ == "__main__":
    import uvicorn
    import utilities as utils

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=utils.read_config()['api_endpoints_port'],
        reload=True
    )
