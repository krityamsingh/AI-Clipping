"""
Video Downloader Module
Supports downloading media from YouTube, Reels, TikTok, and direct links via yt-dlp.
"""

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from config.settings import FFMPEG_BIN, RAW_DIR


class DownloadError(Exception):
    """Exception raised for video download errors."""
    pass


class VideoDownloader:
    """
    Downloads videos from web links using yt-dlp or validates local files.
    """

    def __init__(self, download_dir: Path = RAW_DIR):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def is_url(self, source: str) -> bool:
        """Check if source string is a valid HTTP/HTTPS or YouTube link."""
        return bool(re.match(r"^(https?://|www\.|youtu)", source.strip(), re.IGNORECASE))

    def resolve_source(self, source: str) -> Path:
        """
        If source is a local file, return its Path.
        If source is a URL, download it to raw/ and return the saved Path.
        """
        source = source.strip().strip('"').strip("'")
        local_path = Path(source)
        if local_path.is_file():
            return local_path.resolve()

        # Check if file exists inside RAW_DIR
        raw_candidate = self.download_dir / source
        if raw_candidate.is_file():
            return raw_candidate.resolve()

        if not self.is_url(source):
            raise FileNotFoundError(f"Video file or valid URL not found: '{source}'")

        return self.download_url(source)

    def download_url(self, url: str) -> Path:
        """
        Download web video using yt-dlp with automatic format selection and fallback.
        """
        try:
            import yt_dlp
        except ImportError:
            raise RuntimeError("yt-dlp is not installed in the environment.")

        import uuid
        timestamp_str = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        out_template = str(self.download_dir / f"download_{timestamp_str}_%(id)s.%(ext)s")

        ydl_opts = {
            "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "merge_output_format": "mp4",
            "outtmpl": out_template,
            "ffmpeg_location": FFMPEG_BIN,
            "noplaylist": True,
            "retries": 5,
            "fragment_retries": 5,
            "socket_timeout": 30,
            "match_filter": yt_dlp.utils.match_filter_func("duration <= 14400"),
            "max_filesize": 4 * 1024 * 1024 * 1024,
            "quiet": True,
            "no_warnings": True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_path = ydl.prepare_filename(info)
            # Ensure mp4 extension
            path_obj = Path(downloaded_path)
            if not path_obj.is_file():
                mp4_cand = path_obj.with_suffix(".mp4")
                if mp4_cand.is_file():
                    return mp4_cand
            if not path_obj.is_file():
                raise DownloadError("Downloader returned no usable media file")
            return path_obj
