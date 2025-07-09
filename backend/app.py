"""
Main FastAPI Backend Server with WebSocket support
Real-time collaborative music queue
"""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import utilities as utils
from innertube.audio_cache import audio_cache
from models import (
    JoinRoomRequest, AddSongRequest, UpdatePlaybackRequest,
    ReorderQueueRequest, RoomResponse, AddSongResponse, QueueResponse, WSMessage, WSMessageType
)
from room_manager import RoomManager
from websocket_manager import ConnectionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

room_manager = RoomManager()
ws_manager = ConnectionManager()
config = utils.read_config()

# Dictionary to store the last request time for each room and action, for throttling
# Used for playback control, skipping, and autoplay toggling
# Structure: {room_id: {'action': timestamp}}
last_request_times = {}

# Dictionary to store per-user request counts for bring to top throttling
# Structure: {user_id: [(timestamp1, timestamp2, ...)]}
user_bring_to_top_requests = {}

# Dictionary to store WebSocket pinging tasks
# Structure: {room_id: asyncio.Task}
pinging_tasks: Dict[str, asyncio.Task] = {}

background_tasks = set()


# App lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start playback progress updater
    progress_task = asyncio.create_task(broadcast_playback_progress())
    background_tasks.add(progress_task)

    # Start audio preloader
    preloader_task = asyncio.create_task(audio_preloader())
    background_tasks.add(preloader_task)

    yield

    # Shutdown
    for task in background_tasks:
        task.cancel()

    # Clean up audio cache
    audio_cache.cleanup_all()


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
        "*"
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
                        # Also broadcast queue update for natural song finish
                        await ws_manager.broadcast_queue_reordered(room_id,
                                                                   [s.dict() for s in room.queue])

                        # Check autoplay after skipping
                        if next_song and room.autoplay and len(room.queue) == 0:
                            asyncio.create_task(async_check_autoplay(room_id))
                    else:
                        # Only broadcast progress every 5 seconds (default in config),
                        # while there are active ws connections
                        connection_count = ws_manager.get_room_connection_count(room_id)
                        if connection_count > 0:
                            # Check if we should send progress update
                            if int(current_time) % config['progress_broadcast_interval'] == 0:
                                await ws_manager.broadcast_playback_progress(
                                    room_id,
                                    current_time,
                                    room.current_song.duration
                                )
        except Exception as e:
            logger.error(f"Error in playback progress broadcast: {e}")

        # Update every second but only broadcast every 5 seconds
        await asyncio.sleep(1)


async def async_check_autoplay(room_id: str):
    """Asynchronously check and add autoplay song"""
    try:
        autoplay_song = await room_manager.check_and_add_autoplay_song(room_id)

        if autoplay_song:
            # Broadcast the new song when it's ready
            await ws_manager.broadcast_song_added(room_id, autoplay_song.dict())
            logger.info(f"Autoplay song added asynchronously for room {room_id}")
    except Exception as e:
        logger.error(f"Error in async autoplay check for room {room_id}: {e}")


# ===== Basic Endpoints =====

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "CarTunes API",
        "version": "v0.1.0",
        "active_rooms": len(room_manager.rooms),
    }


# ===== Audio Endpoints =====

@app.get("/api/audio/{video_id}/status")
async def get_audio_status(video_id: str, room_id: str = Query(None)):
    """Get the download status of an audio file"""
    logger.info(f"Status check requested for video {video_id}, room {room_id}")

    if audio_cache.is_downloading(video_id):
        logger.info(f"Video {video_id} is downloading")
        return {"status": "downloading", "is_downloading": True}
    elif audio_cache.get_cache_path(video_id):
        # If room_id provided and audio is ready, start playback
        logger.info(f"Video {video_id} is ready")
        if room_id:
            started = room_manager.start_audio_ready_playback(room_id, video_id)
            if started:
                # Broadcast the playback state change
                logger.info(f"Started playback for room {room_id}")

                await ws_manager.broadcast_playback_state(
                    room_id,
                    True,
                    -abs(config['song_start_delay_seconds'])
                )

        return {"status": "ready", "is_downloading": False}
    else:
        logger.info(f"Video {video_id} not found")
        raise HTTPException(status_code=404, detail="Audio not found or not yet initiated download")


@app.get("/api/stream/{video_id}")
async def stream_audio(video_id: str):
    """Stream downloaded audio file"""
    try:
        # Check if file is already cached
        cached_path = audio_cache.get_cache_path(video_id)

        if cached_path:
            # Determine media type based on file extension
            file_extension = os.path.splitext(cached_path)[1].lower()
            # Since we are converting to MP3, the media type will always be audio/mpeg
            media_type = 'audio/mpeg'

            logger.info(f"Serving cached audio for {video_id}: {cached_path} as {media_type}")

            # Enhanced headers for better browser compatibility
            headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range, Content-Range, Content-Length",
                "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
                "Cache-Control": "public, max-age=3600",
                "Accept-Ranges": "bytes",
                "Content-Type": media_type,
            }

            return FileResponse(
                cached_path,
                media_type=media_type,
                headers=headers,
                filename=f"{video_id}{file_extension}"
            )

        # Download if not cached
        logger.info(f"Downloading audio for {video_id}")
        downloaded_path = await audio_cache.download_audio(video_id, priority=True)

        if not downloaded_path:
            # Find and remove the failed song from any room
            await handle_failed_song(video_id)
            raise HTTPException(status_code=404, detail="Audio download failed")

        # Determine media type based on file extension
        file_extension = os.path.splitext(downloaded_path)[1].lower()
        # Since we are converting to MP3, the media type will always be audio/mpeg
        media_type = 'audio/mpeg'

        logger.info(f"Serving downloaded audio for {video_id}: {downloaded_path} as {media_type}")

        # Enhanced headers for better browser compatibility
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Range, Content-Length",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
            "Cache-Control": "public, max-age=3600",
            "Accept-Ranges": "bytes",
            "Content-Type": media_type,
        }

        return FileResponse(
            downloaded_path,
            media_type=media_type,
            headers=headers,
            filename=f"{video_id}{file_extension}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error streaming audio {video_id}: {str(e)}")
        await handle_failed_song(video_id)
        raise HTTPException(status_code=500, detail="Audio streaming error")


async def handle_failed_song(video_id: str):
    """Handle failed song by removing it from queues and skipping if current"""
    for room_id in list(room_manager.rooms.keys()):
        room = room_manager.get_room(room_id)
        if not room:
            continue

        # Check if this is the current song
        if room.current_song and room.current_song.video_id == video_id:
            logger.info(f"Skipping failed current song {video_id} in room {room_id}")
            next_song = room_manager.skip_to_next_song(room_id)
            await ws_manager.broadcast_song_changed(
                room_id,
                next_song.dict() if next_song else None
            )
            continue

        # Remove from queue if present
        songs_to_remove = [song for song in room.queue if song.video_id == video_id]
        for song in songs_to_remove:
            success = room_manager.remove_song(room_id, song.id)
            if success:
                logger.info(f"Removed failed song {video_id} from room {room_id} queue")
                await ws_manager.broadcast_song_removed(room_id, song.id)


async def audio_preloader():
    """Background task to preload upcoming songs"""
    while True:
        try:
            for room_id in room_manager.rooms.keys():
                room = room_manager.get_room(room_id)
                if room and room.queue:
                    # Get top 5 video IDs of upcoming songs from queue
                    upcoming_video_ids = [song.video_id for song in room.queue[:5]]

                    # Also preload top 3 songs from autoplay_playlist
                    if room.autoplay_playlist:
                        autoplay_video_ids = [song_data['video_id'] for song_data in
                                              room.autoplay_playlist[:3]]
                        upcoming_video_ids.extend(autoplay_video_ids)

                    if upcoming_video_ids:
                        await audio_cache.preload_queue_songs(upcoming_video_ids)

        except Exception as e:
            logger.error(f"Error in audio preloader: {e}")

        # Check every 30 seconds
        await asyncio.sleep(30)


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
        active_users=room.active_connections,
        autoplay=room.autoplay
    )


@app.post("/api/room/join", response_model=RoomResponse)
async def join_room(request_object: Request, request: JoinRoomRequest):
    """Join an existing room"""
    # Only allow requests from localhost
    client_ip = request_object.client.host
    if client_ip != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Forbidden: Internal use only")

    room = room_manager.join_room(
        room_id=request.room_id,
        user_id=request.user_id,
        user_name=request.user_name or "User"
    )
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Broadcast member update to active WebSocket connections
    await ws_manager.broadcast_room_state(request.room_id, {
        "room_id": room.room_id,
        "members": [m.dict() for m in room.members],
        "queue": [s.dict() for s in room.queue],
        "current_song": room.current_song.dict() if room.current_song else None,
        "playback_state": {
            **room.playback_state.dict(),
            "current_time": room_manager.get_current_playback_time(request.room_id)},
        "autoplay": room.autoplay
    })

    return RoomResponse(
        room_id=room.room_id,
        created_at=room.created_at.isoformat(),
        creator_id=room.creator_id,
        members=[m.dict() for m in room.members],
        queue=[s.dict() for s in room.queue],
        current_song=room.current_song.dict() if room.current_song else None,
        playback_state=room.playback_state.dict(),
        active_users=room.active_connections,
        autoplay=room.autoplay
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
        active_users=room.active_connections,
        autoplay=room.autoplay
    )


@app.delete("/api/room/{room_id}/leave")
async def leave_room(request: Request, room_id: str, user_id: str = Query(...)):
    """Leave a room"""
    # Only allow requests from localhost
    client_ip = request.client.host
    if client_ip != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Forbidden: Internal use only")

    success = room_manager.leave_room(room_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Room not found")

    # Cleanup user_bring_to_top_requests for this user
    if user_id in user_bring_to_top_requests:
        del user_bring_to_top_requests[user_id]

    # Broadcast updated room state to active WebSocket connections
    room = room_manager.get_room(room_id)
    if room:  # Room still exists (has other members)
        await ws_manager.broadcast_room_state(room_id, {
            "room_id": room.room_id,
            "members": [m.dict() for m in room.members],
            "queue": [s.dict() for s in room.queue],
            "current_song": room.current_song.dict() if room.current_song else None,
            "playback_state": {
                **room.playback_state.dict(),
                "current_time": room_manager.get_current_playback_time(room_id)},
            "autoplay": room.autoplay
        })
    if not room:  # Room no longer exists (last member left)
        # Cleanup last_request_times for this room
        if room_id in last_request_times:
            del last_request_times[room_id]

    return {"message": "Left room successfully"}


@app.post("/api/room/{room_id}/autoplay/toggle")
async def toggle_autoplay(room_id: str):
    """Toggle autoplay setting for a room"""
    # Throttle this action
    if room_id in last_request_times and time.time() - last_request_times[room_id].get(
            'autoplay_toggle', 0) < config['action_throttle_seconds']:
        raise HTTPException(status_code=429, detail="Too many requests")

    if room_id not in last_request_times:
        last_request_times[room_id] = {}
    last_request_times[room_id]['autoplay_toggle'] = time.time()

    new_state = room_manager.toggle_autoplay(room_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail="Room not found")

    room = room_manager.get_room(room_id)

    # Broadcast state change
    message = WSMessage(
        type=WSMessageType.ROOM_STATS_UPDATE,
        data={
            "active_users": room.active_connections,
            "autoplay": room.autoplay,
        }
    )
    await ws_manager.broadcast_to_room(room_id, message)

    # If autoplay was just enabled and conditions are met, add a song
    if new_state and room.current_song and len(room.queue) == 0:
        asyncio.create_task(async_check_autoplay(room_id))

    return {"success": True, "autoplay": new_state}


# ===== Queue Endpoints =====

@app.post("/api/room/{room_id}/queue/add", response_model=AddSongResponse)
async def add_song_to_queue(room_id: str, request: AddSongRequest, user_id: str = Query(...),
                            user_name: str = Query(...), request_object: Request = Request):
    """Add a song to the queue, only for internal calls (called by line_bot.py)"""
    # Only allow requests from localhost
    client_ip = request_object.client.host
    if client_ip != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Forbidden: Internal use only")

    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    song_data = {
        'video_id': request.video_id,
        'title': request.title,
        'channel': request.channel,
        'duration': request.duration,
        'thumbnail': request.thumbnail
    }

    # Basic validation only, since we did it already in line_bot.py
    if not song_data['title']:
        raise HTTPException(status_code=400, detail="Invalid song data")

    # Refresh cache timer if song already exists in cache
    audio_cache.refresh_cache_timer(request.video_id)

    # Check if this will be the first song BEFORE adding
    was_empty = not room.current_song and not room.playback_state.is_playing

    # Add song to the queue
    song, autoplay_removed = room_manager.add_song_to_queue(room_id, song_data, user_id, user_name)
    if not song:
        raise HTTPException(status_code=500, detail="Failed to add song")
    # If autoplay song was removed, broadcast queue update first
    if autoplay_removed:
        await ws_manager.broadcast_queue_reordered(room_id, [s.dict() for s in room.queue])

    else:  # This is the standard path where a song is simply added.
        # Check if the song became current song AFTER adding
        became_current_song = was_empty and room.current_song and room.current_song.id == song.id
        if became_current_song:
            # Send SONG_CHANGED for first song that becomes current
            await ws_manager.broadcast_song_changed(room_id, song.dict())

            # Also broadcast playback state if room should be playing
            if room.playback_state.is_playing:
                await ws_manager.broadcast_playback_state(
                    room_id,
                    room.playback_state.is_playing,
                    room.playback_state.current_time
                )

            # If autoplay is enabled and queue is empty, check for autoplay songs
            if room.autoplay and len(room.queue) == 0:
                asyncio.create_task(async_check_autoplay(room_id))
        else:
            # Send SONG_ADDED for songs added to queue
            await ws_manager.broadcast_song_added(room_id, song.dict())

    # Start preloading in background (non-blocking)
    upcoming_video_ids = [s.video_id for s in room.queue[:5]]
    if room.current_song:
        upcoming_video_ids.insert(0, room.current_song.video_id)
    asyncio.create_task(audio_cache.preload_queue_songs(upcoming_video_ids))

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
    # Throttle this action
    if room_id in last_request_times and time.time() - last_request_times[room_id].get('skip', 0) < \
            config['action_throttle_seconds']:
        raise HTTPException(status_code=429, detail="Too many requests")

    if room_id not in last_request_times:
        last_request_times[room_id] = {}
    last_request_times[room_id]['skip'] = time.time()

    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")
    if not room.current_song:
        raise HTTPException(status_code=400, detail="No song currently playing")

    next_song = room_manager.skip_to_next_song(room_id)

    # Broadcast song change to room
    await ws_manager.broadcast_song_changed(
        room_id,
        next_song.dict() if next_song else None
    )
    # Broadcast updated queue after skipping
    await ws_manager.broadcast_queue_reordered(room_id, [s.dict() for s in room.queue])
    # Also broadcast playback state change to ensure song starts playing
    await ws_manager.broadcast_playback_state(
        room_id,
        room.playback_state.is_playing,
        room.playback_state.current_time
    )

    # Stop paused room ping/pong task if it exists
    if room_id in pinging_tasks:
        stop_pinging_task(room_id)

    # Check autoplay after skipping
    if next_song and room.autoplay and len(room.queue) == 0:
        asyncio.create_task(async_check_autoplay(room_id))

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

    # Check if we need to add autoplay song while song was removed
    if room.current_song and len(room.queue) == 0:
        asyncio.create_task(async_check_autoplay(room_id))

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

    # Check if this is a "bring to top" action (moving one song to position 0)
    is_bring_to_top = (
            len(request.song_ids) == len(room.queue) and  # All songs are included
            len(room.queue) > 1 and  # There's more than one song
            request.song_ids[0] != room.queue[0].id  # First song is changing
    )

    # Apply per-user throttling for bring to top actions
    if is_bring_to_top:
        current_time = time.time()

        # Initialize user's request list if not exists
        if user_id not in user_bring_to_top_requests:
            user_bring_to_top_requests[user_id] = []

        # Remove requests older than config window seconds
        user_bring_to_top_requests[user_id] = [
            req_time for req_time in user_bring_to_top_requests[user_id]
            if current_time - req_time < config['bring_to_top_throttle']['window_seconds']
        ]

        # Check if user has made 2 or more requests in the last 5 seconds, throttle it
        if len(user_bring_to_top_requests[user_id]) >= config['bring_to_top_throttle'][
            'max_requests']:
            return {
                "message": "Queue unchanged, blocked by throttle",
                "queue": [s.dict() for s in room.queue]
            }

        # Add current request timestamp for successful bring to top
        user_bring_to_top_requests[user_id].append(current_time)

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
    # Throttle this action
    if (room_id in last_request_times and
            time.time() - last_request_times[room_id].get('playback', 0) < config[
                'action_throttle_seconds']):
        room = room_manager.get_room(room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        return {
            "is_playing": room.playback_state.is_playing,
            "current_time": room_manager.get_current_playback_time(room_id)
        }

    if room_id not in last_request_times:
        last_request_times[room_id] = {}
    last_request_times[room_id]['playback'] = time.time()

    room = room_manager.get_room(room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    # Check if user is in room
    if not any(m.user_id == user_id for m in room.members):
        raise HTTPException(status_code=403, detail="Not a room member")

    was_playing = room.playback_state.is_playing
    success = room_manager.update_playback_state(
        room_id,
        request.is_playing,
        request.current_time
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update playback")

    # Broadcast to room playback asynchronously so it doesn't block
    asyncio.create_task(ws_manager.broadcast_playback_state(
        room_id,
        request.is_playing,
        request.current_time
    ))

    # Ping task management for Paused rooms
    if was_playing and not request.is_playing:
        start_pinging_task(room_id)
    elif room_id in pinging_tasks and not was_playing and request.is_playing:
        stop_pinging_task(room_id)

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
            active_users=room.active_connections,
            autoplay=room.autoplay
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

    # Verify user is a member of the room
    if not any(m.user_id == user_id for m in room.members):
        await websocket.close(code=4003, reason="Not a room member")
        return

    # Connect - pass room_manager instance
    await ws_manager.connect(websocket, room_id, user_id, room_manager)

    # Update connection count and broadcast to room
    connection_count = ws_manager.get_room_connection_count(room_id)
    room_manager.update_active_connections(room_id, connection_count)
    await ws_manager.broadcast_room_stats_update(room_id, connection_count, room.autoplay)

    # Send current room state to the connected user
    await ws_manager.broadcast_room_state(room_id, {
        "room_id": room.room_id,
        "members": [m.dict() for m in room.members],
        "queue": [s.dict() for s in room.queue],
        "current_song": room.current_song.dict() if room.current_song else None,
        "playback_state": {
            **room.playback_state.dict(),
            "current_time": room_manager.get_current_playback_time(room_id)},
        "autoplay": room.autoplay
    })

    try:
        while True:
            # Wait for messages from client
            try:
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                    # Handle PONG messages from the client
                    if message.get('type') == 'pong':
                        await ws_manager.handle_pong(websocket)
                    # Handle other message types as needed
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from client: {data}")
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error(f"WebSocket receive error: {e}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected normally for user {user_id} in room {room_id}")
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id} in room {room_id}: {e}")
    finally:
        # Cleanup: Disconnect and update connection count - pass room_manager instance
        room_id_disconnected, user_id_disconnected = ws_manager.disconnect(websocket, room_manager)

        if room_id_disconnected:
            # Update connection count and broadcast to room
            connection_count = ws_manager.get_room_connection_count(room_id_disconnected)
            room_manager.update_active_connections(room_id_disconnected, connection_count)
            await ws_manager.broadcast_room_stats_update(room_id_disconnected, connection_count,
                                                         room.autoplay)


# ===== Ping/Pong Task For Paused Room =====


async def _ping_task(room_id: str):
    """A dedicated task that sends pings to a manually paused room every 5 seconds."""
    ping_message = WSMessage(type=WSMessageType.PING, data={})
    while True:
        try:
            room = room_manager.get_room(room_id)
            # Stop if room is gone, or if music is no longer paused
            if not room or room.playback_state.is_playing:
                break

            logger.debug(f"Room {room_id} is manually paused, sending keep-alive ping.")
            await ws_manager.broadcast_to_room(room_id, ping_message)
            await asyncio.sleep(5)  # Ping every 5 seconds
        except asyncio.CancelledError:
            # Task was cancelled, which is expected when music is played again
            break
        except Exception as e:
            logger.error(f"Error in ping task for {room_id}: {e}")
            break


def start_pinging_task(room_id: str):
    """Start a keep-alive ping task for a specific room. (When music is manually paused)"""
    if room_id in pinging_tasks:
        pinging_tasks[room_id].cancel()

    pinging_tasks[room_id] = asyncio.create_task(_ping_task(room_id))


def stop_pinging_task(room_id: str):
    """Stop the keep-alive ping task for a specific room. (If music is played again)"""
    if room_id in pinging_tasks:
        pinging_tasks[room_id].cancel()
        pinging_tasks.pop(room_id, None)


if __name__ == "__main__":
    import uvicorn
    import utilities as utils

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=utils.read_config()['api_endpoints_port'],
    )
