"""
System Environment and Binaries Test
Verifies Python, Node, FFmpeg, FFprobe, HyperFrames, and GPU/CPU encoders.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import FFMPEG_BIN, FFPROBE_BIN, HYPERFRAMES_BIN, CPU_THREADS


def test_python_environment():
    print(f"Testing Python runtime: {sys.version.split()[0]}... ", end="")
    assert sys.version_info >= (3, 10), "Python 3.10+ required"
    print("PASS")


def test_node_and_npm():
    print("Testing Node.js... ", end="")
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js binary not found"
    res = subprocess.run([node_bin, "-v"], capture_output=True, text=True)
    assert res.returncode == 0, "Node.js failed execution"
    print(f"PASS ({res.stdout.strip()})")


def test_ffmpeg_and_ffprobe():
    print(f"Testing FFmpeg binary ({FFMPEG_BIN})... ", end="")
    res = subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, text=True)
    assert res.returncode == 0, "FFmpeg failed execution"
    version = res.stdout.splitlines()[0]
    print(f"PASS ({version[:35]}...)")

    print(f"Testing FFprobe binary ({FFPROBE_BIN})... ", end="")
    res = subprocess.run([FFPROBE_BIN, "-version"], capture_output=True, text=True)
    assert res.returncode == 0, "FFprobe failed execution"
    print("PASS")


def test_hyperframes_cli():
    print("Testing HyperFrames CLI... ", end="")
    assert Path(HYPERFRAMES_BIN).is_file(), f"HyperFrames binary not found at {HYPERFRAMES_BIN}"
    res = subprocess.run([HYPERFRAMES_BIN, "--help"], capture_output=True, text=True)
    assert res.returncode == 0, "HyperFrames execution failed"
    print("PASS (HyperFrames ready)")


def test_encoder_hardware_and_software():
    print("Testing Intel VA-API hardware acceleration... ", end="")
    va_cmd = [
        FFMPEG_BIN, "-y",
        "-init_hw_device", "vaapi=va:/dev/dri/renderD128",
        "-filter_hw_device", "va",
        "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=30",
        "-vf", "format=nv12,hwupload",
        "-c:v", "h264_vaapi",
        "-f", "null", "-"
    ]
    va_res = subprocess.run(va_cmd, capture_output=True, text=True)
    if va_res.returncode == 0:
        print("PASS (Intel VA-API hardware acceleration available)")
    else:
        print("UNAVAILABLE / DRIVER ABSENT (Proceeding to software fallback)")

    print(f"Testing FFmpeg libx264 software encoder (CPU threads={CPU_THREADS})... ", end="")
    sw_cmd = [
        FFMPEG_BIN, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=0.5:size=320x240:rate=30",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-threads", str(CPU_THREADS),
        "-f", "null", "-"
    ]
    sw_res = subprocess.run(sw_cmd, capture_output=True, text=True)
    assert sw_res.returncode == 0, f"libx264 software encoder failed: {sw_res.stderr}"
    print("PASS (libx264 software encoding verified)")


if __name__ == "__main__":
    print("--- RUNNING ENVIRONMENT TESTS ---")
    test_python_environment()
    test_node_and_npm()
    test_ffmpeg_and_ffprobe()
    test_hyperframes_cli()
    test_encoder_hardware_and_software()
    print("--- ALL ENVIRONMENT TESTS PASSED ---")
