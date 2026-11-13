"""Fast offline regression checks for edge cases and safety fixes."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from src.video_analyzer import VideoAnalyzer
from src.video_editor import VideoEditor
from web.app import allowed_source


class RegressionTests(unittest.TestCase):
    def test_reject_source_outside_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            outside = Path(root) / "external.mp4"
            outside.write_bytes(b"not a real video")
            with self.assertRaises(ValueError):
                allowed_source(str(outside))

    def test_streaming_audio_uses_bounded_windows(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "sample.wav"
            sf.write(path, np.zeros(16000, dtype=np.float32), 16000)
            result = VideoAnalyzer().analyze_audio_signals(path)
            self.assertEqual(len(result["rms_timeline"]), 4)
            self.assertEqual(len(result["timestamps"]), 4)
            self.assertAlmostEqual(result["duration"], 1.0)

    def test_highlight_ranking_rejects_bad_duration(self):
        analyzer = VideoAnalyzer()
        with self.assertRaises(ValueError):
            analyzer.rank_candidate_highlights(
                target_duration=0, num_clips=2, video_metadata={"duration": 60},
                segments=[], audio_signals={}, scene_cuts=[])

    def test_silent_highlights_are_possible(self):
        analyzer = VideoAnalyzer()
        result = analyzer.rank_candidate_highlights(
            target_duration=12, num_clips=1, video_metadata={"duration": 10},
            segments=[], audio_signals={}, scene_cuts=[])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["end"], 10)

    def test_bad_render_bounds_fail_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as root:
            video = Path(root) / "sample.mp4"
            video.write_bytes(b"stub")
            with self.assertRaises(ValueError):
                VideoEditor().render_clip(video, 12, 3, Path(root) / "out.mp4")


if __name__ == "__main__":
    unittest.main()
