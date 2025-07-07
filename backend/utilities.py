import re
import sys
import urllib.parse
from os.path import exists

import yaml
from yaml import SafeLoader


def config_file_generator():
    """Generate the template of config file"""
    with open('config.yml', 'w', encoding="utf8") as file:
        file.write("""# ++--------------------------------++
# | CarTunes       (AGPL-3.0 LICENSE)|
# | Made by LD                v0.1.0 |
# ++--------------------------------++

# Line Channel Access Token & Secret
# You can get it from https://developers.line.biz/console/
line_channel_access_token: ''
line_channel_secret: ''

# Backend server configuration, aka the webhook server for LINE and API endpoints for websites.
# If you change port, make sure to change the port in your reverse proxy as well.
api_endpoints_port: 5000
line_webhook_port: 5001

# Frontend website configuration, where users can interact with the music player.
# This is needed so user can access the website with LINE rich menu.
frontend_url: 'https://cartunes.playfuni.net'


# --- Song Streaming/Caching Settings ---

# Seconds of delay before the song starts playing.
# This is to ensure the song is fully loaded on frontend before playing.
# Default is 1 second.
song_start_delay_seconds: 1

# Song length limit in seconds. Default is 30 minutes (1800 seconds).
# Shows an error if the song exceeds this limit.
song_length_limit: 1800

# Audio bitrate for downloaded songs (lower = smaller files, lower quality)
# Default is 96 kbps for good balance of quality and file size.
audio_quality_kbps: 96

# Song cache settings
# Maximum cache folder size in MB. Default is 300MB.
max_cache_size_mb: 300

# Cache duration in hours. Songs will be deleted after this time since last order.
# Default is 1 hour.
cache_duration_hours: 1

# Autoplay the recommended next song if there's no more song in the queue.
# Default is true, which means as the room is created, this option is enabled.
# User can always disable or enable it with the frontend website.
autoplay_default: true

# Recommended next song search engine, two options:
# 'youtube_music' - Uses YouTube Music to find the next song, might be more random.
# 'youtube' - Uses YouTube to find the next song, might be more relevant but stuck to the same artist.
autoplay_search_engine: 'youtube_music'

# Search and recommendations API localization parameters.
# hl means Host Language, gl means Geolocation.
hl_param: 'zh-TW'
gl_param: 'TW'


# --- Rooms Broadcast/Cleanup/Throttle Settings ---

# Room's code generation logic, 6-digit code.
# Default is false, using random alphanumeric code, For example, ABC123.
# If set to true, it will only use a numeric code, For example, 123456.
numeric_room_code: false

# Pause music if no active websocket connections for this many seconds.
# Default is 10 seconds.
pause_music_after_no_connections: 10

# Rooms would be automatically deleted after this many minutes of inactivity.
# Inactivity definition: No active websocket connections, aka noone is browsing the website
# Default is 2 hours (120 minutes).
room_cleanup_after_inactivity: 120

# The interval for wss to broadcast current song progress to clients, aka the website.
# In seconds, default is 5 seconds.
progress_broadcast_interval: 5

# Throttle seconds for room's play/pause/next/autoplay-toggle actions.
# This is used to prevent same action in the same room being sent too frequently.
# Default is 1 second.
action_throttle_seconds: 1

# Throttle settings for user clicking BringSongToTop button.
# Users can bring songs to top up to 2 times within any 5-second window by default.
# This is counted per user without affecting other users.
bring_to_top_throttle:
  max_requests: 2
  window_seconds: 5
  
# LINE message throttling settings, used to prevent one user from spamming messages.
# Specifically designed to solve rich menu buttons spam. (But still applied to all messages)
# Default is 0.8 seconds.
line_message_throttle_seconds: 0.8
"""
                   )
        file.close()
    sys.exit()


def read_config():
    """Read config file.

    Check if config file exists, if not, create one.
    if exists, read config file and return config with dict type.

    :rtype: dict
    """
    if not exists('./config.yml'):
        print("Config file not found, create one by default.\nPlease finish filling config.yml")
        with open('config.yml', 'w', encoding="utf8"):
            config_file_generator()

    try:
        with open('config.yml', encoding="utf8") as file:
            data = yaml.load(file, Loader=SafeLoader)
            config = {
                'line_channel_access_token': data['line_channel_access_token'],
                'line_channel_secret': data['line_channel_secret'],
                'api_endpoints_port': data['api_endpoints_port'],
                'line_webhook_port': data['line_webhook_port'],
                'frontend_url': data['frontend_url'],
                'song_start_delay_seconds': data['song_start_delay_seconds'],
                'song_length_limit': data['song_length_limit'],
                'audio_quality_kbps': data['audio_quality_kbps'],
                'max_cache_size_mb': data['max_cache_size_mb'],
                'cache_duration_hours': data['cache_duration_hours'],
                'autoplay_default': data['autoplay_default'],
                'autoplay_search_engine': data['autoplay_search_engine'],
                'hl_param': data['hl_param'],
                'gl_param': data['gl_param'],
                'numeric_room_code': data['numeric_room_code'],
                'pause_music_after_no_connections': data['pause_music_after_no_connections'],
                'room_cleanup_after_inactivity': data['room_cleanup_after_inactivity'],
                'progress_broadcast_interval': data['progress_broadcast_interval'],
                'action_throttle_seconds': data['action_throttle_seconds'],
                'bring_to_top_throttle': {
                    'max_requests': data['bring_to_top_throttle']['max_requests'],
                    'window_seconds': data['bring_to_top_throttle']['window_seconds']
                },
                'line_message_throttle_seconds': data['line_message_throttle_seconds']
            }
            file.close()

            # Validate if LINE channel access token and secret are provided
            if not config['line_channel_access_token'] or not config['line_channel_secret']:
                print("Please fill in LINE channel access token and secret in config.yml.\n"
                      "You can get it from https://developers.line.biz/console/")
                sys.exit()

            # Validate if autoplay_search_engine is set to a valid value
            if config['autoplay_search_engine'] not in ['youtube_music', 'youtube']:
                print("Invalid autoplay_search_engine value in config.yml. "
                      "Please set it to 'youtube_music' or 'youtube'.")
                sys.exit()
            return config
    except (KeyError, TypeError):
        print(
            "An error occurred while reading config.yml, please check if the file is corrected filled.\n"
            "If the problem can't be solved, consider delete config.yml and restart the program.\n")
        sys.exit()


def convert_duration_to_seconds(duration_str: str | int) -> int | None:
    """Convert duration string like '3:47' to seconds.
    If duration is already an integer, return it directly.
    """
    if not duration_str or duration_str == 'N/A':
        return None

    if isinstance(duration_str, int):
        # If duration is already an integer (in seconds), return it directly
        return duration_str

    try:
        # Handle formats like "3:47" or "1:23:45"
        parts = duration_str.split(':')
        if len(parts) == 2:  # MM:SS
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        elif len(parts) == 3:  # HH:MM:SS
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        else:
            return None
    except (ValueError, TypeError):
        return None


def check_video_duration(duration: str) -> bool:
    """Check if the video duration is within the limit."""
    seconds = convert_duration_to_seconds(duration)
    if seconds is None:
        return False
    config = read_config()
    return seconds <= config['song_length_limit']


def is_url(text: str) -> bool:
    """Check if the given text is a valid URL."""
    try:
        result = urllib.parse.urlparse(text)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def is_youtube_url(url: str) -> bool:
    """Check if the given URL is a YouTube URL."""
    if not is_url(url):
        return False

    parsed = urllib.parse.urlparse(url)
    youtube_domains = [
        'youtube.com', 'www.youtube.com', 'm.youtube.com',
        'youtu.be', 'music.youtube.com'
    ]

    return parsed.netloc.lower() in youtube_domains


def extract_video_id_from_url(url: str) -> str | None:
    """Extract video ID from various YouTube URL formats."""
    if not is_youtube_url(url):
        return None

    # Remove any whitespace and normalize URL
    url = url.strip()

    # Patterns for different YouTube URL formats
    patterns = [
        # Standard watch URLs
        r'(?:youtube\.com|m\.youtube\.com)/watch\?.*v=([a-zA-Z0-9_-]+)',
        # Short URLs
        r'youtu\.be/([a-zA-Z0-9_-]+)',
        # Embed URLs
        r'(?:youtube\.com|m\.youtube\.com)/embed/([a-zA-Z0-9_-]+)',
        # YouTube Music URLs
        r'music\.youtube\.com/watch\?.*v=([a-zA-Z0-9_-]+)',
        # Live URLs
        r'(?:youtube\.com|m\.youtube\.com)/live/([a-zA-Z0-9_-]+)',
        # Shorts URLs
        r'(?:youtube\.com|m\.youtube\.com)/shorts/([a-zA-Z0-9_-]+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            video_id = match.group(1)
            # Additional validation for video ID format
            if re.match(r'^[a-zA-Z0-9_-]{11}$', video_id):
                return video_id

    return None
