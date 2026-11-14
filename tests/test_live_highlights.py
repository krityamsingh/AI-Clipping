"""Regression coverage for measured livestream signals and editing style presets."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.clip_profiles import PROFILES, EDIT_STYLES, get_style
from src.stream_highlights import (parse_chat, chat_bursts, audio_events,
                                   rank_stream_highlights, sample_motion)
from src.agent_workflow import build_auto_plan, validate_plan
from src.render_plan import render_plan


class StreamSignalTests(unittest.TestCase):
    def test_timecoded_chat_and_peak_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "chat.txt"
            path.write_text(
                "[00:00:01] quiet\n"
                "[00:00:20] OMG clutch!\n"
                "[00:00:20] POG\n"
                "[00:00:21] no way!\n"
                "[00:00:21] insane\n"
                "[00:00:22] wow\n"
                "[00:00:22] lets go\n", encoding="utf-8")
            parsed = parse_chat(path)
            self.assertEqual(len(parsed), 7)
            chat = chat_bursts(parsed, 60, interval=5)
            self.assertTrue(chat)
            self.assertGreater(max(item["spike"] for item in chat), 0.5)
            ranked = rank_stream_highlights(60, motion=[], audio=[], chat=chat,
                                            target_duration=12, num_clips=1)
            self.assertEqual(len(ranked), 1)
            self.assertEqual(ranked[0]["evidence"]["trigger"], "chat")
            self.assertIn("score_type", ranked[0])

    def test_audio_onset_is_relative_and_silent_input_is_empty(self):
        self.assertEqual(audio_events({"timestamps": [0, 1], "rms_timeline": [-90, -90]}), [])
        events = audio_events({"timestamps": [0, 1, 2, 3, 4, 5],
                               "rms_timeline": [-40, -40, -40, -6, -40, -40]})
        self.assertTrue(any(e["timestamp"] == 3 for e in events))
        self.assertEqual(rank_stream_highlights(120, [], [], [],
                         target_duration=20), [])

    def test_motion_audio_ranks_action_and_no_overlaps(self):
        motion = [{"timestamp": i, "motion_spike": 0.9 if 70 <= i <= 73
                   or 180 <= i <= 183 else 0.0} for i in range(240)]
        audio = [{"timestamp": t, "energy": .9} for t in (71, 181)]
        result = rank_stream_highlights(240, motion, audio, target_duration=25,
                                        num_clips=3, context_before=9,
                                        profile="gaming")
        self.assertEqual(len(result), 2)
        self.assertLess(result[0]["end"], result[1]["start"])
        self.assertGreater(result[0]["evidence"]["motion_strength"], 0)
        self.assertGreater(result[0]["evidence"]["audio_strength"], 0)

    def test_profile_and_edit_style_validation(self):
        self.assertIn("sports", PROFILES)
        self.assertIn("cinematic", EDIT_STYLES)
        name, definition = get_style(None, "sports")
        self.assertEqual(name, "energetic")
        self.assertIn("font_size", definition)
        plan = {"version": 1, "source": "real.mp4", "profile": "sports",
                "settings": {"edit_style": "cinematic"}, "parts": [
                    {"part": 1, "shots": [{"source_start": 0, "source_end": 3}]}]}
        self.assertIs(validate_plan(plan, 5), plan)
        plan["settings"]["edit_style"] = "not-a-real-style"
        with self.assertRaises(ValueError):
            validate_plan(plan, 5)

    def test_plan_for_signal_only_disables_unverified_captions(self):
        report = {"source": "source.mp4", "metadata": {"duration": 1600},
                  "transcript": [], "candidate_highlights": [
                      {"start": 40, "end": 65, "score": 85, "title": "Motion spike",
                       "evidence": {"motion_strength": .9},
                       "selection_method": "stream_audio_motion_chat"},
                      {"start": 100, "end": 125, "score": 78, "title": "Chat spike",
                       "selection_method": "stream_audio_motion_chat"}]}
        plan = build_auto_plan(report, profile="livestream", max_parts=2,
                               edit_style="gaming")
        self.assertFalse(plan["settings"]["captions"])
        self.assertEqual(plan["settings"]["edit_style"], "gaming")
        self.assertEqual(plan["parts"][0]["edit_style"], "gaming")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg required")
class StreamFFmpegTests(unittest.TestCase):
    def test_motion_samples_actual_frames_and_style_renders(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "short.mp4"
            media = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=12:duration=5",
                 "-f", "lavfi", "-i", "sine=frequency=400:duration=5",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(source)],
                capture_output=True, text=True)
            self.assertEqual(media.returncode, 0, media.stderr)
            motion = sample_motion(source)
            self.assertGreaterEqual(len(motion), 5)
            self.assertTrue(all(0 <= item["motion"] <= 1 for item in motion))
            self.assertTrue(any(item["motion"] > .001 for item in motion))
            plan = {"version": 1, "source": str(source), "profile": "gaming",
                    "settings": {"aspect_ratio": "9:16", "quality": "preview",
                                 "edit_style": "energetic", "captions": True,
                                 "normalize_audio": False},
                    "caption_corrections": {},
                    "transcript": [{"start": .4, "end": 1.2, "text": "Amazing move!",
                                    "words": [{"start": .4, "end": .8, "word": "Amazing"},
                                              {"start": .8, "end": 1.2, "word": "move!"}]}],
                    "parts": [{"part": 1, "title": "Observed motion", "title_card": "PART 1",
                               "edit_style": "energetic",
                               "shots": [{"source_start": 0, "source_end": 2,
                                          "layout": "fit_pad"}]}]}
            output = render_plan(plan, Path(root) / "output")
            self.assertEqual(output["parts"][0]["edit_style"], "energetic")
            self.assertTrue(output["parts"][0]["full_decode_passed"])
            ass = Path(output["parts"][0]["ass"]).read_text(encoding="utf-8")
            self.assertIn(EDIT_STYLES["energetic"]["highlight_color"], ass)
            self.assertIn("Amazing", Path(output["parts"][0]["srt"]).read_text())


if __name__ == "__main__":
    unittest.main()
