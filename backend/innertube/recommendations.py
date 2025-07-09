from typing import List, Dict, Optional

import httpx

import utilities as utils

config = utils.read_config()


async def get_yt_recommendations(video_id: str) -> Optional[List[Dict]]:
    """Fetches recommended videos for a given video ID using the InnerTube API.

    :param video_id: The YouTube video ID.
    :return: A list of dictionaries containing recommended video details, or None on error.
    """
    url = "https://youtubei.googleapis.com/youtubei/v1/next?prettyPrint=false"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240401.05.00",
                "hl": config['hl_param'],
                "gl": config['gl_param']
            }
        },
        "videoId": video_id,
        "params": "EgIQAfABAQ=="  # Videos only filter
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return _parse_recommendations_payload(data)
    except Exception as e:
        print(f"Error fetching recommendations for {video_id}: {e}")
        return None


async def get_yt_music_recommendations(video_id: str) -> Optional[List[Dict]]:
    """Fetches recommended music tracks by first getting the automix playlist details,
    then fetching that playlist's contents to get the recommended tracks.
    """
    playlist_details = await _get_playlist_details(video_id)
    if not playlist_details:
        return None

    playlist_id = playlist_details['playlistId']
    params = playlist_details['params']
    url = "https://youtubei.googleapis.com/youtubei/v1/next?prettyPrint=false"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": "1.20240403.01.00",
                "hl": config['hl_param'],
                "gl": config['gl_param']
            }
        },
        "playlistId": playlist_id,
        "params": params
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            return _parse_watch_playlist_response(data)
    except Exception as e:
        print(f"Error fetching YouTube Music playlist contents: {e}")
        return None


def _parse_recommendations_payload(data: Dict) -> List[Dict]:
    """Parses the JSON response from the InnerTube /v1/next endpoint to extract recommended videos.
    This is specifically used for get_yt_recommendations and is not used for music recommendations.
    """
    results = []
    try:
        primary_results = data['contents']['twoColumnWatchNextResults']
        recommended_section = primary_results['secondaryResults']['secondaryResults']['results']
    except KeyError:
        return []

    for item in recommended_section:
        if 'compactVideoRenderer' in item:
            video_info = item['compactVideoRenderer']
            video_id = video_info.get('videoId')
            title = video_info.get('title', {}).get('simpleText')

            channel_name_runs = video_info.get('longBylineText', {}).get('runs')
            channel_name = channel_name_runs[0].get('text') if channel_name_runs else None

            duration = video_info.get('lengthText', {}).get('simpleText')
            view_count = video_info.get('viewCountText', {}).get('simpleText')
            thumbnail_url = video_info.get('thumbnail', {}).get('thumbnails', [{}])[-1].get(
                'url')  # Get highest quality thumb

            if all([video_id, title, channel_name]):  # Ensure essential data is present
                results.append({
                    'type': 'video',
                    'id': video_id,
                    'title': title,
                    'channel': channel_name,
                    'duration': duration,
                    'views': view_count,
                    'thumbnail': thumbnail_url
                })
    return results


async def _get_playlist_details(video_id: str) -> Optional[Dict]:
    """Hits the /next endpoint to get playlistId and params for YouTube Music auto-mix,
    an auto-generated recommended playlist.
    """
    url = "https://youtubei.googleapis.com/youtubei/v1/next?prettyPrint=false"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": "1.20240403.01.00"
            }
        },
        "videoId": video_id,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            # Navigate through the JSON to find the automix renderer's endpoint
            playlist_panel = \
                data['contents']['singleColumnMusicWatchNextResultsRenderer']['tabbedRenderer'][
                    'watchNextTabbedResultsRenderer']['tabs'][0]['tabRenderer']['content'][
                    'musicQueueRenderer']['content']['playlistPanelRenderer']

            automix_renderer = playlist_panel['contents'][1]['automixPreviewVideoRenderer']
            watch_endpoint = \
                automix_renderer['content']['automixPlaylistVideoRenderer']['navigationEndpoint'][
                    'watchPlaylistEndpoint']

            playlist_id = watch_endpoint['playlistId']
            params = watch_endpoint['params']

            return {'playlistId': playlist_id, 'params': params}

    except Exception as e:
        print(f"Error finding playlist details for {video_id}: {e}")
        return None


def _parse_watch_playlist_response(data: Dict) -> List[Dict]:
    """Parses the response from the /next endpoint (with playlist context) to get the track list.
    This is used to get YouTube Music recommendations when already got its auto-remix playlist ID.
    """
    results = []
    try:
        track_list = \
            data['contents']['singleColumnMusicWatchNextResultsRenderer']['tabbedRenderer'][
                'watchNextTabbedResultsRenderer']['tabs'][0]['tabRenderer']['content'][
                'musicQueueRenderer']['content']['playlistPanelRenderer']['contents']
    except (KeyError, IndexError):
        return []

    # The first song in the radio playlist is often the song that started it. We skip it.
    for item in track_list[1:]:
        if 'playlistPanelVideoRenderer' not in item:
            continue

        renderer = item['playlistPanelVideoRenderer']

        video_id = renderer.get('videoId')
        title_runs = renderer.get('title', {}).get('runs')
        title = title_runs[0].get('text') if title_runs else None

        byline_runs = renderer.get('longBylineText', {}).get('runs', [])
        details = [run.get('text') for run in byline_runs if run.get('text') not in [' • ', ' ']]

        artists = details[0] if len(details) > 0 else None
        album_or_views = details[1] if len(details) > 1 else None  # Can be album or view count

        duration_runs = renderer.get('lengthText', {}).get('runs')
        duration = duration_runs[0].get('text') if duration_runs else None
        thumbnail_url = renderer.get('thumbnail', {}).get('thumbnails', [{}])[-1].get('url')

        if all([video_id, title, artists]):
            results.append({
                'type': 'song', 'id': video_id, 'title': title, 'channel': artists,
                'album': album_or_views, 'duration': duration, 'thumbnail': thumbnail_url
            })

    return results


if __name__ == "__main__":
    target_video_id = 'B1tArM5XYuc'
    use_music_search = False


    async def main():
        if use_music_search:
            recommendations = await get_yt_music_recommendations(target_video_id)

            if recommendations:
                print(f"\nSuccessfully found {len(recommendations)} recommended songs:")
                for i, track in enumerate(recommendations[:10]):
                    print(
                        f"  {i + 1:2d}. {track['title']} by {track['channel']} ({track['duration']})")
            else:
                print("\nCould not retrieve any recommendations.")

        else:
            recommendations = await get_yt_recommendations(target_video_id)

            if recommendations:
                print(f"\nFound {len(recommendations)} recommended videos:")
                for i, video in enumerate(recommendations[:10]):
                    print(f"  {i + 1}. {video['title']}")
                    print(f"     Channel: {video['channel']}")
                    print(f"     ID: {video['id']}, Duration: {video['duration']}\n")
            else:
                print("Could not retrieve recommendations.")


    import asyncio

    asyncio.run(main())
