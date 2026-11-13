"""
Configuration and Hardware Settings for AI-Clipping Engine
Optimized for Intel Core i3-1125G4 (Tiger Lake, 4 cores / 8 threads, 15 GiB RAM)
"""

from pathlib import Path
import os
import shutil
import socket

# Force IPv4 preference for network resilience on Linux systems with stalled IPv6 routes
_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_preferring_getaddrinfo(host, port, family=0, *args, **kwargs):
    return _orig_getaddrinfo(host, port, socket.AF_INET, *args, **kwargs)
socket.getaddrinfo = _ipv4_preferring_getaddrinfo

# Root directory of AI-Clipping workspace
BASE_DIR = Path(__file__).resolve().parent.parent

# Working directories
RAW_DIR = BASE_DIR / "raw"
STYLE_DIR = BASE_DIR / "style"
MODELS_DIR = BASE_DIR / "models"
AUDIO_DIR = BASE_DIR / "audio"
CAPTIONS_DIR = BASE_DIR / "captions"
THUMBNAILS_DIR = BASE_DIR / "thumbnails"
PREVIEWS_DIR = BASE_DIR / "previews"
EXPORT_DIR = BASE_DIR / "export"
SCRIPTS_DIR = BASE_DIR / "scripts"
SRC_DIR = BASE_DIR / "src"
CONFIG_DIR = BASE_DIR / "config"
TESTS_DIR = BASE_DIR / "tests"
LOGS_DIR = BASE_DIR / "logs"
BIN_DIR = BASE_DIR / "bin"

for directory in [
    RAW_DIR, STYLE_DIR, MODELS_DIR, AUDIO_DIR, CAPTIONS_DIR,
    THUMBNAILS_DIR, PREVIEWS_DIR, EXPORT_DIR, SCRIPTS_DIR,
    SRC_DIR, CONFIG_DIR, TESTS_DIR, LOGS_DIR, BIN_DIR
]:
    directory.mkdir(parents=True, exist_ok=True)

# Binaries resolution (prefer local workspace bin, fallback to PATH)
def get_binary_path(name: str) -> str:
    local_path = BIN_DIR / name
    if local_path.is_file() and os.access(local_path, os.X_OK):
        return str(local_path)
    system_path = shutil.which(name)
    if system_path:
        return system_path
    return name

FFMPEG_BIN = get_binary_path("ffmpeg")
FFPROBE_BIN = get_binary_path("ffprobe")
HYPERFRAMES_BIN = str(BASE_DIR / "node_modules" / ".bin" / "hyperframes")

# Hardware Optimization Settings (Intel Core i3-1125G4: 4 Cores / 8 Threads)
PHYSICAL_CORES = 4
TOTAL_THREADS = os.cpu_count() or 8
# Configured for maximum throughput utilizing all 8 threads across all 4 cores
CPU_THREADS = TOTAL_THREADS
MAX_CONCURRENT_JOBS = 1

# Faster-Whisper Settings
WHISPER_MODEL_NAME = "base"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_DOWNLOAD_ROOT = str(MODELS_DIR / "whisper")

# Video Encoding Settings
ENCODER_CODEC = "libx264"
ENCODER_PRESET = "veryfast"
ENCODER_CRF_FINAL = 22
ENCODER_CRF_PREVIEW = 28
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "192k"
AUDIO_SAMPLE_RATE = 44100

# Video Aspect Ratio Presets
ASPECT_RATIOS = {
    "9:16": {
        "name": "Vertical (Shorts / Reels / TikTok)",
        "final": (1080, 1920),
        "preview": (720, 1280),
    },
    "16:9": {
        "name": "Landscape (YouTube / Standard)",
        "final": (1920, 1080),
        "preview": (1280, 720),
    },
    "1:1": {
        "name": "Square (Instagram / Feed)",
        "final": (1080, 1080),
        "preview": (720, 720),
    }
}

DEFAULT_DURATIONS = [15, 30, 45, 60]

# Audio Analysis & Scene Thresholds
SCENE_DETECTOR_THRESHOLD = 27.0
SILENCE_THRESHOLD_DB = -36.0
MIN_SILENCE_DURATION_SEC = 0.4
PEAK_PERCENTILE = 92.0
