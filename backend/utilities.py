import re
import sys
from os.path import exists

import yaml
from yaml import SafeLoader


def config_file_generator():
    """Generate the template of config file"""
    with open('config.yml', 'w', encoding="utf8") as file:
        file.write("""# ++--------------------------------++
# | CarTunes            (MIT LICENSE)|
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
            }
            file.close()
            return config
    except (KeyError, TypeError):
        print(
            "An error occurred while reading config.yml, please check if the file is corrected filled.\n"
            "If the problem can't be solved, consider delete config.yml and restart the program.\n")
        sys.exit()


def convert_duration_to_seconds(duration_str: str) -> int | None:
    """Convert duration string like '3:47' to seconds."""
    if not duration_str or duration_str == 'N/A':
        return None

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


def extract_video_id_from_url(url: str) -> str | None:
    """Extract video ID from YouTube URL."""
    # Pattern for https://www.youtube.com/watch?v=VIDEO_ID
    pattern1 = r'https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]+)'
    # Pattern for https://youtu.be/VIDEO_ID
    pattern2 = r'https://youtu\.be/([a-zA-Z0-9_-]+)'

    match = re.search(pattern1, url)
    if match:
        return match.group(1)

    match = re.search(pattern2, url)
    if match:
        return match.group(1)

    return None
