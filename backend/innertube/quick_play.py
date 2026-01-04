import asyncio
import random
from typing import List, Dict, Optional, Any

import httpx

import utilities as utils
from audio_extractor import get_audio_stream_info

config = utils.read_config()


async def get_mixed_quick_play_songs() -> List[Dict]:
    """Fetches a curated mix of songs based on specific popularity ranges and counts.
    In a total of 9 songs. 4 Mandarin, 2 English, 2 Korean, 1 Japanese.
    Sort order: Mandarin > English > Korean > Japanese.
    """
    categories = [
        # Mandarin (Total 4)
        # 華語金曲重溫 - Top 30, pick 1
        {"id": "RDCLAK5uy_mjAJiE8flpX8OlujSbgylHKFYt-4smINE", "top": 30, "count": 1,
         "lang": "Mandarin"},
        # 抒壓華語搖滾 - Top 30, pick 2
        {"id": "RDCLAK5uy_mC9dfCbaYLyxCzi1f4mubMKKkqucjmfu0", "top": 30, "count": 2,
         "lang": "Mandarin"},
        # 提振精神的華語嘻哈 - Top 20, pick 1
        {"id": "RDCLAK5uy_nOraQS0DsAIt0F62Go-ztE9P4ssuIiL8c", "top": 20, "count": 1,
         "lang": "Mandarin"},

        # English (Total 2)
        # 令人振奮的西洋流行樂 - Top 20, pick 1
        {"id": "RDCLAK5uy_mVJ3RRi_YBfUJnZnQxLAedQQcXHujbUcg", "top": 20, "count": 1,
         "lang": "English"},
        # 美國百大勁歌金曲 - Top 10, pick 1
        {"id": "PL4fGSI1pDJn6O1LS0XSdF3RyO0Rq_LDeI", "top": 10, "count": 1, "lang": "English"},

        # Korean (Total 2)
        # K-Pop 派對熱門歌曲 - Top 25, pick 2
        {"id": "RDCLAK5uy_l7K78k4EkjcFojhd1617rmUjY-aet6-t0", "top": 25, "count": 2,
         "lang": "Korean"},

        # Japanese (Total 1)
        # J-Pop Stress Busters - Top 15, pick 1
        {"id": "RDCLAK5uy_k_OEunzsOIJ_BOfbbTDgYN253bcPItURY", "top": 15, "count": 1,
         "lang": "Japanese"}
    ]

    all_selected_songs = []

    # Use AsyncClient for parallel fetching
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_playlist_songs(client, cat["id"]) for cat in categories]
        playlists_results = await asyncio.gather(*tasks)

    for i, songs in enumerate(playlists_results):
        cat = categories[i]
        if songs:
            # Filter to top range for guaranteed quality/popularity
            pool = songs[:cat["top"]]
            sample_size = min(len(pool), cat["count"])
            selected = random.sample(pool, sample_size)

            # Tag the song for sorting
            for s in selected:
                s['lang_tag'] = cat['lang']

            all_selected_songs.extend(selected)
        else:
            print(f"Warning: Failed to fetch playlist {cat['id']}")

    # Final Sort: Mandarin(0) > English(1) > Korean(2) > Japanese(3)
    lang_priority = {"Mandarin": 0, "English": 1, "Korean": 2, "Japanese": 3}
    all_selected_songs.sort(key=lambda x: lang_priority.get(x['lang_tag'], 99))

    # Supplemental metadata check in parallel
    metadata_tasks = []
    songs_to_update = []
    for song in all_selected_songs:
        if song['title'] == "Unknown Title" or not song['channel']:
            metadata_tasks.append(get_audio_stream_info(song['id']))
            songs_to_update.append(song)

    if metadata_tasks:
        infos = await asyncio.gather(*metadata_tasks)
        for song, info in zip(songs_to_update, infos):
            if info:
                song['title'] = info.get('title', song['title'])
                song['channel'] = info.get('uploader', song['channel'])

    return all_selected_songs


async def _fetch_playlist_songs(client: httpx.AsyncClient, playlist_id: str) -> List[Dict]:
    """Fetches and parses songs from an InnerTube browse ID using async client."""
    url = "https://music.youtube.com/youtubei/v1/browse?prettyPrint=false"
    browse_id = f"VL{playlist_id}" if not playlist_id.startswith("VL") else playlist_id

    payload = {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": "1.20240403.01.00",
                "hl": config['hl_param'],
                "gl": config['gl_param'],
                "utcOffsetMinutes": 480
            }
        },
        "browseId": browse_id
    }

    headers = {
        "Content-Type": "application/json",
        "Referer": "music.youtube.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return _parse_items_recursive(data)
    except Exception as e:
        print(f"Error fetching playlist {playlist_id}: {e}")
        return []


def _parse_items_recursive(data: Dict) -> List[Dict]:
    """Deep search for music shelf and list items in the InnerTube JSON response."""
    items = []

    def find_shelf(obj: Any) -> Optional[Dict]:
        if isinstance(obj, dict):
            for key in ['musicPlaylistShelfRenderer', 'musicShelfRenderer']:
                if key in obj: return obj[key]
            for value in obj.values():
                res = find_shelf(value)
                if res: return res
        elif isinstance(obj, list):
            for item in obj:
                res = find_shelf(item)
                if res: return res
        return None

    shelf = find_shelf(data)
    if not shelf or 'contents' not in shelf:
        return []

    for content in shelf['contents']:
        renderer = content.get('musicResponsiveListItemRenderer')
        if not renderer: continue

        video_id = renderer.get('playlistItemData', {}).get('videoId')
        if not video_id: continue

        title = "Unknown Title"
        artist = "Unknown Artist"

        flex_columns = renderer.get('flexColumns', [])
        if flex_columns:
            # Title
            try:
                title_runs = flex_columns[0]['musicResponsiveListItemFlexColumnRenderer']['text'][
                    'runs']
                if title_runs: title = title_runs[0]['text']
            except:
                pass

            # Artist
            if len(flex_columns) > 1:
                try:
                    runs = flex_columns[1]['musicResponsiveListItemFlexColumnRenderer']['text'][
                        'runs']
                    names = [r['text'] for r in runs if
                             r['text'].strip() not in ['', '•', '·', '●']]
                    if names: artist = names[0]
                except:
                    pass

        thumbnails = renderer.get('thumbnail', {}).get('musicThumbnailRenderer', {}).get(
            'thumbnail', {}).get('thumbnails', [])
        thumb_url = thumbnails[-1].get('url') if thumbnails else ""

        items.append({
            'id': video_id,
            'title': title,
            'channel': artist,
            'thumbnail': thumb_url,
            'type': 'song'
        })

    return items


if __name__ == "__main__":
    async def main():
        print("Generating Curated Mixed Dashboard (Total 9 Songs)...")
        results = await get_mixed_quick_play_songs()
        for i, song in enumerate(results, 1):
            print(
                f"{i}. [{song['lang_tag']}] {song['title']} - {song['channel']} (ID: {song['id']})")


    asyncio.run(main())
