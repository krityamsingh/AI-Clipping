"""Continuous watcher lifecycle, chat isolation, and real HTTP/FFmpeg coverage."""
import functools
import http.server
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.live_watcher import (LiveWatcher, WatchConfig, capture_command,
                              closed_segments, resolve_live_url)
from src.stream_highlights import rank_stream_highlights, chat_bursts
from src.twitch_chat import TwitchChat


class WatcherTests(unittest.TestCase):
    def config(self, root, **kwargs):
        return WatchConfig(url="https://example.com/live.m3u8",
                           capture_dir=str(Path(root) / "capture"),
                           output_dir=str(Path(root) / "output"), **kwargs)

    def test_config_rejects_unbounded_or_destructive_settings(self):
        with tempfile.TemporaryDirectory() as root:
            for kwargs in ({"duration": 90}, {"chunk_seconds": float("nan")},
                           {"max_disk_gb": 0}, {"queue_size": 0},
                           {"twitch_channel": "foo\r\nPRIVMSG #x :bad"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    self.config(root, **kwargs).validate()
            config = self.config(root)
            config.url = "https://www.twitch.tv/example"
            self.assertEqual(config.validate().twitch_channel, "example")

    def test_resolver_rejects_vods_and_preserves_signed_headers(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({
            "is_live": True, "url": "https://cdn.example/live.m3u8?token=test",
            "http_headers": {"Referer": "https://youtube.com"}}), "")
        with patch("src.live_watcher.subprocess.run", return_value=result) as run:
            info = resolve_live_url("https://youtube.com/watch?v=abc")
            self.assertIn("token=test", info["url"])
            self.assertEqual(info["headers"]["Referer"], "https://youtube.com")
            self.assertIn("--no-playlist", run.call_args.args[0])
            result.stdout = json.dumps({"is_live": False, "url": "https://cdn.example/file"})
            with self.assertRaisesRegex(ValueError, "not currently live"):
                resolve_live_url("https://twitch.tv/example")
        with self.assertRaisesRegex(ValueError, "headers"):
            capture_command({"url": "https://a", "headers": {"X": "\r\nbad"}}, Path("/tmp"), 60)

    def test_finalized_csv_only_and_partial_lines_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            (folder / "closed.csv").write_text('segment_000000.mkv,0,10.5\nsegment_000001.mkv,10.5,20')
            rows = closed_segments(folder)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["end"], 10.5)

    def test_separate_hls_tracks_share_one_input_and_refresh_manifest(self):
        info = {"is_live": True, "requested_formats": [
            {"vcodec": "h264", "protocol": "m3u8_native", "url": "https://cdn.example/video.m3u8"},
            {"vcodec": "none", "protocol": "m3u8_native", "url": "https://cdn.example/audio.m3u8"}]}
        result = subprocess.CompletedProcess([], 0, json.dumps(info), "")
        with tempfile.TemporaryDirectory() as root, patch(
                "src.live_watcher.subprocess.run", return_value=result):
            resolved = resolve_live_url("https://youtube.com/live/example")
            command = capture_command(resolved, Path(root), 60)
            self.assertEqual(command.count("-i"), 1)
            manifest = Path(root) / "stream.m3u8"
            self.assertIn(resolved["audio_url"], manifest.read_text())
            self.assertIn(resolved["url"], manifest.read_text())
            resolved["audio_url"] = "https://cdn.example/fresh-audio.m3u8"
            capture_command(resolved, Path(root), 60)
            self.assertIn("fresh-audio", manifest.read_text())
            resolved["audio_url"] = 'https://cdn.example/audio.m3u8"\n#bad'
            with self.assertRaisesRegex(ValueError, "HLS track URL"):
                capture_command(resolved, Path(root), 60)

    def test_queue_overload_deletes_only_unqueued_segment(self):
        with tempfile.TemporaryDirectory() as root:
            watcher = LiveWatcher(self.config(root, queue_size=1))
            a, b = Path(root) / "a.mkv", Path(root) / "b.mkv"
            a.touch()
            b.touch()
            watcher._enqueue({"path": a})
            watcher._enqueue({"path": b})
            self.assertTrue(a.exists())
            self.assertFalse(b.exists())
            self.assertEqual(watcher.snapshot()["segments_dropped"], 1)

    def test_rolling_context_and_gap_never_join_unrelated_capture(self):
        with tempfile.TemporaryDirectory() as root:
            watcher = LiveWatcher(self.config(root))
            items = []
            for attempt, index in ((1, 0), (1, 1), (1, 2), (2, 0)):
                path = Path(root) / f"{attempt}_{index}.mkv"
                path.touch()
                item = {"path": path, "attempt": attempt, "index": index}
                items.append(item)
                watcher.pending.put(item)
            watcher.capture_done.set()
            calls = []
            with patch.object(watcher, "_process_window", side_effect=lambda group, owner:
                              calls.append(([x["path"].name for x in group], owner["path"].name))):
                watcher._worker()
            self.assertEqual(calls, [(["1_0.mkv", "1_1.mkv"], "1_0.mkv"),
                                     (["1_0.mkv", "1_1.mkv", "1_2.mkv"], "1_1.mkv"),
                                     (["1_1.mkv", "1_2.mkv"], "1_2.mkv"),
                                     (["2_0.mkv"], "2_0.mkv")])
            self.assertTrue(all(not item["path"].exists() for item in items))

    def test_peak_ownership_retains_context_and_excludes_neighbor_seeds(self):
        audio = [{"timestamp": 9, "energy": .9}, {"timestamp": 12, "energy": .8}]
        ranked = rank_stream_highlights(30, [], audio, target_duration=10,
                                        peak_bounds=(10, 20), num_clips=1)
        self.assertEqual(ranked[0]["evidence"]["peak_time"], 12)
        self.assertLess(ranked[0]["start"], 10)

    def test_sparse_chat_spike_survives_long_quiet_window(self):
        events = [{"timestamp": 100, "hype": False} for _ in range(20)]
        bursts = chat_bursts(events, 180)
        self.assertGreater(bursts[0]["spike"], .8)
        self.assertTrue(rank_stream_highlights(180, [], [], bursts))

    def test_chat_counts_privmsg_only_and_offsets_without_storing_raw_text(self):
        chat = TwitchChat("example", threading.Event(), capacity=2)
        self.assertFalse(chat.ingest(":server PING :tmi.twitch.tv", now=100))
        self.assertFalse(chat.ingest(":user!u@u PRIVMSG #other :wow", now=100))
        for t in (101, 102, 103):
            self.assertTrue(chat.ingest(":user!u@u PRIVMSG #example :POG private-text", now=t))
        rows = chat.relative_events(100, 0, 10, offset=-1)
        self.assertEqual([x["timestamp"] for x in rows], [1, 2])
        self.assertNotIn("private-text", repr(chat.events))
        self.assertEqual(chat.snapshot()["buffer_evictions"], 1)

    def test_api_rejects_bad_settings_and_has_live_controls(self):
        from fastapi.testclient import TestClient
        from web.app import app
        client = TestClient(app)
        self.assertEqual(client.post("/api/live/start", json={"url": "file:///tmp/a"}).status_code, 400)
        self.assertEqual(client.post("/api/live/start", json={
            "url": "https://example.com/live", "duration": 90, "chunk_seconds": 60}).status_code, 400)
        self.assertEqual(client.get("/api/live/missing").status_code, 404)
        self.assertEqual(client.post("/api/live/missing/stop").status_code, 404)
        self.assertIn("Continuous live stream clipper", client.get("/").text)
        self.assertEqual(client.get("/api/live/not-a-session/media/file.mp4").status_code, 404)

    def test_api_start_conflict_status_and_stop(self):
        from fastapi.testclient import TestClient
        from web.app import app, live_sessions, live_sessions_lock

        def run_until_stopped(watcher):
            watcher.update(status="watching")
            watcher.stop_event.wait(5)
            watcher.update(status="stopped")

        with patch.object(LiveWatcher, "run", run_until_stopped), TestClient(app) as client:
            response = client.post("/api/live/start", json={"url": "https://example.com/live"})
            self.assertEqual(response.status_code, 200, response.text)
            session_id = response.json()["session_id"]
            try:
                self.assertEqual(client.post("/api/live/start", json={
                    "url": "https://example.com/live"}).status_code, 409)
                self.assertEqual(client.get(f"/api/live/{session_id}").json()["status"], "watching")
                self.assertEqual(client.post(f"/api/live/{session_id}/stop").status_code, 200)
                live_sessions[session_id]["thread"].join(timeout=2)
                self.assertEqual(client.get(f"/api/live/{session_id}").json()["status"], "stopped")
            finally:
                with live_sessions_lock:
                    live_sessions.pop(session_id)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class WatcherFFmpegTests(unittest.TestCase):
    def test_separate_hls_video_audio_with_http_headers(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            generated = subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=10:duration=4", "-f", "lavfi", "-i",
                "sine=frequency=440:duration=4", "-map", "0:v:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-g", "10", "-f", "hls", "-hls_time", "1",
                "-hls_list_size", "0", str(root / "video.m3u8"), "-map", "1:a:0",
                "-c:a", "aac", "-f", "hls", "-hls_time", "1", "-hls_list_size", "0",
                str(root / "audio.m3u8")], capture_output=True, text=True, timeout=30)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                functools.partial(QuietHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            watcher = LiveWatcher(WatchConfig(
                url="https://example.com/live", capture_dir=str(root / "capture"),
                output_dir=str(root / "output")))
            folder = watcher.capture_dir / "connection_0001"
            folder.mkdir(parents=True)
            manifest_server, manifest_thread = watcher._manifest_server()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                command = capture_command({"url": base + "/video.m3u8",
                    "audio_url": base + "/audio.m3u8", "headers": {"Referer": base}},
                    folder, 60, manifest_url=f"http://127.0.0.1:{manifest_server.server_port}/connection_0001/stream.m3u8")
                result = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = closed_segments(folder)
                self.assertEqual(len(rows), 1)
                meta = watcher.analyzer.probe_video(rows[0]["path"])
                self.assertTrue(meta["has_audio"])
                self.assertGreater(meta["duration"], 3)
            finally:
                manifest_server.shutdown()
                manifest_server.server_close()
                manifest_thread.join(timeout=2)
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_http_capture_processing_export_and_graceful_stop(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / "fixture.ts"
            result = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "testsrc2=size=320x180:rate=10:duration=25", "-an",
                "-c:v", "libx264", "-preset", "ultrafast", "-g", "20", "-f", "mpegts", str(source)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                functools.partial(QuietHandler, directory=str(root)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                watcher = LiveWatcher(WatchConfig(
                    url=f"http://127.0.0.1:{server.server_port}/fixture.ts",
                    capture_dir=str(root / "capture"), output_dir=str(root / "output"),
                    chunk_seconds=10, duration=5, min_score=0, max_runtime=.7,
                    retry_seconds=1, signals_only=True, aspect="16:9"))
                status = watcher.run()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            self.assertEqual(status["status"], "stopped", status)
            self.assertGreaterEqual(status["segments_captured"], 2, status)
            self.assertGreaterEqual(status["clips_rendered"], 1, status)
            self.assertEqual(status["errors"], [], status)
            self.assertEqual(status["queue_depth"], 0)
            self.assertFalse(list((root / "capture").rglob("segment_*.mkv")))
            for clip in status["clips"]:
                self.assertTrue(clip["full_decode_passed"])
                plan = json.loads((Path(clip["output"]).parent / "edit_plan.json").read_text())
                self.assertFalse(plan["settings"]["captions"])
                self.assertEqual(plan["parts"][0]["shots"][0]["layout"], "fit_pad")
                self.assertTrue(Path(plan["source"]).exists())
            saved = json.loads((root / "output" / "status.json").read_text())
            self.assertEqual(saved["clips_rendered"], status["clips_rendered"])


if __name__ == "__main__":
    unittest.main()
