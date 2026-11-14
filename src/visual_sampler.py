"""Generate bounded, timestamp-grounded source frames for visual editing agents.

This does not claim to classify scenes or objects. Agents with visual inputs
may inspect the real extracted JPEGs alongside the transcript before editing.
"""
import bisect
import json
import math
import subprocess
from pathlib import Path

from config.settings import FFMPEG_BIN
from src.agent_workflow import write_json


def sample_frames(report, output_dir, max_frames=24, width=480):
    duration = float(report["metadata"]["duration"])
    source = Path(report["source"]).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid video duration")
    if not isinstance(max_frames, int) or not 1 <= max_frames <= 64:
        raise ValueError("Frame limit must be 1..64")
    if not isinstance(width, int) or not 160 <= width <= 1280:
        raise ValueError("Frame width must be 160..1280")
    cuts = sorted(float(c) for c in report.get("scene_cuts") or []
                  if isinstance(c, (int, float)) and math.isfinite(float(c))
                  and 0 <= c < duration)
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    count = min(max_frames, max(1, int(math.ceil(duration / 3.0))))
    window = duration / count
    selected = []
    for index in range(count):
        target = (index + .5) * window
        pos = bisect.bisect_left(cuts, target)
        neighbors = cuts[max(0, pos - 1):pos + 1]
        near = min(neighbors, key=lambda c: abs(c - target)) if neighbors else None
        # Prefer a frame shortly after a meaningful cut when it is nearby.
        timestamp = min(duration - .05, near + .4) if near is not None and abs(near - target) < window * .35 else target
        timestamp = round(max(0.0, min(timestamp, max(0, duration - .05))), 3)
        filename = "frame_%03d.jpg" % (index + 1)
        destination = folder / filename
        result = subprocess.run(
            [FFMPEG_BIN, "-y", "-v", "error", "-ss", str(timestamp),
             "-i", str(source), "-frames:v", "1",
             "-vf", "scale=%d:-2" % width, "-q:v", "4", str(destination)],
            capture_output=True, text=True, timeout=120)
        if result.returncode or not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError("Failed to extract frame at %.3fs: %s" %
                               (timestamp, result.stderr[-400:]))
        selected.append({"source_time": timestamp,
                         "image": str(destination.resolve())})
    manifest = {
        "version": 1, "source": str(source), "frames": selected,
        "purpose": "Actual source frame evidence for agent visual review",
        "notice": "No object detection or scene classification was performed"
    }
    write_json(folder / "frames.json", manifest)
    return manifest
