import asyncio
import re

import yt_dlp


async def get_audio_stream_info(video_id: str) -> dict | None:
    """Extract audio stream information from a video ID using yt-dlp.
    :param video_id: The YouTube video or audio ID.
    :return: Dict containing audio stream URLs and metadata
    """
    url = f'https://www.youtube.com/watch?v={video_id}'
    ydl_opts = {
        'format': 'bestaudio/best',  # Prefer audio-only formats
        'noplaylist': True,
        'extract_flat': False,
        'quiet': True,
        'no_warnings': True,
    }

    def extract_sync():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)

                # Filter for audio formats
                audio_formats = []
                for fmt in info.get('formats', []):
                    # Check if the format contains audio
                    if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                        audio_formats.append({
                            'url': fmt['url'],
                            'format_id': fmt.get('format_id'),
                            'ext': fmt.get('ext'),
                            'abr': fmt.get('abr'),  # Audio bitrate
                            'filesize': fmt.get('filesize'),
                            'protocol': fmt.get('protocol'),
                        })

                # If no audio-only formats, get the best format with audio
                if not audio_formats:
                    for fmt in info.get('formats', []):
                        if fmt.get('acodec') != 'none':
                            audio_formats.append({
                                'url': fmt['url'],
                                'format_id': fmt.get('format_id'),
                                'ext': fmt.get('ext'),
                                'abr': fmt.get('abr'),
                                'vbr': fmt.get('vbr'),
                                'filesize': fmt.get('filesize'),
                                'protocol': fmt.get('protocol'),
                            })
                            break

                return {
                    'id': info.get('id'),
                    'title': info.get('title'),
                    'duration': info.get('duration'),
                    'channel': info.get('uploader'),
                    'audio_formats': audio_formats,
                    'thumbnail': info.get('thumbnail'),
                }

            except Exception as e:
                print(f"Error extracting audio stream info: {e}")
                return None

    return await asyncio.to_thread(extract_sync)


async def get_playlist_info(playlist_id: str, max_songs: int = 20) -> dict | None:
    """Extract playlist information and songs using yt-dlp.

    :param playlist_id: The YouTube playlist ID
    :param max_songs: Maximum number of songs to fetch from playlist
    :return: Dict containing playlist info and songs list
    """
    url = f'https://www.youtube.com/playlist?list={playlist_id}'

    ydl_opts = {
        'extract_flat': 'in_playlist',  # Fast extraction without downloading
        'playlistend': max_songs,  # Limit number of entries
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,  # Skip private/deleted videos
    }

    def extract_sync():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)

                if not info or 'entries' not in info:
                    return None

                playlist_data = {
                    'id': playlist_id,
                    'title': info.get('title', 'Unknown Playlist'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'total_songs': len(info['entries']),
                    'songs': []
                }

                # Process each video in playlist
                for entry in info['entries']:
                    if not entry:  # Skip None entries (private/deleted videos)
                        continue

                    # Filter out live streams
                    if entry.get('live_status') == 'is_live':
                        continue

                    song_data = {
                        'video_id': entry.get('id'),
                        'title': entry.get('title', 'Unknown Title'),
                        'channel': entry.get('uploader', 'Unknown Artist'),
                        'duration': entry.get('duration'),  # In seconds
                        'thumbnail': re.sub(  # Use higher res thumbnail
                            r'/(hqdefault|mqdefault|sddefault|default|maxresdefault)\.jpg',
                            '/hq720.jpg',
                            entry.get('thumbnails', [{}])[-1].get('url', '')) if entry.get(
                            'thumbnails') else ''
                    }

                    # Only add if we have essential data
                    if song_data['video_id'] and song_data['title']:
                        playlist_data['songs'].append(song_data)

                return playlist_data

            except Exception as e:
                print(f"Error extracting playlist info: {e}")
                return None

    return await asyncio.to_thread(extract_sync)


if __name__ == "__main__":
    # For YouTube eNCVyQylZ6c
    # For UouTube Music xquV6OUwNOw
    async def main():
        result = await get_audio_stream_info('eNCVyQylZ6c')

        if result is not None:
            print(f"Title: {result['title']}")
            print(f"Duration: {result['duration']} seconds")
            print("Available audio streams:")
            for fmt in result['audio_formats']:
                print(f"  - {fmt['format_id']}: {fmt['url']}")


    asyncio.run(main())
