"""
PySceneDetect Scene Detection Test
Generates a test video with known cuts and verifies scene detection.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import TESTS_DIR, FFMPEG_BIN
from src.video_analyzer import VideoAnalyzer


def create_synthetic_multiscene_video(output_video: Path) -> Path:
    """Generate 9-second video with cuts at 3s and 6s."""
    output_video = Path(output_video)
    cmd = [
        FFMPEG_BIN, "-y",
        "-f", "lavfi", "-i", "color=c=red:s=640x360:d=3",
        "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=3",
        "-f", "lavfi", "-i", "color=c=green:s=640x360:d=3",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[outv]",
        "-map", "[outv]",
        "-c:v", "libx264", "-preset", "ultrafast",
        str(output_video)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_video


def test_scene_detection():
    print("Testing PySceneDetect scene change detection... ", end="")
    test_video = TESTS_DIR / "sample_scenes.mp4"
    create_synthetic_multiscene_video(test_video)

    analyzer = VideoAnalyzer()
    cuts = analyzer.detect_scenes(test_video)

    assert len(cuts) >= 2, f"Expected at least 2 scene cuts, detected: {cuts}"
    print(f"PASS (Detected cuts at: {cuts})")


if __name__ == "__main__":
    print("--- RUNNING SCENEDETECT TESTS ---")
    test_scene_detection()
    print("--- SCENEDETECT TESTS PASSED ---")
