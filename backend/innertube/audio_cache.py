import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Set, Optional
import subprocess

import yt_dlp

logger = logging.getLogger(__name__)


class AudioCacheManager:
    def __init__(self, max_cache_size_mb: int, cache_duration_hours: int, audio_quality_kbps: int, loudness_normalization: bool):
        self.cache_dir = tempfile.mkdtemp(prefix="cartunes_audio_")
        self.cached_files: Dict[
            str, dict] = {}  # video_id -> {path, downloaded_at, last_ordered_at, size}
        self.downloading: Set[str] = set()  # Track currently downloading videos
        self.max_cache_size_mb = max_cache_size_mb
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.audio_quality = str(audio_quality_kbps)
        self.loudness_normalization = loudness_normalization
        logger.info(f"Audio cache initialized at: {self.cache_dir}")
        logger.info(
            f"Cache settings: {self.max_cache_size_mb}MB max, "
            f"{cache_duration_hours}h duration, {self.audio_quality}kbps quality, "
            f"Normalize Audio: {loudness_normalization}")

    def get_cache_path(self, video_id: str) -> Optional[str]:
        """Get cached file path if exists and valid"""
        if video_id in self.cached_files:
            file_info = self.cached_files[video_id]
            file_path = file_info['path']

            # Check if file still exists and not expired (based on last_ordered_at)
            if (os.path.exists(file_path) and
                    datetime.now() - file_info['last_ordered_at'] < self.cache_duration):
                return file_path
            else:
                # Remove expired/missing file from cache
                self._remove_from_cache(video_id)

        return None

    def is_downloading(self, video_id: str) -> bool:
        """Check if video is currently being downloaded"""
        return video_id in self.downloading

    def refresh_cache_timer(self, video_id: str):
        """Refresh the cache timer for a song when it's ordered again"""
        if video_id in self.cached_files:
            self.cached_files[video_id]['last_ordered_at'] = datetime.now()
            logger.debug(f"Refreshed cache timer for {video_id}")

    async def download_audio(self, video_id: str, priority: bool = False) -> Optional[str]:
        """Download audio file and return local path"""
        if video_id in self.downloading:
            # Wait for ongoing download
            while video_id in self.downloading:
                await asyncio.sleep(0.5)
            # Refresh timer since this is a new request for the same song
            self.refresh_cache_timer(video_id)
            return self.get_cache_path(video_id)

        # Check if already cached
        cached_path = self.get_cache_path(video_id)
        if cached_path:
            # Refresh timer since this song is being requested again
            self.refresh_cache_timer(video_id)
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
            ffmpeg_path = shutil.which('ffmpeg')

            # Configure yt-dlp to extract audio and convert to MP3 using ffmpeg
            if ffmpeg_path:
                logger.warning(f"Found ffmpeg at: {ffmpeg_path}")
                ydl_opts = {
                    'format': 'bestaudio/best',  # Select the best audio format
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',  # Convert to MP3
                        'preferredquality': self.audio_quality,  # Use configurable quality
                    }],
                    'outtmpl': os.path.join(self.cache_dir, f'{video_id}.%(ext)s'),
                    'quiet': True,
                    'no_warnings': True,
                    'ffmpeg_location': ffmpeg_path
                }
            else:
                logger.warning(f"ffmpeg not found in PATH, using yt-dlp defaults.")

            def download_sync():
                # This function runs in a separate thread to avoid blocking
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)

            await asyncio.to_thread(download_sync)
            # The output file will now always be .mp3 due to postprocessor
            downloaded_file = os.path.join(self.cache_dir, f'{video_id}.mp3')

            if not os.path.exists(downloaded_file):
                logger.error(
                    f"Downloaded MP3 file not found for video {video_id} "
                    f"after yt_dlp.extract_info.")
                # Fallback: try to find any file that starts with the video ID
                cache_files = os.listdir(self.cache_dir)
                found_fallback = False
                for file in cache_files:
                    if file.startswith(video_id):
                        downloaded_file = os.path.join(self.cache_dir, file)
                        logger.info(
                            f"Found file by prefix match as fallback: {downloaded_file}")
                        found_fallback = True
                        break
                if not found_fallback:
                    return None

            def _normalize_audio():
                # Start to normalize loudness
                normalized_file = os.path.join(self.cache_dir, f'{video_id}_normalized.mp3')
                normalization_cmd = [
                    ffmpeg_path, "-y", "-loglevel", "error", "-i",
                    downloaded_file, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                    normalized_file
                ]

                logger.info(f"Normalizing loudness for {video_id}...")
                subprocess.run(normalization_cmd, check=True)

                # Replace original with normalized version
                os.remove(downloaded_file)
                os.rename(normalized_file, downloaded_file)
                logger.info(f"Loudness normalized and saved: {downloaded_file}")

            if self.loudness_normalization:
                await asyncio.to_thread(_normalize_audio)

            # Add to cache with both timestamps
            current_time = datetime.now()
            file_size = os.path.getsize(downloaded_file)
            self.cached_files[video_id] = {
                'path': downloaded_file,
                'downloaded_at': current_time,
                'last_ordered_at': current_time,  # Same as download time initially
                'size': file_size
            }

            logger.info(
                f"Audio downloaded and converted to MP3 for {video_id}: "
                f"{downloaded_file} ({file_size} bytes) at {self.audio_quality}kbps")
            return downloaded_file

        except Exception as e:
            logger.error(f"Error downloading or converting audio for {video_id}: {e}")
            return None

    async def _cleanup_cache(self):
        """Remove old files and maintain cache size limit"""
        # Remove expired files (based on last_ordered_at)
        expired_videos = []
        for video_id, file_info in self.cached_files.items():
            if datetime.now() - file_info['last_ordered_at'] > self.cache_duration:
                expired_videos.append(video_id)

        for video_id in expired_videos:
            self._remove_from_cache(video_id)

        # If still oversize limit, remove the oldest files (by last_ordered_at)
        total_size_mb = self._get_total_cache_size_mb()
        if total_size_mb >= self.max_cache_size_mb:
            # Sort by last_ordered_at and remove oldest
            sorted_files = sorted(
                self.cached_files.items(),
                key=lambda x: x[1]['last_ordered_at']
            )

            # Remove files until under limit
            for video_id, file_info in sorted_files:
                if total_size_mb < self.max_cache_size_mb:
                    break
                self._remove_from_cache(video_id)
                total_size_mb = self._get_total_cache_size_mb()

    def _get_total_cache_size_mb(self) -> float:
        """Get total cache size in MB"""
        total_size_bytes = sum(file_info['size'] for file_info in self.cached_files.values())
        return total_size_bytes / (1024 * 1024)  # Convert to MB

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