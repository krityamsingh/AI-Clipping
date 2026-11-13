"""Offline tests for content-aware selection and edit safety."""
import tempfile
import unittest
from pathlib import Path

from src.editing_director import EditingDirector
from src.caption_generator import CaptionGenerator
from src.video_analyzer import VideoAnalyzer


class DirectorTests(unittest.TestCase):
    def setUp(self):
        self.segments = [
            {"start": 0.0, "end": 5.0, "text": "And this is because the thing is"},
            {"start": 5.0, "end": 10.0, "text": "we should wait for more details"},
            {"start": 12.0, "end": 17.0, "text": "Did the new game reveal realistic traffic?"},
            {"start": 17.0, "end": 22.0, "text": "The trailer shows traffic moving naturally."},
            {"start": 22.0, "end": 27.0, "text": "The vehicles slow down at intersections."},
            {"start": 30.0, "end": 35.0, "text": "But this one is because"},
        ]

    def test_prefers_coherent_question_answer_with_sentence_end(self):
        ranked = EditingDirector().rank(
            target_duration=15, num_clips=1, video_metadata={"duration": 40},
            segments=self.segments, audio_signals={}, scene_cuts=[])
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["start"], 12)
        self.assertEqual(ranked[0]["end"], 27)
        self.assertTrue(ranked[0]["evidence"]["ends_with_sentence_punctuation"])

    def test_no_invented_story_when_no_transcript(self):
        self.assertEqual(EditingDirector().rank(
            target_duration=12, num_clips=1, video_metadata={"duration": 30},
            segments=[], audio_signals={}, scene_cuts=[]), [])

    def test_integrated_selection_evidence(self):
        result = VideoAnalyzer().rank_candidate_highlights(
            target_duration=15, num_clips=1, video_metadata={"duration": 40},
            segments=self.segments, audio_signals={}, scene_cuts=[])
        self.assertEqual(result[0]["selection_method"], "transcript_story_boundaries")
        self.assertIn("evidence", result[0])

    def test_no_negative_duration_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "test.srt"
            CaptionGenerator().generate_srt([
                {"start": 0, "end": 1, "text": "Before"},
                {"start": 5, "end": 6, "text": "After"},
            ], file, clip_start=2, clip_end=4)
            self.assertEqual(file.read_text(), "")


if __name__ == "__main__":
    unittest.main()
