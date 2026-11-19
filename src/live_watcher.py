"""Continuous segmented capture, bounded highlight processing, and local status.

Capture copies packets while a single worker analyzes closed segments. Three
adjacent segments give each owned peak its setup and payoff across boundaries.
Scores represent measured activity; all exports need editorial review.
"""
import copy
import csv
import http.server
import json
import math
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from config.settings import FFMPEG_BIN
from src.agent_workflow import build_auto_plan, write_json
from src.clip_profiles import PROFILES, EDIT_STYLES
from src.stream_highlights import (sample_motion, audio_events, chat_bursts,
                                   rank_stream_highlights)
from src.transcript_tools import review_transcript
from src.twitch_chat import TwitchChat, channel_name
from src.video_analyzer import VideoAnalyzer
from src.render_plan import render_plan


@dataclass
class WatchConfig:
    url: str
    capture_dir: str
    output_dir: str
    twitch_channel: str = ""
    chat_offset: float = 0
    chunk_seconds: float = 60
    duration: float = 45
    min_score: float = 35
    clips_per_window: int = 1
    model: str = "small"
    vocabulary: tuple = ()
    signals_only: bool = False
    profile: str = "livestream"
    style: str = "gaming"
    quality: str = "preview"
    aspect: str = "9:16"
    queue_size: int = 4
    max_disk_gb: float = 10
    max_runtime: float = 0
    retry_seconds: float = 10

    def validate(self):
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https", "rtmp", "rtmps"} or not parsed.netloc:
            raise ValueError("Supply a YouTube/Twitch live link or playable HTTP(S)/RTMP URL")
        for name, low, high in (("chunk_seconds", 10, 300), ("duration", 5, 120),
                               ("min_score", 0, 100), ("max_disk_gb", .1, 1000),
                               ("max_runtime", 0, 604800), ("retry_seconds", 1, 300),
                               ("chat_offset", -300, 300)):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be finite and in {low}..{high}")
        if self.duration > self.chunk_seconds:
            raise ValueError("duration must be <= chunk_seconds for boundary context")
        if self.model not in {"tiny", "base", "small", "medium"}:
            raise ValueError("Unsupported Whisper model")
        if self.profile not in PROFILES or self.style not in EDIT_STYLES:
            raise ValueError("Unsupported profile/style")
        if self.aspect not in {"9:16", "16:9", "1:1"} or self.quality not in {"preview", "final"}:
            raise ValueError("Unsupported aspect/quality")
        if not 1 <= self.queue_size <= 16 or not 1 <= self.clips_per_window <= 5:
            raise ValueError("queue_size must be 1..16; clips_per_window must be 1..5")
        capture, output = Path(self.capture_dir).resolve(), Path(self.output_dir).resolve()
        if capture.is_relative_to(output) or output.is_relative_to(capture):
            raise ValueError("Capture and output directories must be separate")
        self.twitch_channel = channel_name(self.twitch_channel)
        if not self.twitch_channel and parsed.hostname in {"twitch.tv", "www.twitch.tv"}:
            self.twitch_channel = channel_name(parsed.path.strip("/"))
        return self


def resolve_live_url(url):
    """Resolve platform pages on every reconnect so signed URLs can refresh."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    platform = any(host == domain or host.endswith("." + domain)
                   for domain in ("youtube.com", "youtu.be", "twitch.tv"))
    if not platform:
        return {"url": url, "headers": {}}
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--no-playlist", "--skip-download",
         "--dump-single-json", "--no-warnings", "--socket-timeout", "15",
         "--retries", "1", "-f",
         "best[height<=720]/bestvideo[height<=720]+bestaudio/best", url],
        capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("Stream resolution failed. Check that the channel is live and "
                           "yt-dlp is current. " + result.stderr[-500:])
    info = json.loads(result.stdout)
    if not info.get("is_live"):
        raise ValueError("The platform link is not currently live")
    formats = info.get("requested_formats") or []
    if formats:
        video = next((f for f in formats if f.get("vcodec") != "none"), None)
        audio = next((f for f in formats if f.get("vcodec") == "none"), None)
        if not video or not audio or any(
                f.get("protocol") not in {"m3u8", "m3u8_native"} or not f.get("url")
                for f in (video, audio)):
            raise ValueError("Separate live tracks must be playable HLS streams")
        return {"url": video["url"], "audio_url": audio["url"],
                "headers": video.get("http_headers") or info.get("http_headers") or {}}
    if not info.get("url"):
        raise ValueError("No playable live video/audio format")
    return {"url": info["url"], "headers": info.get("http_headers") or {}}


def capture_command(resolved, folder, chunk_seconds, *, manifest_url=None):
    command = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-rw_timeout", "15000000"]
    headers = resolved.get("headers") or {}
    # Headers are argv data, never shell strings; reject CR/LF injection.
    if headers:
        if any("\r" in str(v) or "\n" in str(v) for pair in headers.items() for v in pair):
            raise ValueError("Invalid stream HTTP headers")
        command += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    source = resolved["url"]
    if resolved.get("audio_url"):
        # One HLS input lets FFmpeg align renditions on their shared timestamps.
        # Rebuild on every reconnect because platform URLs expire.
        for url in (source, resolved["audio_url"]):
            if urlparse(url).scheme not in {"http", "https"} or any(
                    char in url for char in '\r\n"\\'):
                raise ValueError("Invalid separate HLS track URL")
        manifest = folder / "stream.m3u8"
        manifest.write_text(
            '#EXTM3U\n#EXT-X-VERSION:3\n'
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="original",'
            'DEFAULT=YES,AUTOSELECT=YES,URI="' + resolved["audio_url"] + '"\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=3000000,AUDIO="audio"\n' + source + '\n',
            encoding="utf-8")
        source = manifest_url or str(manifest)
        if manifest_url is None:
            command += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto"]
    return command + ["-i", source, "-map", "0:v:0", "-map", "0:a:0?",
                      "-c", "copy", "-f", "segment", "-segment_time", str(chunk_seconds),
                      "-segment_list", str(folder / "closed.csv"),
                      "-segment_list_type", "csv", "-segment_list_size", "8",
                      "-reset_timestamps", "1", str(folder / "segment_%06d.mkv")]


def closed_segments(folder):
    """Only CSV entries emitted by the muxer after a segment is finalized."""
    path = folder / "closed.csv"
    if not path.exists():
        return []
    rows = []
    try:
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines(keepends=True):
            if not line.endswith("\n"):
                continue
            row = next(csv.reader([line]))
            if len(row) == 3 and re.fullmatch(r"segment_\d{6}\.mkv", Path(row[0]).name):
                start, end = float(row[1]), float(row[2])
                if math.isfinite(start) and math.isfinite(end) and end > start:
                    rows.append({"path": folder / Path(row[0]).name,
                                 "start": start, "end": end})
    except (OSError, ValueError, csv.Error):
        pass  # Muxer may be rewriting its bounded list; retry on the next poll.
    return rows


class LiveWatcher:
    def __init__(self, config, *, stop_event=None, processing_lock=None):
        self.config = config.validate()
        self.stop_event = stop_event or threading.Event()
        self.processing_lock = processing_lock or threading.Semaphore(1)
        self.capture_dir = Path(config.capture_dir).resolve()
        self.output_dir = Path(config.output_dir).resolve()
        self.pending = queue.Queue(maxsize=config.queue_size)
        self.capture_done = threading.Event()
        self.chat = TwitchChat(config.twitch_channel, self.stop_event)
        self.lock = threading.RLock()
        self.state = {"status": "starting", "segments_captured": 0,
                      "windows_processed": 0, "segments_dropped": 0,
                      "spike_count": 0, "clips_rendered": 0, "reconnects": 0,
                      "errors": [], "clips": [], "recent_candidates": [],
                      "notice": "Activity candidates require review; scores do not predict virality.",
                      "caption_review_required": True}
        self.sequence = 0
        self.last_intervals = []
        self.analyzer = VideoAnalyzer(whisper_model_name=config.model)

    def _manifest_server(self):
        root = self.capture_dir

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if not re.fullmatch(r"/connection_\d{4,}/stream\.m3u8", self.path):
                    self.send_error(404)
                    return
                try:
                    content = (root / self.path.lstrip("/")).read_bytes()
                except OSError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, name="live-manifest", daemon=True)
        thread.start()
        return server, thread

    def snapshot(self):
        with self.lock:
            state = copy.deepcopy(self.state)
        state.update(queue_depth=self.pending.qsize(), chat=self.chat.snapshot(),
                     capture_dir=str(self.capture_dir), output_dir=str(self.output_dir))
        return state

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def increment(self, key, value=1):
        with self.lock:
            self.state[key] += value

    def error(self, exc):
        with self.lock:
            self.state["errors"] = (self.state["errors"] + [str(exc)[-800:]])[-10:]

    def stop(self):
        self.update(status="stopping")
        self.stop_event.set()

    def _disk_usage(self):
        roots = {self.capture_dir, self.output_dir}
        size = 0
        for root in roots:
            for path in root.rglob("*"):
                try:
                    if path.is_file():
                        size += path.stat().st_size
                except FileNotFoundError:
                    pass  # Worker is concurrently retiring a processed chunk.
        return size

    def _enqueue(self, item):
        self.increment("segments_captured")
        try:
            self.pending.put_nowait(item)
        except queue.Full:
            self.increment("segments_dropped")
            item["path"].unlink(missing_ok=True)

    def run(self):
        # Never reuse captures from another session.
        self.capture_dir.mkdir(parents=True, exist_ok=False)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if any(self.output_dir.iterdir()):
            raise ValueError("Use an empty output directory for a new watcher")
        manifest_server, manifest_thread = self._manifest_server()
        started = time.monotonic()
        self.chat.start()
        worker = threading.Thread(target=self._worker, name="live-highlight-worker", daemon=True)
        worker.start()
        attempt = 0
        failure = None
        try:
            while not self.stop_event.is_set():
                attempt += 1
                self.update(status="connecting")
                folder = self.capture_dir / f"connection_{attempt:04d}"
                folder.mkdir()
                process = None
                last_index = -1
                try:
                    resolved = resolve_live_url(self.config.url)
                    if self.stop_event.is_set():
                        break
                    origin = time.monotonic()
                    with (folder / "ffmpeg.log").open("w") as log:
                        manifest_url = (f"http://127.0.0.1:{manifest_server.server_port}/"
                                        f"{folder.name}/stream.m3u8")
                        process = subprocess.Popen(capture_command(
                            resolved, folder, self.config.chunk_seconds, manifest_url=manifest_url),
                                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                   stderr=log)
                        self.update(status="watching")
                        last_closed = origin
                        def collect():
                            nonlocal last_index, last_closed
                            for item in closed_segments(folder):
                                index = int(item["path"].stem.split("_")[-1])
                                if index <= last_index:
                                    continue
                                # The muxer retains eight CSV entries. If polling
                                # was delayed longer, retire untracked older files
                                # explicitly rather than leaking them on disk.
                                for missed in range(last_index + 1, index):
                                    old = folder / f"segment_{missed:06d}.mkv"
                                    if old.exists():
                                        old.unlink()
                                        self.increment("segments_captured")
                                        self.increment("segments_dropped")
                                last_index, last_closed = index, time.monotonic()
                                if item["path"].is_file():
                                    item.update(attempt=attempt, origin=origin, index=index)
                                    self._enqueue(item)
                        while process.poll() is None:
                            collect()
                            now = time.monotonic()
                            if self.config.max_runtime and now - started >= self.config.max_runtime:
                                self.stop()
                            if self._disk_usage() >= self.config.max_disk_gb * 1024**3:
                                raise RuntimeError("Session disk budget reached; increase --max-disk-gb or archive clips")
                            if not worker.is_alive():
                                failure = "Highlight worker exited unexpectedly"
                                raise RuntimeError(failure)
                            if now - last_closed > max(90, self.config.chunk_seconds * 3):
                                raise RuntimeError("No finalized video segments; reconnecting stalled stream")
                            write_json(self.output_dir / "status.json", self.snapshot())
                            if self.stop_event.wait(.5):
                                break
                        self._terminate(process)
                        collect()
                        if process.returncode and not self.stop_event.is_set():
                            self.error("FFmpeg connection ended: " + (folder / "ffmpeg.log").read_text()[-500:])
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    self.error(exc)
                    if failure or "disk budget" in str(exc):
                        failure = str(exc)
                        self.stop_event.set()
                finally:
                    if process is not None:
                        self._terminate(process)
                    # Remove unfinished files, never submit an active/truncated chunk.
                    for path in folder.glob("segment_*.mkv"):
                        if int(path.stem.split("_")[-1]) > last_index:
                            path.unlink(missing_ok=True)
                if not self.stop_event.is_set():
                    self.update(status="reconnecting")
                    self.increment("reconnects")
                    # Empty failed attempts must not accumulate logs/directories forever.
                    (folder / "ffmpeg.log").unlink(missing_ok=True)
                    (folder / "closed.csv").unlink(missing_ok=True)
                    (folder / "stream.m3u8").unlink(missing_ok=True)
                    if not any(folder.iterdir()):
                        folder.rmdir()
                    self.stop_event.wait(self.config.retry_seconds)
                if self.config.max_runtime and time.monotonic() - started >= self.config.max_runtime:
                    self.stop()
        finally:
            self.stop_event.set()
            manifest_server.shutdown()
            manifest_server.server_close()
            manifest_thread.join(timeout=2)
            self.capture_done.set()
            self.update(status="draining")
            # The current ASR/render and queued segments finish before a clean stop.
            while worker.is_alive():
                worker.join(timeout=.5)
                write_json(self.output_dir / "status.json", self.snapshot())
            if self.chat.thread:
                self.chat.thread.join(timeout=6)
            self.update(status="failed" if failure else "stopped", error=failure)
            write_json(self.output_dir / "status.json", self.snapshot())
        return self.snapshot()

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _worker(self):
        previous = None
        center = None
        try:
            while not self.capture_done.is_set() or not self.pending.empty():
                try:
                    following = self.pending.get(timeout=.5)
                except queue.Empty:
                    continue
                try:
                    if center and (following["attempt"] != center["attempt"] or
                                   following["index"] != center["index"] + 1):
                        self._process_safely(previous, center, None)
                        self._remove(previous)
                        self._remove(center)
                        previous, center = None, None
                    if center:
                        self._process_safely(previous, center, following)
                        self._remove(previous)
                        previous = center
                    center = following
                finally:
                    self.pending.task_done()
            if center:
                self._process_safely(previous, center, None)
        finally:
            self._remove(previous)
            self._remove(center)

    @staticmethod
    def _remove(item):
        if item:
            item["path"].unlink(missing_ok=True)

    def _process_safely(self, previous, center, following):
        try:
            with self.processing_lock:
                self._process_window([x for x in (previous, center, following) if x], center)
            self.increment("windows_processed")
        except Exception as exc:
            self.error(f"Segment {center['index']} processing failed: {exc}")

    def _process_window(self, items, owner):
        self.sequence += 1
        folder = self.capture_dir / f"window_{self.sequence:06d}"
        folder.mkdir()
        source = folder / "source.mkv"
        keep_source = False
        try:
            # Fixed generated names; FFmpeg concat syntax never includes user input.
            playlist = folder / "concat.txt"
            playlist.write_text("".join(f"file '../connection_{x['attempt']:04d}/{x['path'].name}'\n"
                                         for x in items), encoding="utf-8")
            result = subprocess.run([FFMPEG_BIN, "-y", "-v", "error", "-f", "concat",
                                     "-safe", "0", "-i", str(playlist), "-c", "copy", str(source)],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise RuntimeError("Cannot assemble stream window: " + result.stderr[-500:])
            metadata = self.analyzer.probe_video(source)
            # Probe actual durations; keyframe-aligned chunks differ from requested lengths.
            durations = [self.analyzer.probe_video(x["path"])["duration"] for x in items]
            owner_index = items.index(owner)
            owner_start = sum(durations[:owner_index])
            owner_end = owner_start + durations[owner_index]
            timeline_start = owner["start"] - owner_start
            wav = self.analyzer.extract_audio(source, folder / "audio.wav") if metadata["has_audio"] else None
            signals = self.analyzer.analyze_audio_signals(wav) if wav else {}
            motion = sample_motion(source)
            audio = audio_events(signals)
            events = self.chat.relative_events(owner["origin"], timeline_start,
                                               timeline_start + metadata["duration"],
                                               self.config.chat_offset)
            chat = chat_bursts(events, metadata["duration"])
            candidates = rank_stream_highlights(metadata["duration"], motion, audio, chat,
                profile=self.config.profile, target_duration=self.config.duration, num_clips=100,
                peak_bounds=(owner_start, min(owner_end, metadata["duration"])))
            candidates = [c for c in candidates if owner_start <= c["evidence"]["peak_time"] < owner_end
                          and c["score"] >= self.config.min_score]
            self.increment("spike_count", len(candidates))
            # Do not duplicate previously exported source intervals across overlapping windows.
            candidates = [c for c in candidates if all(
                owner["attempt"] != attempt or c["end"] + timeline_start <= start or
                c["start"] + timeline_start >= end for attempt, start, end in self.last_intervals)]
            candidates = sorted(candidates, key=lambda c: -c["score"])[:self.config.clips_per_window]
            candidates.sort(key=lambda c: c["start"])
            self.update(recent_candidates=candidates)
            if not candidates:
                return
            transcript = (self.analyzer.transcribe_audio(wav, initial_prompt=", ".join(self.config.vocabulary) or None)
                          if wav and not self.config.signals_only else [])
            # Expand to observed utterance boundaries where nearby; never trim away a peak.
            for candidate in candidates:
                for segment in transcript:
                    if segment["start"] < candidate["start"] < segment["end"] and candidate["start"] - segment["start"] <= 8:
                        candidate["start"] = max(0, segment["start"] - .1)
                    if segment["start"] < candidate["end"] < segment["end"] and segment["end"] - candidate["end"] <= 8:
                        candidate["end"] = min(metadata["duration"], segment["end"] + .15)
                candidate["duration"] = round(candidate["end"] - candidate["start"], 2)
            # Expanded speech boundaries may overlap; keep only distinct episodes.
            selected = []
            for c in candidates:
                if all(c["start"] >= v["end"] or c["end"] <= v["start"] for v in selected) and all(
                        owner["attempt"] != a or c["end"] + timeline_start <= s or
                        c["start"] + timeline_start >= e for a, s, e in self.last_intervals):
                    selected.append(c)
            if not selected:
                return
            report = {"version": 1, "source": str(source), "metadata": metadata,
                      "model": self.config.model, "profile": self.config.profile,
                      "transcript": transcript, "candidate_highlights": selected,
                      "caption_review_flags": review_transcript(transcript),
                      "activity_analysis": {"motion": motion, "audio_events": audio, "chat_bursts": chat},
                      "live_provenance": {"connection": owner["attempt"], "media_offset": timeline_start,
                                          "chat_alignment": "estimated_from_arrival_time",
                                          "chat_offset": self.config.chat_offset}}
            output = self.output_dir / f"window_{self.sequence:06d}"
            output.mkdir()
            keep_source = True  # Preserve evidence/EDL even if rendering fails.
            write_json(output / "analysis_report.json", report)
            plan = build_auto_plan(report, profile=self.config.profile, target_duration=self.config.duration,
                                   max_parts=len(selected), edit_style=self.config.style,
                                   quality=self.config.quality, aspect_ratio=self.config.aspect,
                                   captions=not self.config.signals_only)
            for part in plan["parts"]:
                for shot in part["shots"]:
                    shot["layout"] = "fit_pad"
            write_json(output / "edit_plan.json", plan)
            result = render_plan(plan, output)
            clips = []
            for part, candidate in zip(result["parts"], selected):
                self.last_intervals.append((owner["attempt"], candidate["start"] + timeline_start,
                                            candidate["end"] + timeline_start))
                clips.append({**part, "score": candidate["score"], "start": candidate["start"],
                              "end": candidate["end"], "aspect_ratio": self.config.aspect,
                              "explanation": candidate["explanation"], "review_required": True})
            # Only adjacent windows can overlap; retain a bounded deduplication history.
            self.last_intervals = self.last_intervals[-100:]
            self.increment("clips_rendered", len(clips))
            with self.lock:
                self.state["clips"] = (self.state["clips"] + clips)[-100:]
        finally:
            (folder / "audio.wav").unlink(missing_ok=True)
            (folder / "concat.txt").unlink(missing_ok=True)
            if not keep_source:
                source.unlink(missing_ok=True)
                folder.rmdir()
