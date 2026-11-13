"""
Automated Video Analysis & Highlight Detection Engine
Combines speech transcription, audio peaks, and scene transitions to rank candidate highlights.
Optimized for CPU inference with Faster-Whisper INT8.
"""

import bisect
import json
import logging
import math
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

from config.settings import (
    FFMPEG_BIN,
    FFPROBE_BIN,
    WHISPER_MODEL_NAME,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DOWNLOAD_ROOT,
    CPU_THREADS,
    AUDIO_DIR,
    SCENE_DETECTOR_THRESHOLD,
    SILENCE_THRESHOLD_DB,
    PEAK_PERCENTILE
)

logger = logging.getLogger("AI-Clipping.Analyzer")
logging.basicConfig(level=logging.INFO)


class VideoAnalyzer:
    """
    Analyzes video files for speech, audio energy, and visual scene changes.
    """

    def __init__(self, whisper_model_name: str = WHISPER_MODEL_NAME):
        self.whisper_model_name = whisper_model_name
        self._whisper_model = None

    def get_whisper_model(self):
        """Lazy load Faster-Whisper model to conserve memory."""
        if self._whisper_model is None:
            try:
                from faster_whisper import WhisperModel
                logger.info(
                    f"Loading Faster-Whisper ({self.whisper_model_name}, "
                    f"device={WHISPER_DEVICE}, compute_type={WHISPER_COMPUTE_TYPE}, threads={CPU_THREADS})"
                )
                self._whisper_model = WhisperModel(
                    self.whisper_model_name,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                    cpu_threads=CPU_THREADS,
                    download_root=WHISPER_DOWNLOAD_ROOT
                )
            except Exception as e:
                logger.error(f"Failed to load Faster-Whisper: {e}")
                raise
        return self._whisper_model

    def probe_video(self, video_path: Path) -> Dict[str, Any]:
        """
        Extract stream and container metadata using ffprobe.
        """
        video_path = Path(video_path)
        if not video_path.is_file():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cmd = [
            FFPROBE_BIN,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"FFprobe failed on {video_path}: {res.stderr}")

        data = json.loads(res.stdout)
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
        if video_stream is None:
            raise ValueError(f"Input does not contain a video stream: {video_path}")

        duration = float(data.get("format", {}).get("duration", 0.0))
        if duration <= 0.0 and video_stream:
            duration = float(video_stream.get("duration", 0.0))

        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"Input video has invalid duration: {video_path}")

        fps = 30.0
        if video_stream and "r_frame_rate" in video_stream:
            try:
                num, den = video_stream["r_frame_rate"].split("/")
                fps = float(num) / float(den) if float(den) > 0 else 30.0
            except Exception:
                fps = 30.0

        return {
            "path": str(video_path),
            "filename": video_path.name,
            "duration": duration,
            "width": int(video_stream.get("width", 1920)) if video_stream else 1920,
            "height": int(video_stream.get("height", 1080)) if video_stream else 1080,
            "fps": round(fps, 2),
            "video_codec": video_stream.get("codec_name", "unknown") if video_stream else None,
            "audio_codec": audio_stream.get("codec_name", None) if audio_stream else None,
            "has_audio": audio_stream is not None,
            "bitrate": int(data.get("format", {}).get("bit_rate", 0))
        }

    def extract_audio(self, video_path: Path, output_wav: Optional[Path] = None) -> Path:
        """
        Extract audio track as 16kHz mono 16-bit WAV for whisper and signal analysis.
        """
        video_path = Path(video_path)
        if output_wav is None:
            output_wav = AUDIO_DIR / f"{video_path.stem}_audio16k.wav"
        output_wav = Path(output_wav)
        output_wav.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            FFMPEG_BIN, "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(output_wav)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Audio extraction failed: {res.stderr}")

        return output_wav

    def detect_scenes(self, video_path: Path, threshold: float = SCENE_DETECTOR_THRESHOLD) -> List[float]:
        """
        Detect visual shot changes using PySceneDetect (with PyAV software backend) or FFmpeg fallback.
        Returns a sorted list of scene cut timestamps in seconds.
        """
        scene_cuts = []
        video_path = Path(video_path)

        # 1. Try PySceneDetect with PyAV backend first (avoids OpenCV hardware acceleration errors on AV1)
        try:
            from scenedetect import open_video, SceneManager, ContentDetector
            video = None
            try:
                # Prefer PyAV backend for robust software decoding via libdav1d / ffmpeg
                video = open_video(str(video_path), backend="pyav")
            except Exception as be_err:
                logger.debug(f"PyAV backend not available ({be_err}), trying opencv backend...")
                try:
                    video = open_video(str(video_path), backend="opencv")
                except Exception:
                    video = open_video(str(video_path))

            if video is not None:
                scene_manager = SceneManager()
                scene_manager.add_detector(ContentDetector(threshold=threshold))
                scene_manager.detect_scenes(video, frame_skip=1)
                scene_list = scene_manager.get_scene_list()

                for scene in scene_list:
                    start_sec = scene[0].get_seconds()
                    if start_sec > 0.05:
                        scene_cuts.append(round(start_sec, 2))
        except Exception as e:
            logger.warning(f"PySceneDetect encountered error: {e}")

        # 2. If no cuts detected on videos longer than 5 seconds, invoke fast FFmpeg scene analysis fallback
        if not scene_cuts:
            try:
                meta = self.probe_video(video_path)
                if meta.get("duration", 0) > 5.0:
                    logger.info("Visual cuts detected: 0 via PySceneDetect. Invoking high-speed FFmpeg scene fallback...")
                    scene_cuts = self._detect_scenes_ffmpeg(video_path)
            except Exception as e:
                logger.warning(f"FFmpeg scene fallback failed: {e}")

        return sorted(list(set(scene_cuts)))

    def _detect_scenes_ffmpeg(self, video_path: Path) -> List[float]:
        """High-speed fallback scene cut detection using FFmpeg select filter with 320p downscaling."""
        cuts = []
        try:
            cmd = [
                FFMPEG_BIN,
                "-threads", str(CPU_THREADS),
                "-i", str(video_path),
                "-an",
                "-vf", "scale=320:-1,select='gt(scene,0.3)',metadata=print:file=-",
                "-f", "null", "-"
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=300)
            for line in res.stdout.splitlines():
                if "pts_time:" in line:
                    try:
                        pts = float(line.split("pts_time:")[1].strip())
                        if pts > 0.05:
                            cuts.append(round(pts, 2))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"FFmpeg scene fallback failed: {e}")
        return cuts

    def analyze_audio_signals(self, wav_path: Path) -> Dict[str, Any]:
        """Stream RMS in short windows instead of loading entire recordings into RAM."""
        import soundfile as sf

        values = []
        timestamps = []
        with sf.SoundFile(str(wav_path)) as stream:
            sample_rate = stream.samplerate
            window_size = max(1, round(0.25 * sample_rate))
            offset = 0
            while True:
                chunk = stream.read(frames=window_size, dtype="float32", always_2d=True)
                if len(chunk) < window_size:
                    break
                mono = chunk.mean(axis=1)
                rms = math.sqrt(float(np.mean(mono * mono, dtype=np.float64)) + 1e-12)
                values.append(20.0 * math.log10(rms + 1e-9))
                timestamps.append(round(offset / sample_rate, 2))
                offset += window_size
            duration = float(stream.frames / sample_rate) if sample_rate else 0.0

        if not values:
            return {"duration": duration, "rms_timeline": [], "timestamps": [],
                    "peak_timestamps": [], "silence_timestamps": [],
                    "mean_db": -100.0, "max_db": -100.0, "peak_threshold": -100.0}
        rms_db = np.asarray(values, dtype=np.float32)
        threshold = float(np.percentile(rms_db, PEAK_PERCENTILE))
        return {
            "duration": duration,
            "rms_timeline": [round(float(v), 2) for v in rms_db],
            "timestamps": timestamps,
            "peak_timestamps": [timestamps[i] for i in np.where(rms_db >= threshold)[0]],
            "silence_timestamps": [timestamps[i] for i in np.where(rms_db < SILENCE_THRESHOLD_DB)[0]],
            "mean_db": float(np.mean(rms_db)),
            "max_db": float(np.max(rms_db)),
            "peak_threshold": threshold
        }

    def transcribe_audio(self, wav_path: Path) -> List[Dict[str, Any]]:
        """
        Run Faster-Whisper speech recognition with word-level timestamps.
        """
        model = self.get_whisper_model()
        segments_gen, info = model.transcribe(
            str(wav_path),
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400)
        )

        segments = []
        for s in segments_gen:
            words = []
            if s.words:
                for w in s.words:
                    words.append({
                        "word": w.word,
                        "start": round(w.start, 2),
                        "end": round(w.end, 2),
                        "probability": round(w.probability, 2)
                    })
            segments.append({
                "id": s.id,
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "text": s.text.strip(),
                "words": words
            })

        logger.info(f"Transcribed {len(segments)} segments (Language: {info.language}, prob: {info.language_probability:.2f})")
        return segments

    def generate_clip_title(self, transcript_slice: str) -> str:
        """
        Generate a concise, engaging title from the clip transcript.
        """
        import re
        clean = transcript_slice.strip().replace("\n", " ")
        clean = re.sub(r"\s+", " ", clean)
        if not clean:
            return "Engaging Highlight"

        # Split into sentences or clauses
        sentences = [s.strip(" ,;:-\"'") for s in re.split(r"[.!?]+", clean) if len(s.strip(" ,;:-\"'")) > 6]
        if sentences:
            candidate = sentences[0]
            words = candidate.split()
            if len(words) > 8:
                return " ".join(words[:8]).strip(" ,;:-\"'").capitalize() + "..."
            return candidate.capitalize()

        words = clean.split()
        return " ".join(words[:6]).strip(" ,;:-\"'").capitalize()

    def rank_candidate_highlights(
        self,
        target_duration: float,
        num_clips: int,
        video_metadata: Dict[str, Any],
        segments: List[Dict[str, Any]],
        audio_signals: Dict[str, Any],
        scene_cuts: List[float]
    ) -> List[Dict[str, Any]]:
        """
        Heuristic Highlight Scoring Engine.
        Combines speech density, audio peaks, and scene changes.
        Snaps window start/end to sentence/word boundaries to avoid mid-speech cuts.
        Guarantees non-overlapping highlights.
        """
        video_duration = video_metadata.get("duration", 0.0)
        if target_duration <= 0 or num_clips < 1 or video_duration <= 0:
            raise ValueError("Duration and clip count must be positive")
        if video_duration <= target_duration:
            title = self.generate_clip_title(" ".join(s["text"] for s in segments))
            return [{
                "index": 1,
                "title": title,
                "start": 0.0,
                "end": video_duration,
                "duration": video_duration,
                "score": 100.0,
                "explanation": "Full video fits target duration."
            }]

        all_words = []
        for s in segments:
            all_words.extend(s.get("words", []))

        all_words.sort(key=lambda w: w["start"])
        word_starts = [w["start"] for w in all_words]
        word_ends = sorted(w["end"] for w in all_words)
        peak_times = sorted(set(audio_signals.get("peak_timestamps", [])))
        scene_cuts = sorted(scene_cuts)
        rms_times = audio_signals.get("timestamps", [])
        rms_values = audio_signals.get("rms_timeline", [])
        mean_db = audio_signals.get("mean_db", -30.0)

        step_sec = 2.0
        candidate_windows = []
        curr_time = 0.0

        while (curr_time + target_duration * 0.75) <= video_duration:
            ideal_start = curr_time
            ideal_end = min(video_duration, curr_time + target_duration)

            # Snap start to nearest word start (within 1.5s tolerance)
            snapped_start = ideal_start
            near = bisect.bisect_left(word_starts, ideal_start)
            options = word_starts[max(0, near - 1):near + 1]
            if options:
                closest = min(options, key=lambda t: abs(t - ideal_start))
                if abs(closest - ideal_start) <= 1.5:
                    snapped_start = closest

            # Snap end to nearest sentence or word end (within 2.0s tolerance)
            snapped_end = ideal_end
            near = bisect.bisect_left(word_ends, ideal_end)
            options = word_ends[max(0, near - 1):near + 1]
            if options:
                closest = min(options, key=lambda t: abs(t - ideal_end))
                if abs(closest - ideal_end) <= 2.0:
                    snapped_end = closest

            clip_dur = snapped_end - snapped_start
            if clip_dur < target_duration * 0.70 or clip_dur > target_duration * 1.30:
                curr_time += step_sec
                continue

            # 1. Speech Density Score
            left = bisect.bisect_left(word_starts, snapped_start)
            right = bisect.bisect_right(word_starts, snapped_end)
            words_in_window = all_words[left:right]
            wpm = (len(words_in_window) / (clip_dur / 60.0)) if clip_dur > 0 else 0
            # Target conversational pace ~ 120 - 180 wpm
            speech_density_score = min(100.0, (wpm / 140.0) * 100.0) if wpm > 0 else 10.0

            # 2. Audio Energy Score (peaks and relative RMS)
            peaks_in_window = bisect.bisect_right(peak_times, snapped_end) - bisect.bisect_left(peak_times, snapped_start)
            peak_score = min(100.0, (peaks_in_window / max(1.0, clip_dur / 5.0)) * 50.0)

            # 3. Scene Changes (Visual Pacing)
            cuts_in_window = bisect.bisect_right(scene_cuts, snapped_end) - bisect.bisect_left(scene_cuts, snapped_start)
            scene_score = min(100.0, (cuts_in_window / max(1.0, clip_dur / 6.0)) * 50.0)

            # Bonus for punctuation/questions/excitement in transcript
            window_text = " ".join(w["word"] for w in words_in_window)
            enthusiasm_bonus = 0.0
            if any(char in window_text for char in ["?", "!"]):
                enthusiasm_bonus += 15.0

            # Penalty if window cuts in the middle of a word
            boundary_penalty = 0.0
            for w in all_words[max(0, left-1):right+1]:
                if w["start"] < snapped_start < w["end"] or w["start"] < snapped_end < w["end"]:
                    boundary_penalty += 20.0

            # Total Composite Score
            composite_score = (
                0.40 * speech_density_score +
                0.35 * peak_score +
                0.25 * scene_score +
                enthusiasm_bonus - boundary_penalty
            )
            composite_score = round(max(0.0, min(100.0, composite_score)), 2)

            candidate_windows.append({
                "start": round(snapped_start, 2),
                "end": round(snapped_end, 2),
                "duration": round(clip_dur, 2),
                "score": composite_score,
                "text": window_text,
                "speech_wpm": round(wpm, 1),
                "cuts": cuts_in_window,
                "peaks": peaks_in_window
            })

            curr_time += step_sec

        # Rank candidates by score descending
        candidate_windows.sort(key=lambda x: x["score"], reverse=True)

        # Select non-overlapping highlights
        selected_clips = []
        for cand in candidate_windows:
            if len(selected_clips) >= num_clips:
                break
            # Check overlap with existing selected clips (allow max 3s overlap or require disjoint)
            overlap = False
            for sel in selected_clips:
                if not (cand["end"] <= sel["start"] or cand["start"] >= sel["end"]):
                    overlap = True
                    break
            if not overlap:
                cand["index"] = len(selected_clips) + 1
                cand["title"] = self.generate_clip_title(cand["text"])
                cand["explanation"] = (
                    f"Score: {cand['score']} | {cand['speech_wpm']} WPM | "
                    f"{cand['cuts']} visual scene cuts | {cand['peaks']} audio peaks."
                )
                selected_clips.append(cand)

        # Sort selected clips chronologically for export
        selected_clips.sort(key=lambda x: x["start"])
        for idx, clip in enumerate(selected_clips):
            clip["index"] = idx + 1

        return selected_clips
