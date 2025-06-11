import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Set, Optional

import yt_dlp

logger = logging.getLogger(__name__)


class AudioCacheManager:
    def __init__(self, max_cache_size: int = 10, cache_duration_hours: int = 2):
        self.cache_dir = tempfile.mkdtemp(prefix="cartunes_audio_")
        self.cached_files: Dict[str, dict] = {}  # video_id -> {path, downloaded_at, size}
        self.downloading: Set[str] = set()  # Track currently downloading videos
        self.max_cache_size = max_cache_size
        self.cache_duration = timedelta(hours=cache_duration_hours)
        logger.info(f"Audio cache initialized at: {self.cache_dir}")

    def get_cache_path(self, video_id: str) -> Optional[str]:
        """Get cached file path if exists and valid"""
        if video_id in self.cached_files:
            file_info = self.cached_files[video_id]
            file_path = file_info['path']

            # Check if file still exists and not expired
            if (os.path.exists(file_path) and
                    datetime.now() - file_info['downloaded_at'] < self.cache_duration):
                return file_path
            else:
                # Remove expired/missing file from cache
                self._remove_from_cache(video_id)

        return None

    def is_downloading(self, video_id: str) -> bool:
        """Check if video is currently being downloaded"""
        return video_id in self.downloading

    async def download_audio(self, video_id: str, priority: bool = False) -> Optional[str]:
        """Download audio file and return local path"""
        if video_id in self.downloading:
            # Wait for ongoing download
            while video_id in self.downloading:
                await asyncio.sleep(0.5)
            return self.get_cache_path(video_id)

        # Check if already cached
        cached_path = self.get_cache_path(video_id)
        if cached_path:
            return cached_path

        self.downloading.add(video_id)

        try:
            return await self._download_file(video_id)
        finally:
            self.downloading.discard(video_id)

    async def _download_file(self, video_id: str) -> Optional[str]:
        """Actually download the audio file"""
        try:
            # Clean cache if needed
            await self._cleanup_cache()

            url = f'https://www.youtube.com/watch?v={video_id}'

            # Simple download without any conversion
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
                'outtmpl': os.path.join(self.cache_dir, f'{video_id}.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Download the audio
                info = ydl.extract_info(url, download=True)

                # Look for downloaded file
                expected_extensions = ['m4a', 'webm', 'mp4', 'mp3', 'ogg']
                downloaded_file = None

                for ext in expected_extensions:
                    potential_file = os.path.join(self.cache_dir, f'{video_id}.{ext}')
                    if os.path.exists(potential_file):
                        downloaded_file = potential_file
                        logger.info(f"Found downloaded file: {downloaded_file}")
                        break

                if not downloaded_file:
                    # Debug: List all files in cache dir to see what was actually downloaded
                    cache_files = os.listdir(self.cache_dir)
                    logger.error(f"Downloaded file not found for video {video_id}")
                    logger.error(f"Cache dir contents: {cache_files}")

                    # Try to find any file that starts with the video ID
                    for file in cache_files:
                        if file.startswith(video_id):
                            downloaded_file = os.path.join(self.cache_dir, file)
                            logger.info(f"Found file by prefix match: {downloaded_file}")
                            break

                    if not downloaded_file:
                        return None

                # If the file is MP4, rename it to MP3 for better browser compatibility
                if downloaded_file.endswith('.mp4'):
                    mp3_file = downloaded_file.replace('.mp4', '.mp3')
                    try:
                        os.rename(downloaded_file, mp3_file)
                        downloaded_file = mp3_file
                        logger.info(f"Renamed MP4 to MP3: {downloaded_file}")
                    except OSError as e:
                        logger.warning(f"Failed to rename MP4 to MP3: {e}, keeping original")

                # Add to cache
                file_size = os.path.getsize(downloaded_file)
                self.cached_files[video_id] = {
                    'path': downloaded_file,
                    'downloaded_at': datetime.now(),
                    'size': file_size
                }

                logger.info(
                    f"Audio downloaded for {video_id}: {downloaded_file} ({file_size} bytes)")
                return downloaded_file

        except Exception as e:
            logger.error(f"Error downloading audio for {video_id}: {e}")
            return None

    async def _cleanup_cache(self):
        """Remove old files and maintain cache size limit"""
        # Remove expired files
        expired_videos = []
        for video_id, file_info in self.cached_files.items():
            if datetime.now() - file_info['downloaded_at'] > self.cache_duration:
                expired_videos.append(video_id)

        for video_id in expired_videos:
            self._remove_from_cache(video_id)

        # If still over limit, remove oldest files
        if len(self.cached_files) >= self.max_cache_size:
            # Sort by download time and remove oldest
            sorted_files = sorted(
                self.cached_files.items(),
                key=lambda x: x[1]['downloaded_at']
            )

            files_to_remove = sorted_files[:len(sorted_files) - self.max_cache_size + 1]
            for video_id, _ in files_to_remove:
                self._remove_from_cache(video_id)

    def _remove_from_cache(self, video_id: str):
        """Remove file from cache and filesystem"""
        if video_id in self.cached_files:
            file_path = self.cached_files[video_id]['path']
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"Removed cached file: {file_path}")
            except OSError as e:
                logger.error(f"Error removing cached file {file_path}: {e}")

            del self.cached_files[video_id]

    async def preload_queue_songs(self, video_ids: list):
        """Preload upcoming songs in background"""
        for video_id in video_ids[:5]:  # Only preload next 5 songs
            if not self.get_cache_path(video_id) and not self.is_downloading(video_id):
                # Download in background without waiting
                asyncio.create_task(self.download_audio(video_id))

    def cleanup_all(self):
        """Clean up all cached files and temp directory"""
        try:
            if os.path.exists(self.cache_dir):
                shutil.rmtree(self.cache_dir)
                logger.info(f"Cleaned up audio cache directory: {self.cache_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up cache directory: {e}")


audio_cache = AudioCacheManager()
