"""Offline and FFmpeg integration tests for the agent editing workflow."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.agent_workflow import build_auto_plan, validate_plan
from src.transcript_tools import correct_transcript, retime_shots, caption_cues, review_transcript
from src.render_plan import render_plan


class AgentPlanTests(unittest.TestCase):
    def test_two_chronological_parts_with_measured_highlights(self):
        report = {
            "source": "/tmp/example.mp4",
            "metadata": {"duration": 800},
            "transcript": [],
            "candidate_highlights": [
                {"start": 520, "end": 560, "score": 90, "title": "Later", "explanation": "Topic 2"},
                {"start": 20, "end": 60, "score": 80, "title": "Earlier", "explanation": "Topic 1"},
                {"start": 22, "end": 59, "score": 79, "title": "Overlap", "explanation": "Duplicate"},
            ]
        }
        plan = build_auto_plan(report, profile="podcast", max_parts=2)
        self.assertEqual([p["part"] for p in plan["parts"]], [1, 2])
        self.assertEqual([p["shots"][0]["source_start"] for p in plan["parts"]], [20, 520])
        self.assertEqual([p["title_card"] for p in plan["parts"]], ["PART 1", "PART 2"])

    def test_rejects_unbounded_or_invalid_edl(self):
        plan = {"version": 1, "source": "/tmp/file.mp4", "parts": [
            {"part": 1, "shots": [{"source_start": 4, "source_end": 10}]}]}
        self.assertIs(validate_plan(plan, 12), plan)
        with self.assertRaises(ValueError):
            validate_plan(plan, 9)
        plan["parts"][0]["shots"][0]["source_end"] = 4
        with self.assertRaises(ValueError):
            validate_plan(plan, 12)

    def test_corrections_preserve_timing_and_punctuation(self):
        source = [{"start": 0, "end": 1.5, "text": "g t a.", "words": [
            {"word": "g", "start": .1, "end": .4, "probability": .8},
            {"word": "t", "start": .4, "end": .9, "probability": .9},
            {"word": "a.", "start": .9, "end": 1.4, "probability": .8}]}]
        corrected = correct_transcript(source, {"g t a": "GTA"})
        self.assertEqual(corrected[0]["words"][0]["word"], "GTA.")
        self.assertEqual(corrected[0]["text"], "GTA.")
        self.assertAlmostEqual(corrected[0]["words"][0]["start"], .1)
        self.assertAlmostEqual(corrected[0]["words"][0]["end"], 1.4)
        self.assertTrue(review_transcript(corrected))
        self.assertEqual(source[0]["words"][0]["word"], "g")

    def test_retime_across_discontinuous_shots(self):
        words = [
            {"word": "First", "start": 1.2, "end": 1.6},
            {"word": "part.", "start": 1.7, "end": 2.1},
            {"word": "Second", "start": 7.1, "end": 7.4},
            {"word": "part.", "start": 7.5, "end": 7.9}
        ]
        segments = [
            {"start": 1.2, "end": 2.1, "text": "First part.", "words": words[:2]},
            {"start": 7.1, "end": 7.9, "text": "Second part.", "words": words[2:]}
        ]
        shots = [{"source_start": 1, "source_end": 3}, {"source_start": 7, "source_end": 9}]
        output = retime_shots(shots, segments, [2, 2])
        self.assertEqual(len(output), 2)
        self.assertAlmostEqual(output[0]["start"], .2)
        self.assertAlmostEqual(output[1]["start"], 2.1)
        self.assertEqual([cue["text"] for cue in caption_cues(output)], ["First part.", "Second part."])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class FFmpegAgentRenderTests(unittest.TestCase):
    def test_real_multipart_render_with_audio_captions_and_decode(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "source.mp4"
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=12:d=5",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            transcript = [
                {"start": .3, "end": 1.2, "text": "hello world.", "words": [
                    {"word": "hello", "start": .3, "end": .6},
                    {"word": "world.", "start": .7, "end": 1.2}]},
                {"start": 3, "end": 4, "text": "second part.", "words": [
                    {"word": "second", "start": 3, "end": 3.4},
                    {"word": "part.", "start": 3.5, "end": 4.0}]}
            ]
            plan = {
                "version": 1, "source": str(source), "profile": "podcast",
                "settings": {"quality": "preview", "aspect_ratio": "9:16",
                             "captions": True, "word_highlight": True},
                "caption_corrections": {"hello": "Hello"},
                "transcript": transcript,
                "parts": [
                    {"part": 1, "title": "Episode one", "title_card": "PART 1",
                     "shots": [
                        {"source_start": 0, "source_end": 1.5, "layout": "fit_pad"},
                        {"source_start": 2.8, "source_end": 4.3, "layout": "fit_pad"}]},
                    {"part": 2, "title": "Episode two", "title_card": "PART 2",
                     "shots": [
                        {"source_start": 2.8, "source_end": 4.3, "layout": "fit_pad"}]}
                ]}
            result = render_plan(plan, root / "export")
            self.assertEqual(len(result["parts"]), 2)
            for part in result["parts"]:
                self.assertTrue(part["full_decode_passed"])
                self.assertEqual(part["video_codec"], "h264")
                self.assertEqual(part["resolution"], [720, 1280])
                self.assertTrue(Path(part["output"]).is_file())
                self.assertTrue(Path(part["srt"]).is_file())
            subtitle = Path(result["parts"][0]["srt"]).read_text()
            self.assertIn("Hello world.", subtitle)
            self.assertIn("second part.", subtitle)


if __name__ == "__main__":
    unittest.main()
