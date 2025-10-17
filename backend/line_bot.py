import asyncio
import time
import urllib
from typing import Dict, Any

import httpx
from fastapi import Request, HTTPException, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (Configuration, AsyncApiClient, AsyncMessagingApi,
                                  AsyncMessagingApiBlob, TextMessage, ReplyMessageRequest,
                                  FlexMessage, FlexContainer,
                                  RichMenuRequest, RichMenuBounds, URIAction, RichMenuArea,
                                  MessageAction, PostbackAction)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent

import utilities as utils
from innertube import audio_extractor
from innertube.audio_extractor import get_audio_stream_info
from innertube.search import search_both_concurrent
from line_extensions.async_webhook import AsyncWebhookHandler

app = FastAPI()
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["*"],
)

config = utils.read_config()
configuration = Configuration(access_token=config['line_channel_access_token'])
async_handler = AsyncWebhookHandler(config['line_channel_secret'])

# Dictionary to track user rooms - key: user_id, value: room_id
user_rooms = {}

# Cache for storing search results when postback data is too long
# Key: video_id, Value: search result data
postback_cache: Dict[str, Dict[str, Any]] = {}

# Cache for storing playlist URLs temporarily
# Key: user_id + "_" + playlist_id
# Value: dict with 'url', 'video_id' (optional), 'timestamp'
playlist_cache: Dict[str, Dict[str, Any]] = {}

# Song length limit in minutes
song_len_min = config['song_length_limit'] // 60

# LINE messages throttle settings - per user
line_message_throttle = config['line_message_throttle_seconds']
user_messages: Dict[str, float] = {}  # key: user_id, value: last message timestamp


# ===== Song Keyword Search Cache =====

def cleanup_old_cache_entries():
    """Remove cache entries older than 30 minutes"""
    current_time = time.time()
    keys_to_remove = []

    for video_id, data in postback_cache.items():
        if current_time - data.get('cached_at', 0) > 1800:  # 30 minutes
            keys_to_remove.append(video_id)

    for key in keys_to_remove:
        del postback_cache[key]


def store_in_cache(video_id: str, result: dict):
    """Store search result in cache"""
    cleanup_old_cache_entries()
    postback_cache[video_id] = {
        **result,
        'cached_at': time.time()
    }


def get_from_cache(video_id: str) -> Dict[str, Any]:
    """Retrieve cached search result"""
    return postback_cache.get(video_id, {})


def estimate_postback_length(video_id: str, title: str, channel: str, duration: str,
                             thumbnail: str) -> int:
    """Estimate the length of postback data"""
    postback_data = (f"add_song:{video_id}"
                     f"|/title:{title}"
                     f"|/channel:{channel}"
                     f"|/duration:{duration}"
                     f"|/thumbnail:{thumbnail}")
    return len(postback_data)


# ===== Call/Receive Internal Endpoints =====

async def create_room_via_api(user_id: str, user_name: str) -> (bool, str | None):
    """Create a room via internal API call.

    You should check if user_id is already in user_rooms before calling this function.
    This function would link user rich menu if success.
    Returns a tuple (success, room_id) where success is True if room created, False if failed.
    If failed, it will return error reason.
    """
    user_rooms[user_id] = "TEMP"  # Add temporary room entry to prevent spam
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://localhost:{config['api_endpoints_port']}/api/room/create",
                params={"user_id": user_id, "user_name": user_name}
            )
        if response.status_code == 200:
            room_id = response.json()['room_id']
            await link_roomed_rich_menu(user_id, room_id)
            user_rooms[user_id] = room_id  # Update actual room ID
            return True, room_id
        else:
            print(f"Failed to create room: {response.status_code}")
            del user_rooms[user_id]  # Remove temp user_rooms entry
            return False, response.json()['detail']
    except Exception as e:
        print(f"Error creating room: {e}")
        del user_rooms[user_id]  # Remove temp user_rooms entry
        return False, None


async def add_song_via_api(room_id: str, video_id: str, user_id: str, user_name: str,
                           title: str = None,
                           channel: str = None, duration: str = None, thumbnail: str = None):
    """Add song to queue via internal API call."""
    try:
        duration_seconds = utils.convert_duration_to_seconds(duration) if duration else None
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://localhost:{config['api_endpoints_port']}/api/room/{room_id}/queue/add",
                json={
                    "video_id": video_id,
                    "title": title,
                    "channel": channel,
                    "duration": duration_seconds,
                    "thumbnail": thumbnail
                },
                params={"user_id": user_id, "user_name": user_name}
            )
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to add song: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error adding song: {e}")
        return None


async def change_playback_state_via_api(room_id: str, user_id: str) -> bool | None:
    """Change playback state via internal API call.
    Return False if playback state is paused, True if playing, None if error.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Get the current room state to determine the current is_playing status
            get_response = await client.get(
                f"http://localhost:{config['api_endpoints_port']}/api/room/{room_id}"
            )
            if get_response.status_code != 200:
                print(f"Failed to get room state: {get_response.status_code}")
                return None

            playback_state = get_response.json().get("playback_state", None)
            currently_playing = playback_state.get("is_playing", None)
            current_time = playback_state.get("current_time", None)
            if playback_state is None or currently_playing is None or current_time is None:
                print("Playback state is missing required fields.")
                return None

            # Send a POST request with the toggled state in the JSON body
            new_playing_state = not currently_playing
            response = await client.post(
                f"http://localhost:{config['api_endpoints_port']}/api/room/{room_id}/playback",
                params={"user_id": user_id},
                json={"is_playing": new_playing_state, "current_time": current_time}
            )

        if response.status_code == 200:
            return response.json().get('is_playing')
        else:
            print(f"Failed to change playback state: {response.status_code} - {response.text}")
            return None

    except httpx.RequestError as e:
        print(f"Error changing playback state: {e}")
        return None


async def skip_song_via_api(room_id: str, user_id: str) -> (bool, str | None):
    """Skip current song via internal API call.
    Return tuple (success, current_song) where success is True if song skipped,"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://localhost:{config['api_endpoints_port']}/api/room/{room_id}/queue/next",
                params={"user_id": user_id}
            )
        if response.status_code == 200:
            return True, response.json().get('current_song', None)
        elif response.status_code == 429:  # Throttle limit exceeded
            return False, "Throttle limit exceeded"
        else:
            print(f"Failed to skip song: {response.status_code}")
            return False, None
    except Exception as e:
        print(f"Error skipping song: {e}")
        return False, None


async def join_room(user_id: str, room_id: str, user_name: str) -> (bool, str | None):
    """Join room endpoint to add user_rooms locally.

    You should check if user_id is already in user_rooms before calling this function.
    This function would link user rich menu if success.
    Returns a tuple (success, error_message) where success is True if joined, False if failed.
    If error_message is "No such room", it means the room does not exist.
    Else, error_message would be just None.
    """
    user_rooms[user_id] = "TEMP"  # Add temporary room entry to prevent spam
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"http://localhost:{config['api_endpoints_port']}/api/room/join",
                json={"room_id": room_id, "user_id": user_id, "user_name": user_name}
            )
        if response.status_code == 200:
            # Successfully joined room
            await link_roomed_rich_menu(user_id, room_id)
            user_rooms[user_id] = room_id  # Update actual room ID
            return True, None
        else:
            # API call failed
            del user_rooms[user_id]  # Remove temp user_rooms entry
            return False, "No such room"
    except Exception as e:
        print(f"Error joining room: {e}")
        del user_rooms[user_id]  # Remove temp user_rooms entry
        return False, None


async def leave_room(user_id: str, room_id: str) -> bool:
    """Leave room endpoint to remove user_rooms locally.

    You should check if user_id is in user_rooms before calling this function.
    This function would unlink user rich menu if success.
    Returns True if successfully left the room, False if failed.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"http://localhost:{config['api_endpoints_port']}/api/room/{room_id}/leave",
                params={"user_id": user_id}
            )

        if response.status_code == 200:
            # Successfully left room
            del user_rooms[user_id]
            await unlink_rich_menu_from_user(user_id)
            return True
        else:
            # API call failed
            return False
    except Exception as e:
        print(f"Error leaving room: {e}")
        # Even if API fails, remove from local tracking
        del user_rooms[user_id]
        await unlink_rich_menu_from_user(user_id)
        return False


@app.delete("/api/room/leave")
async def clear_user_rooms(request: Request, user_id: str):
    """This function would be called from room_manger.py _cleanup_timer_task().
    It is designed to be called internally to clear specific user in user_rooms while
    system cleaning up inactive rooms.
    """
    # Only allow requests from localhost
    client_ip = request.client.host
    if client_ip != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Forbidden: Internal use only")

    if user_id in user_rooms:
        del user_rooms[user_id]


# ===== Handel Message Event =====

def create_search_results_carousel(youtube_results: list, youtube_music_results: list,
                                   user_input: str, page: int = 0):
    """Create LINE Flex carousel for search results with YouTube Music prioritized on first page."""

    # Filter out results that don't have channel or duration
    def is_valid_result(result):
        return (result.get('channel') and
                result.get('duration') and
                result.get('title') and
                result.get('id'))

    # Filter both result sets
    filtered_youtube_results = [r for r in youtube_results if is_valid_result(r)]
    filtered_youtube_music_results = [r for r in youtube_music_results if is_valid_result(r)]

    # Combine results with YouTube Music first on page 0
    if page == 0 and filtered_youtube_music_results:
        # First result from YouTube Music, then YouTube results
        combined_results = filtered_youtube_music_results[:1] + filtered_youtube_results
    else:
        # For other pages, just use YouTube results
        combined_results = filtered_youtube_results

    start_index = page * 4
    end_index = start_index + 4
    current_results = combined_results[start_index:end_index]

    bubbles = []

    # Add result bubbles
    for i, result in enumerate(current_results):
        video_id = result.get('id')
        title = result.get('title')
        channel = result.get('channel')
        duration = result.get('duration')
        thumbnail = result.get('thumbnail', '')

        display_title = title
        if page == 0 and i == 0 and filtered_youtube_music_results:
            display_title = "🎵 " + title  # Music note for YouTube Music

        # Estimate postback data length
        estimated_length = estimate_postback_length(video_id, title, channel, duration, thumbnail)

        # Use cache if postback data would be too long
        if estimated_length > 290:  # 300 characters is the limit for postback data
            store_in_cache(video_id, result)
            postback_data = f"add_song_cached:{video_id}"
        else:
            postback_data = (f"add_song:{video_id}"
                             f"|/title:{title}"
                             f"|/channel:{channel}"
                             f"|/duration:{duration}"
                             f"|/thumbnail:{thumbnail}")

        bubble = {
            "type": "bubble",
            "size": "kilo",
            "header": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "image",
                        "url": thumbnail or 'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
                        "size": "full",
                        "aspectMode": "cover",
                        "aspectRatio": "320:213"
                    }
                ],
                "paddingAll": "0px"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": display_title,
                        "weight": "bold",
                        "size": "sm",
                        "wrap": True,
                        "maxLines": 2
                    },
                    {
                        "type": "text",
                        "text": channel,
                        "size": "xs",
                        "color": "#aaaaaa",
                        "wrap": True,
                        "maxLines": 1
                    },
                    {
                        "type": "text",
                        "text": f"⏱️ {duration}",
                        "size": "xs",
                        "color": "#666666"
                    }
                ],
                "spacing": "sm",
                "paddingAll": "13px"
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "action": {
                            "type": "postback",
                            "label": "新增歌曲",
                            "data": postback_data
                        }
                    }
                ],
                "paddingAll": "13px"
            }
        }
        bubbles.append(bubble)

    # Add navigation bubble
    navigation_contents = []

    # Show next page button if there are more results
    if end_index < len(combined_results):
        navigation_contents.append({
            "type": "button",
            "style": "secondary",
            "action": {
                "type": "postback",
                "label": "下一頁",
                "data": f"next_page:{user_input}:{page + 1}"
            }
        })

    encoded_query = urllib.parse.quote_plus(user_input)
    youtube_search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
    navigation_contents.append({
        "type": "button",
        "style": "link",
        "action": {
            "type": "uri",
            "label": "搜尋 YouTube",
            "uri": youtube_search_url
        }
    })

    yt_music_search_url = f"https://music.youtube.com/search?q={encoded_query}"
    navigation_contents.append({
        "type": "button",
        "style": "link",
        "action": {
            "type": "uri",
            "label": "搜尋 YT Music",
            "uri": yt_music_search_url
        }
    })

    if navigation_contents:
        nav_bubble = {
            "type": "bubble",
            "size": "kilo",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                                {
                                    "type": "text",
                                    "text": "更多選項",
                                    "weight": "bold",
                                    "size": "md",
                                    "align": "center"
                                },
                                {
                                    "type": "separator",
                                    "margin": "md"
                                }
                            ] + [
                                {
                                    "type": "button",
                                    **button
                                } for button in navigation_contents
                            ],
                "spacing": "md",
                "paddingAll": "20px"
            }
        }
        bubbles.append(nav_bubble)

    carousel = {
        "type": "carousel",
        "contents": bubbles
    }

    return FlexMessage(alt_text="搜尋結果", contents=FlexContainer.from_dict(carousel))


def create_playlist_confirmation_carousel(playlist_info: dict, valid_songs: list,
                                          current_video_id: str | None,
                                          playlist_id: str, max_songs: int) -> FlexMessage:
    """Create a flex message for playlist import confirmation."""

    # Calculate total duration
    total_duration = sum(song.get('duration', 0) for song in valid_songs)
    duration_text = f"{total_duration // 60} 分 {total_duration % 60} 秒"

    # Prepare songs preview (show first 5)
    preview_songs = []
    for i, song in enumerate(valid_songs[:5], 1):
        duration = song.get('duration', 0)
        duration_str = f"{duration // 60}:{duration % 60:02d}" if duration else "未知"

        # Add star emoji if this is the current video
        is_current = song['video_id'] == current_video_id
        song_text = f"{'⭐ ' if is_current else ''}{i}. {song['title'][:30]}... ({duration_str})"

        preview_songs.append({
            "type": "text",
            "text": song_text,
            "size": "sm",
            "color": "#555555",
            "wrap": True,
            "margin": "sm"
        })

    # Add "and X more..." if there are more songs
    if len(valid_songs) > 5:
        preview_songs.append({
            "type": "text",
            "text": f"... 還有 {len(valid_songs) - 5} 首歌曲",
            "size": "sm",
            "color": "#999999",
            "margin": "sm"
        })

    bubble = {
        "type": "bubble",
        "size": "mega",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🎵 發現播放清單",
                    "weight": "bold",
                    "size": "lg",
                    "color": "#FFFFFF"
                }
            ],
            "backgroundColor": "#FF6B6B",
            "paddingAll": "15px"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": playlist_info['title'][:50],
                    "weight": "bold",
                    "size": "md",
                    "wrap": True,
                    "margin": "md"
                },
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "總歌曲數：",
                            "size": "sm",
                            "color": "#555555",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": f"{len(valid_songs)} 首",
                            "size": "sm",
                            "color": "#111111",
                            "flex": 0
                        }
                    ],
                    "margin": "md"
                },
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "總時長：",
                            "size": "sm",
                            "color": "#555555",
                            "flex": 0
                        },
                        {
                            "type": "text",
                            "text": duration_text,
                            "size": "sm",
                            "color": "#111111",
                            "flex": 0
                        }
                    ],
                    "margin": "sm"
                },
                {
                    "type": "separator",
                    "margin": "md"
                },
                {
                    "type": "text",
                    "text": "歌曲預覽：",
                    "size": "sm",
                    "color": "#555555",
                    "margin": "md"
                },
                *preview_songs
            ],
            "spacing": "sm",
            "paddingAll": "13px"
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "action": {
                        "type": "postback",
                        "label": f"新增全部 ({min(len(valid_songs), max_songs)} 首)",
                        "data": f"add_playlist:all|{playlist_id}"
                    },
                    "color": "#FF6B6B"
                },
                {
                    "type": "button",
                    "style": "secondary",
                    "action": {
                        "type": "postback",
                        "label": "僅新增當前歌曲" if current_video_id else "取消",
                        "data": f"add_playlist:single|{playlist_id}|{current_video_id}" if current_video_id else "cancel"
                    },
                    "margin": "sm"
                }
            ]
        }
    }

    return FlexMessage(
        alt_text=f"播放清單：{playlist_info['title']} ({len(valid_songs)} 首歌)",
        contents=FlexContainer.from_dict(bubble)
    )


@app.post("/callback")
async def callback(request: Request):
    """Callback function for line webhook."""

    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = await request.body()

    # handle webhook body
    try:
        await async_handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        raise HTTPException(status_code=400, detail="Invalid signature.")

    return 'OK'


@async_handler.add(MessageEvent, message=TextMessageContent)
async def handle_message(event):
    async with AsyncApiClient(configuration) as api_client:
        if event.source.type == 'group':  # Exclude group messages, only process DM messages
            return
        line_bot_api = AsyncMessagingApi(api_client)
        message_received = event.message.text
        user_id = event.source.user_id

        # LINE message throttling - per user
        current_time = time.time()
        if user_id in user_messages:
            if current_time - user_messages[user_id] < line_message_throttle:
                reply_message = TextMessage(text="冷靜！你速度太快了🔥")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
                return
        # Update last message time
        user_messages[user_id] = current_time

        if message_received == "離開房間":
            if user_id in user_rooms:
                room_id = user_rooms[user_id]

                success = await leave_room(user_id, room_id)
                if success:
                    reply_message = TextMessage(text="成功離開房間！")
                else:
                    reply_message = TextMessage(text="離開房間時發生錯誤，請稍後再試！")
            else:
                reply_message = TextMessage(text="您目前不在任何房間！")

            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message]))
            return

        if message_received == "加入房間":
            reply_message = TextMessage(
                text="請直接輸入6位數房間代碼 或\n"
                     "轉發朋友的訊息至此即可加入房間！")
            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message]))
            return

        # Handle join room share message, and room code message if user not in a room
        if "房間代碼：" in message_received or len(
                message_received) == 6 and user_id not in user_rooms:
            if user_id in user_rooms and "房間代碼：" in message_received:
                reply_message = TextMessage(
                    text="您已經在房間中！請先輸入「離開房間」來離開目前的房間！")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message]))
                return

            if len(message_received) == 6:
                room_id = message_received.upper()
            else:
                try:
                    # Extract room ID from the message, it will be only 6 characters long
                    room_id = message_received.split("房間代碼：")[-1].strip()[:6]
                except IndexError:
                    reply_message = TextMessage(text="無效的房間代碼格式！")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token, messages=[reply_message])
                    )
                    return

            user_name = (await line_bot_api.get_profile(user_id)).display_name
            success, error_message = await join_room(user_id, room_id, user_name)
            if success:
                reply_message = TextMessage(
                    text=f"房間加入成功！🎉\n" \
                         f"現在您可以在聊天室搜尋歌曲並新增\n" \
                         f"或直接貼上 YouTube 連結點歌\n\n" \
                         f"🎵 點擊下方區域進入網頁播放器\n"
                         f"隨時插歌或是刪除不想要的歌曲～\n\n" \
                         f"房間代碼：{room_id}")
            elif error_message == "No such room":
                reply_message = TextMessage(
                    text="❌ 錯誤的房間代碼！\n"
                         "請輸入正確的房間代碼，或直接轉發朋友的訊息至此即可加入房間～")
            else:
                reply_message = TextMessage(text="加入房間時發生錯誤，請稍後再試。")
            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message]))
            return

        if message_received == "創建房間":
            # Check if user is already in a room
            if user_id in user_rooms:
                reply_message = TextMessage(
                    text="您已經在房間中！請先輸入「離開房間」來離開目前的房間")
            else:
                user_name = (await line_bot_api.get_profile(user_id)).display_name
                success, result = await create_room_via_api(user_id, user_name)

                if success:
                    reply_message = TextMessage(
                        text=f"房間創建成功！🎉\n" \
                             f"現在您可以直接在此聊天室搜尋和新增歌曲了！點擊下方的區域進入網頁播放器，隨時插歌" \
                             f"或是刪除不想要的歌曲～\n\n" \
                             f"🎵 想邀請朋友一起聽歌？\n" \
                             f"您現在可以直接分享此訊息給朋友，他們只要將此訊息轉發給本官方帳號，" \
                             f"就能自動加入您的房間與一起同樂！\n\n" \
                             f"房間代碼：{result}\n" \
                             f"🎶 一起來創造美好的音樂時光！")
                else:
                    if result == "Forbidden: Internal use only":
                        reply_message = TextMessage(text="建立房間時發生錯誤，請稍後再試。")
                    if result == "Forbidden: Reached maximum room limit":
                        reply_message = TextMessage(text="已抵達可建立房間上限，請稍後再試。")

            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )
            return

        # After all check, if user is not in a room, ask them to create or join one
        if user_id not in user_rooms:
            reply_message = TextMessage(text="請先加入/創建房間！\n"
                                             "打開下方面版並點擊「創建房間」\n"
                                             "或轉發朋友的訊息至此「加入房間」")
            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )
            return

        # User in room and tap play/pause button
        if message_received == "播放/暫停":
            room_id = user_rooms[user_id]
            is_playing = await change_playback_state_via_api(room_id, user_id)

            if is_playing is None:
                reply_message = TextMessage(text="❌ 無法切換播放狀態，請稍後再試！")
            elif is_playing:
                reply_message = TextMessage(text="▶️ 音樂已開始播放")
            else:
                reply_message = TextMessage(text="⏸️ 音樂已暫停")

            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )
            return

        # User in room and tap next song button
        if message_received == "下一首歌曲":
            room_id = user_rooms[user_id]
            success, current_song = await skip_song_via_api(room_id, user_id)

            if success:
                if current_song:
                    reply_message = TextMessage(
                        text=f"✅ 已切至下一首歌！\n🎵 {current_song['title']}")
                else:
                    reply_message = TextMessage(text="✅ 已切至下一首歌！")
            else:
                if current_song == "Throttle limit exceeded":
                    reply_message = TextMessage(
                        text="✅ 其他使用者已協助切歌！")
                else:
                    reply_message = TextMessage(text="❌ 無法跳過歌曲，請稍後再試！")

            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message]))
            return

        # Handle URL messages to check if it's a valid YouTube link
        if utils.is_url(message_received):
            if not utils.is_youtube_url(message_received):
                reply_message = TextMessage(text="❌ 目前僅支援 YouTube 連結點歌！")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
                return

            # Extract both video ID and playlist ID
            video_id, playlist_id = utils.extract_video_and_playlist_from_url(message_received)

            if playlist_id:
                # Store playlist URL in cache for later use
                playlist_cache[f"{user_id}_{playlist_id}"] = {
                    'url': message_received,
                    'video_id': video_id,  # Might be None if it's just a playlist URL
                    'timestamp': time.time()
                }

                # Fetch playlist info
                max_songs = config.get('max_playlist_songs', 20)
                playlist_info = await audio_extractor.get_playlist_info(playlist_id, max_songs)

                if not playlist_info or not playlist_info['songs']:
                    reply_message = TextMessage(text="❌ 無法取得播放清單資訊，請確認連結是否正確！")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                    )
                    return

                # Filter songs by duration limit and track counts
                valid_songs = []
                for song in playlist_info['songs']:
                    duration_seconds = song.get('duration', 0)
                    if duration_seconds and duration_seconds <= config['song_length_limit']:
                        valid_songs.append(song)

                # If no valid songs in playlist
                if not valid_songs:
                    reply_message = TextMessage(
                        text=f"❌ 播放清單中的 {len(playlist_info['songs'])} 首歌曲都超過"
                             f" {song_len_min} 分鐘限制！\n"
                             f"請選擇其他播放清單或歌曲"
                    )
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                    )
                    return

                # Create confirmation flex message (pass filtered_count for display)
                carousel_message = create_playlist_confirmation_carousel(playlist_info, valid_songs,
                                                                         video_id, playlist_id,
                                                                         max_songs)
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[carousel_message])
                )
                return

            if not video_id:
                reply_message = TextMessage(text="❌ 無效的 YouTube 連結！\n"
                                                 "請重新確認連結或直接搜尋關鍵字")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
                return

            audio_info = await get_audio_stream_info(video_id)
            if not audio_info:
                reply_message = TextMessage(text="❌ 新增歌曲失敗，請檢查連結是否正確！")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
                return
            else:
                room_id = user_rooms[user_id]
                user_name = (await line_bot_api.get_profile(user_id)).display_name

                if audio_info['duration'] is None:  # It's a live video
                    reply_message = TextMessage(
                        text="❌ 無法新增直播至播放佇列！\n"
                             "請選擇其他一般長度的影片或歌曲")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                    )
                    return
                elif audio_info['duration'] > config['song_length_limit']:
                    reply_message = TextMessage(
                        text=f"❌ 歌曲長度超過 {song_len_min} 分鐘限制\n"
                             f"請選擇其他歌曲！")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                    )
                    return

                result = await add_song_via_api(room_id, video_id, user_id, user_name,
                                                title=audio_info.get('title', 'Unknown'),
                                                channel=audio_info.get('channel', 'Unknown'),
                                                duration=audio_info.get('duration', '0'),
                                                thumbnail=audio_info.get(
                                                    'thumbnail',
                                                    'https://i.imgur.com/zSJgfAT.jpeg'))
                if result:
                    reply_message = TextMessage(
                        text=f"✅ 歌曲已新增至播放佇列！\n🎵 {result['song']['title']}")
                else:
                    reply_message = TextMessage(text="❌ 新增歌曲失敗，請檢查連結是否正確！")

                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
        else:  # Keyword search
            if len(message_received) > 50:
                reply_message = TextMessage(text="搜尋關鍵字過長，請重新輸入！")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
                return

            try:
                youtube_results, youtube_music_results = await search_both_concurrent(
                    message_received)
                if youtube_results or youtube_music_results:
                    # Create and send carousel message with both result types
                    carousel_message = create_search_results_carousel(
                        youtube_results, youtube_music_results, message_received
                    )
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token, messages=[carousel_message]
                        )
                    )
                else:
                    reply_message = TextMessage(text="找不到相關歌曲，請嘗試其他關鍵字！")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                    )
            except Exception as e:
                print(f"Search error: {e}")
                reply_message = TextMessage(text="搜尋時發生錯誤，請稍後再試！")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )


@async_handler.add(PostbackEvent)
async def handle_postback(event):
    async with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        postback_data = event.postback.data
        user_id = event.source.user_id

        if postback_data == "join_room":
            reply_message = TextMessage(
                text="請直接輸入6位數房間代碼 或\n"
                     "轉發朋友的訊息至此即可加入房間！")
            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )
            return

        # Check if user is in a room
        if user_id not in user_rooms:
            reply_message = TextMessage(text="請先創建房間才能新增歌曲！")
            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )
            return

        room_id = user_rooms[user_id]
        user_name = (await line_bot_api.get_profile(user_id)).display_name

        if postback_data.startswith("add_song:"):
            # Extract video ID and add song
            data_parts = postback_data.split("|/")
            video_id = data_parts[0].split(":", 1)[1]
            title = channel = duration = thumbnail = None
            for part in data_parts[1:]:
                if part.startswith("title:"):
                    title = part[6:]
                elif part.startswith("channel:"):
                    channel = part[8:]
                elif part.startswith("duration:"):
                    duration = part[9:]
                elif part.startswith("thumbnail:"):
                    thumbnail = part[10:]

            # Filter duration before responding
            if not utils.check_video_duration(duration):
                reply_message = TextMessage(
                    text=f"❌ 歌曲長度超過 {song_len_min} 分鐘限制\n請選擇其他歌曲！")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
                return

            # Immediate success response
            reply_message = TextMessage(text=f"✅ 歌曲已新增至播放佇列！\n🎵 {title}")
            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )

            # Add song asynchronously in the background
            try:
                result = await add_song_via_api(room_id, video_id, user_id, user_name, title=title,
                                                channel=channel, duration=duration,
                                                thumbnail=thumbnail)
            except Exception as e:
                print(f"Error in async song addition: {e}")

        elif postback_data.startswith("add_song_cached:"):
            # Extract video ID and get data from cache
            video_id = postback_data.split(":", 1)[1]
            cached_data = get_from_cache(video_id)

            if cached_data:
                title = cached_data.get('title', 'Unknown Title')
                channel = cached_data.get('channel', 'Unknown')
                duration = cached_data.get('duration', 'N/A')
                thumbnail = cached_data.get('thumbnail', '')

                # Filter duration before responding
                if not utils.check_video_duration(duration):
                    reply_message = TextMessage(
                        text=f"❌ 歌曲長度超過 {song_len_min} 分鐘限制\n請選擇其他歌曲！")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                    )
                    return

                # Immediate success response
                reply_message = TextMessage(text=f"✅ 歌曲已新增至播放佇列！\n🎵 {title}")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )

                # Add song asynchronously in the background
                try:
                    result = await add_song_via_api(room_id, video_id, user_id, user_name,
                                                    title=title, channel=channel, duration=duration,
                                                    thumbnail=thumbnail)
                except Exception as e:
                    print(f"Error in async song addition: {e}")
            else:
                reply_message = TextMessage(text="❌ 歌曲資料已過期，請重新搜尋。")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )

        elif postback_data.startswith("next_page:"):
            # Handle pagination
            parts = postback_data.split(":", 2)
            if len(parts) == 3:
                user_input = parts[1]
                page = int(parts[2])

                try:
                    youtube_results, youtube_music_results = await search_both_concurrent(
                        user_input)
                    if youtube_results or youtube_music_results:
                        carousel_message = create_search_results_carousel(
                            youtube_results, youtube_music_results, user_input, page
                        )
                        await line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token, messages=[carousel_message]
                            )
                        )
                    else:
                        reply_message = TextMessage(text="找不到更多結果囉！")
                        await line_bot_api.reply_message(
                            ReplyMessageRequest(
                                reply_token=event.reply_token, messages=[reply_message]
                            )
                        )
                except Exception as e:
                    print(f"Pagination error: {e}")
                    reply_message = TextMessage(text="載入時發生錯誤！")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token, messages=[reply_message]
                        )
                    )

        elif postback_data.startswith("add_playlist:"):
            parts = postback_data.split("|")
            action = parts[0].split(":")[1]  # "all" or "single"
            playlist_id = parts[1]

            # Get cached playlist data
            cache_key = f"{user_id}_{playlist_id}"
            if cache_key not in playlist_cache:
                reply_message = TextMessage(text="❌ 播放清單資料已過期，請重新傳送連結！")
                await line_bot_api.reply_message(
                    ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                )
                return

            cached_data = playlist_cache[cache_key]

            # Clean up old cache entries (older than 5 minutes)
            current_time = time.time()
            for key in list(playlist_cache.keys()):
                if current_time - playlist_cache[key]['timestamp'] > 300:
                    del playlist_cache[key]

            room_id = user_rooms[user_id]
            user_name = (await line_bot_api.get_profile(user_id)).display_name

            if action == "single" and cached_data['video_id']:
                # Add only the specific video
                video_id = cached_data['video_id']
                audio_info = await get_audio_stream_info(video_id)

                if not audio_info:
                    reply_message = TextMessage(text="❌ 新增歌曲失敗，請稍後再試！")
                else:
                    result = await add_song_via_api(
                        room_id, video_id, user_id, user_name,
                        title=audio_info.get('title', 'Unknown'),
                        channel=audio_info.get('channel', 'Unknown'),
                        duration=audio_info.get('duration', '0'),
                        thumbnail=audio_info.get('thumbnail', '')
                    )
                    if result:
                        reply_message = TextMessage(
                            text=f"✅ 已新增歌曲：\n🎵 {result['song']['title']}"
                        )
                    else:
                        reply_message = TextMessage(text="❌ 新增歌曲失敗！")

            elif action == "all":
                # Fetch playlist info again
                max_songs = config.get('max_playlist_songs', 20)
                playlist_info = await audio_extractor.get_playlist_info(playlist_id, max_songs)

                if not playlist_info or not playlist_info['songs']:
                    reply_message = TextMessage(text="❌ 無法取得播放清單資訊！")
                    await line_bot_api.reply_message(
                        ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
                    )
                    return

                # Add all valid songs
                added_count = 0
                failed_count = 0

                for song in playlist_info['songs']:
                    duration = song.get('duration', 0)
                    if not utils.check_video_duration(duration):
                        continue

                    try:
                        result = await add_song_via_api(
                            room_id, song['video_id'], user_id, user_name,
                            title=song['title'],
                            channel=song['channel'],
                            duration=duration,  # Pass the integer duration directly
                            thumbnail=song.get('thumbnail', '')
                        )
                        if result:
                            added_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        print(f"Error adding song from playlist: {e}")
                        failed_count += 1

                if added_count > 0:
                    reply_message = TextMessage(
                        text=f"✅ 播放清單匯入完成！\n"
                             f"🎵 成功新增 {added_count} 首歌曲"
                             + (f"\n⚠️ {failed_count} 首歌曲新增失敗" if failed_count > 0 else "")
                    )
                else:
                    reply_message = TextMessage(text="❌ 無法新增播放清單中的歌曲！")

            else:
                reply_message = TextMessage(text="已取消")

            # Clean up cache after use
            if cache_key in playlist_cache:
                del playlist_cache[cache_key]

            await line_bot_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )
            return


# ===== Rich Menu Manager =====
async def setup_default_rich_menu():
    """Create and set up the default rich menu for the bot.
    This rich menu will help users to create or join rooms."""
    async with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        line_bot_blob_api = AsyncMessagingApiBlob(api_client)
        rich_menu = RichMenuRequest(
            size=RichMenuBounds(width=2500, height=843),
            selected=True,
            name="CarTunes Rich Menu",
            chat_bar_text="開始使用",
            areas=[
                # Create room area (left side)
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=1250, height=843),
                    action=MessageAction(text="創建房間")
                ),
                # Join room area (right side)
                RichMenuArea(
                    bounds=RichMenuBounds(x=1250, y=0, width=1250, height=843),
                    action=PostbackAction(
                        label="加入房間",
                        data="join_room",
                        displayText="加入房間",
                        input_option="openKeyboard"
                    )
                )
            ]
        )
        rich_menu_id = (
            await line_bot_api.create_rich_menu(rich_menu_request=rich_menu)).rich_menu_id
        with open('./images/default_richmenu.png', 'rb') as image:
            await line_bot_blob_api.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=bytearray(image.read()),
                _headers={'Content-Type': 'image/png'}
            )
        await line_bot_api.set_default_rich_menu(rich_menu_id)


async def link_roomed_rich_menu(user_id: str, room_id: str):
    """Link user with a rich menu for roomed users."""
    async with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        line_bot_blob_api = AsyncMessagingApiBlob(api_client)

        room_url = f"{config['frontend_url']}/room/{room_id}?userId={user_id}"

        rich_menu = RichMenuRequest(
            size=RichMenuBounds(width=2500, height=843),
            selected=True,
            name="CarTunes Rich Menu",
            chat_bar_text="音樂播放器",
            areas=[
                # Open room website
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=0, width=1650, height=600),
                    action=URIAction(uri=room_url)
                ),
                # Play/Pause button
                RichMenuArea(
                    bounds=RichMenuBounds(x=0, y=600, width=825, height=243),
                    action=MessageAction(text="播放/暫停")
                ),
                # Next song button
                RichMenuArea(
                    bounds=RichMenuBounds(x=825, y=600, width=825, height=243),
                    action=MessageAction(text="下一首歌曲")
                ),
                # Leave room button - right side
                RichMenuArea(
                    bounds=RichMenuBounds(x=1650, y=0, width=900, height=843),
                    action=MessageAction(text="離開房間")
                )
            ]
        )
        rich_menu_id = (
            await line_bot_api.create_rich_menu(rich_menu_request=rich_menu)).rich_menu_id
        with open('images/roomed_richmenu.png', 'rb') as image:
            await line_bot_blob_api.set_rich_menu_image(
                rich_menu_id=rich_menu_id,
                body=bytearray(image.read()),
                _headers={'Content-Type': 'image/png'}
            )
        await line_bot_api.link_rich_menu_id_to_user(user_id, rich_menu_id)


async def unlink_rich_menu_from_user(user_id: str):
    """Remove rich menu from user when they leave room."""
    async with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)
        await line_bot_api.unlink_rich_menu_id_from_user(user_id)


async def cleanup_all_rich_menus():
    """Clean up all existing rich menus and user links before setting up new default menu.
    This function is useful since users who had individual rich menus (roomed rich menu) linked from
    the previous session will still have those menus attached even after the bot restarts.
    """
    async with AsyncApiClient(configuration) as api_client:
        line_bot_api = AsyncMessagingApi(api_client)

        try:
            # Get all existing rich menus
            rich_menus = await line_bot_api.get_rich_menu_list()

            # Delete all existing rich menus (this will also unlink them from users)
            for rich_menu in rich_menus.richmenus:
                try:
                    await line_bot_api.delete_rich_menu(rich_menu.rich_menu_id)
                    print(f"Deleted rich menu: {rich_menu.rich_menu_id}")
                except Exception as e:
                    print(f"Error deleting rich menu {rich_menu.rich_menu_id}: {e}")

        except Exception as e:
            print(f"Error during rich menu cleanup: {e}")


if __name__ == "__main__":
    import uvicorn

    asyncio.run(cleanup_all_rich_menus())
    asyncio.run(setup_default_rich_menu())
    uvicorn.run(app, host="0.0.0.0", port=config["line_webhook_port"])
