import asyncio

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
