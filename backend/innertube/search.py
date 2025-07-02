# The InnerTube API allows you to search for videos/musics on YouTube without
# using the official YouTube Data API.
import requests
import utilities as utils

config = utils.read_config()


def search_youtube(query: str) -> list:
    """Searches YouTube for videos based on the query.
    :param query: The search query.
    :return: A list of dictionaries containing video details.
    :rtype: List
    """
    data = _search_youtube(query)
    results = parse_youtube_results(data)
    filtered_results = [item for item in results if item.get('type') not in ('short', 'live')]
    return filtered_results


def search_youtube_music(query: str) -> list:
    """Searches YouTube Music for songs based on the query.
    :param query: The search query.
    :return: A list of dictionaries containing music details.
    :rtype: List
    """
    data = _search_youtube_music(query)
    return parse_youtube_music_search_results(data)


def _search_youtube(query: str) -> dict:
    url = "https://youtubei.googleapis.com/youtubei/v1/search?prettyPrint=false"

    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240401.05.00",
                "hl": config['hl_param'],
                "gl": config['gl_param']
            }
        },
        "query": query,
        "params": "EgIQAfABAQ=="  # Videos only filter
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    response = requests.post(url, json=payload, headers=headers)
    return response.json()


def _search_youtube_music(query: str) -> dict:
    url = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"

    payload = {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": "1.20240403.01.00",
                "hl": config['hl_param'],
                "gl": config['gl_param']
            }
        },
        "query": query,
        "params": "Eg-KAQwIARAAGAAgACgAMABqChADEAQQCRAFEAo="
    }

    headers = {
        "Content-Type": "application/json",
        "Referer": "music.youtube.com"
    }

    response = requests.post(url, json=payload, headers=headers)
    return response.json()


def parse_youtube_results(data: dict) -> list:
    """Parses the JSON response from the YouTube InnerTube API to extract video details.
    :param data: The JSON response from the YouTube InnerTube API.
    :return: A list of dictionaries containing video details.
    :rtype: List
    """
    results = []
    if 'contents' not in data:
        return results

    # Navigate to the list of items
    primary_contents = data.get('contents', {}).get('twoColumnSearchResultsRenderer', {}).get(
        'primaryContents', {})
    contents = primary_contents.get('sectionListRenderer', {}).get('contents', [])

    for content in contents:
        if 'itemSectionRenderer' in content:
            for item in content['itemSectionRenderer']['contents']:
                if 'videoRenderer' in item:
                    video_info = item['videoRenderer']
                    title = video_info.get('title', {}).get('runs', [{}])[0].get('text')
                    video_id = video_info.get('videoId')
                    channel_name = video_info.get('ownerText', {}).get('runs', [{}])[0].get('text')
                    published_time = video_info.get('publishedTimeText', {}).get('simpleText')
                    duration = video_info.get('lengthText', {}).get('simpleText')
                    view_count = video_info.get('viewCountText', {}).get('simpleText')
                    thumbnail_url = video_info.get('thumbnail', {}).get('thumbnails', [{}])[0].get(
                        'url')

                    results.append({
                        'type': 'video',
                        'id': video_id,
                        'title': title,
                        'channel': channel_name,
                        'published': published_time,
                        'duration': duration,
                        'views': view_count,
                        'thumbnail': thumbnail_url
                    })

                if 'reelShelfRenderer' in item:
                    for reel in item['reelShelfRenderer']['items']:
                        reel_info = reel.get('shortsLockupViewModel', {})
                        if not reel_info:
                            continue

                        # Extract details for shorts
                        video_id = reel_info.get('onTap', {}).get('innertubeCommand', {}).get(
                            'reelWatchEndpoint', {}).get('videoId')
                        title = reel_info.get('overlayMetadata', {}).get('primaryText', {}).get(
                            'content')
                        views = reel_info.get('overlayMetadata', {}).get('secondaryText', {}).get(
                            'content')
                        thumbnail_url = reel_info.get('thumbnail', {}).get('sources', [{}])[0].get(
                            'url')

                        results.append({
                            'type': 'short',
                            'id': video_id,
                            'title': title,
                            'views': views,
                            'thumbnail': thumbnail_url
                        })
    return results


def parse_youtube_music_search_results(data: dict) -> list:
    """Parses the JSON response from the YouTube Music InnerTube API.
    :param data: JSON response from the music search API.
    :return: A list of dictionaries containing music details.
    :rtype: List
    """
    results = []

    # Navigate to the content sections (shelves)
    try:
        # Find the selected tab's content
        tabs = data['contents']['tabbedSearchResultsRenderer']['tabs']
        sections = []
        for tab in tabs:
            if tab.get('tabRenderer', {}).get('selected', False):
                sections = tab.get('tabRenderer', {}).get('content', {}).get('sectionListRenderer',
                                                                             {}).get('contents', [])
                break
    except KeyError:
        return results  # Return empty if the structure is unexpected

    # Iterate over different shelves (e.g., 'Songs', 'Videos')
    for section in sections:
        if 'musicShelfRenderer' not in section:
            continue

        shelf = section['musicShelfRenderer']
        shelf_type = shelf.get('title', {}).get('runs', [{}])[0].get('text', 'unknown')

        for item in shelf.get('contents', []):
            if 'musicResponsiveListItemRenderer' not in item:
                continue

            item_renderer = item['musicResponsiveListItemRenderer']

            # Extract common data
            video_id = item_renderer.get('playlistItemData', {}).get('videoId')
            thumbnail = \
                item_renderer.get('thumbnail', {}).get('musicThumbnailRenderer', {}).get(
                    'thumbnail', {}).get('thumbnails', [{}])[-1].get('url')

            # The main info is split into several 'flexColumns'
            flex_columns = item_renderer.get('flexColumns', [])
            if not flex_columns:
                continue

            # First column is always the title
            title = flex_columns[0].get('musicResponsiveListItemFlexColumnRenderer', {}).get(
                'text', {}).get('runs', [{}])[0].get('text')

            # Initialize details
            artists, album, duration, views = None, None, None, None

            # Second column contains artists, album, and duration for songs
            # The structure of this column's text runs can vary
            if len(flex_columns) > 1:
                detail_runs = flex_columns[1].get('musicResponsiveListItemFlexColumnRenderer',
                                                  {}).get('text', {}).get('runs', [])
                # Filter out separators like ' • '
                details = [run.get('text') for run in detail_runs if run.get('text') not in [' • ']]

                # Based on the number of items, assign to artist, album, duration
                if len(details) == 3:  # Artist, Album, Duration
                    artists = details[0]
                    album = details[1]
                    duration = details[2]
                elif len(details) == 2:  # Artist, Duration (album is missing)
                    artists = details[0]
                    duration = details[1]
                elif len(details) == 1:  # Only Artist/Channel
                    artists = details[0]

            # Third column often contains view/play count
            if len(flex_columns) > 2:
                views_runs = flex_columns[2].get('musicResponsiveListItemFlexColumnRenderer',
                                                 {}).get('text', {}).get('runs')
                if views_runs:
                    views = views_runs[0].get('text')

            results.append({
                'type': shelf_type.lower(),
                'id': video_id,
                'title': title,
                'channel': artists,
                'album': album,
                'duration': duration,
                'views': views,
                'thumbnail': thumbnail
            })

    return results
