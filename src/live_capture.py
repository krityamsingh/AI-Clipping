"""Bounded recording of a playable live-media URL into local Matroska chunks.

Works with URLs FFmpeg can directly open (e.g., an HLS .m3u8 manifest).
It does NOT bypass platform authentication/DRM or turn an ordinary webpage
into a live stream. Existing VOD media should use agent_cli auto/analyze.
"""
import json
import math
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from config.settings import FFMPEG_BIN, RAW_DIR


def capture_live(url, *, output_dir=None, chunk_seconds=180, chunks=2):
    """Capture a finite contiguous live session; split only on source keyframes.

    Returns finalized file paths and their probed durations. No background
    scheduling; this command runs synchronously for the requested period.
    """
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https", "rtmp", "rtmps"} or not parsed.netloc:
        raise ValueError("Capture URL must be a playable HTTP(S)/RTMP stream URL")
    if not isinstance(chunks, int) or not 1 <= chunks <= 24:
        raise ValueError("chunks must be 1..24")
    if not math.isfinite(chunk_seconds) or not 10 <= chunk_seconds <= 3600:
        raise ValueError("chunk_seconds must be 10..3600")
    folder = Path(output_dir or RAW_DIR / "live_capture").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if list(folder.glob("segment_*.mkv")):
        raise ValueError("Capture directory must not contain previous segment_*.mkv files")
    duration = chunk_seconds * chunks
    template = str(folder / "segment_%03d.mkv")
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-nostdin",
           "-y", "-i", str(url), "-t", str(duration),
           "-map", "0:v:0", "-map", "0:a:0?",
           "-c", "copy", "-f", "segment",
           "-segment_time", str(chunk_seconds),
           "-reset_timestamps", "1", template]
    # Network sources can disconnect. Don't claim the requested duration was captured.
    result = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=max(90, int(duration * 3 + 90)))
    files = sorted(folder.glob("segment_*.mkv"))
    if result.returncode and not files:
        raise RuntimeError("Live capture failed: " + result.stderr[-1500:])
    from src.video_analyzer import VideoAnalyzer
    analyzer = VideoAnalyzer()
    clips = []
    for item in files:
        if item.stat().st_size <= 0:
            continue
        try:
            data = analyzer.probe_video(item)
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError("Incomplete capture: " + str(item)) from exc
        if data["duration"] >= 1:
            clips.append({"source": str(item), "duration": data["duration"],
                          "size_bytes": item.stat().st_size})
    if not clips:
        raise RuntimeError("No playable chunks captured: " + result.stderr[-900:])
    return {
        "status": "captured" if result.returncode == 0 else "partial_capture",
        "directory": str(folder),
        "segments": clips,
        "stderr_tail": result.stderr[-500:] if result.returncode else "",
        "notice": "Chunk boundaries depend on stream keyframes; short streams may yield fewer parts."
    }
