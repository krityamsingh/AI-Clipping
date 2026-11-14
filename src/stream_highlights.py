"""Bounded CPU analysis of high-motion live/VOD footage and optional chat spikes.

Records measured video-frame differences, audio-relative energy and chat burst
times. NO semantic claims about kills, goals, 'crazy' actions or viral success.
It is a candidate generator. A vision agent should review actual frames.
"""
import bisect
import json
import math
import re
import subprocess
from pathlib import Path

import numpy as np

from config.settings import FFMPEG_BIN
from src.clip_profiles import SIGNAL_WEIGHTS, PROFILES

FRAME_WIDTH = 144
FRAME_HEIGHT = 80
FRAME_FPS = 2.0
_CHAT_HYPE = re.compile(r"\b(?:pog|poggers|omg|wow|insane|clutch|gg|no way|holy|lets go|"
                        r"let's go|crazy|hype|goall?|w(?:tf)+|amazing|op)\b",
                        flags=re.IGNORECASE)


def _robust_spikes(values):
    """Return 0..1 relative spike strengths, tolerating constant noisy streams."""
    arr = np.asarray(values, dtype=np.float64)
    if not len(arr):
        return []
    baseline = float(np.median(arr))
    spread = float(np.percentile(arr, 90) - baseline)
    if spread <= 1e-7:
        return [0.0] * len(arr)
    return [round(float(min(1, max(0, (x - baseline) / spread))), 4) for x in arr]


def sample_motion(video_path, fps=FRAME_FPS, width=FRAME_WIDTH, height=FRAME_HEIGHT):
    """Stream 2fps downscaled gray frames from FFmpeg, bounded by one frame."""
    if fps <= 0 or fps > 5 or width < 32 or height < 32:
        raise ValueError("Invalid sampling dimensions/rate")
    frame_size = width * height
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
           "-threads", "2", "-i", str(video_path), "-an",
           "-vf", f"fps={fps},scale={width}:{height},format=gray",
           "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, bufsize=frame_size * 4)
    results = []
    previous = None
    last_motion = 0.0
    try:
        index = 0
        while True:
            data = proc.stdout.read(frame_size)
            if not data:
                break
            if len(data) != frame_size:
                raise RuntimeError("Incomplete raw video frame returned by FFmpeg")
            frame = np.frombuffer(data, dtype=np.uint8)
            brightness = float(np.mean(frame) / 255.0)
            if previous is not None:
                # Use int16 to avoid unsigned wraparound on pixel subtraction.
                delta = np.abs(frame.astype(np.int16) - previous.astype(np.int16))
                motion = float(np.mean(delta) / 255.0)
                changed = float(np.count_nonzero(delta > 25) / frame_size)
                # Scene transitions are isolated very high changed-pixel rates;
                # sustained action needs more than a lone cut/flash.
                scene_jump = changed >= .74 and motion >= .18
                sustained = min(1.0, (motion + last_motion) / .38)
                results.append({"timestamp": round(index / fps, 3),
                                "motion": round(motion, 5),
                                "changed_fraction": round(changed, 5),
                                "brightness": round(brightness, 4),
                                "scene_jump": scene_jump,
                                "sustained": round(sustained, 4)})
                last_motion = motion
            previous = frame.copy()
            index += 1
        if proc.wait(timeout=30) != 0:
            raise RuntimeError("Motion analysis FFmpeg process failed")
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    spike_values = _robust_spikes(
        [r["motion"] * (0.25 if r["scene_jump"] else 1.0) * (0.55 + 0.45 * r["sustained"])
         for r in results])
    for item, spike in zip(results, spike_values):
        item["motion_spike"] = spike
    return results


def parse_chat(path):
    """Read relative-seconds timestamped JSON, JSONL or [HH:MM:SS] lines."""
    if not path:
        return []
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Chat log too large (>32MiB); split or summarize it first")
    content = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        payload = json.loads(content)
        rows = payload.get("messages", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("Chat JSON must contain an array of messages")
    else:
        rows = []
        for line in content.splitlines():
            if not line.strip():
                continue
            if line.lstrip().startswith("{"):
                rows.append(json.loads(line))
            else:
                m = re.match(r"\[(\d{1,2}):(\d{2}):(\d{2})\]\s*(.+)", line)
                if m:
                    timestamp = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
                    rows.append({"time": timestamp, "text": m[4]})
    events = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        value = item.get("time", item.get("timestamp", item.get("offset")))
        try:
            t = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(t) or t < 0:
            continue
        # Relative seconds only. Absolute Unix timestamps require an explicit
        # conversion by the ingesting agent, not a guessed stream start.
        if t > 86400 * 7:
            continue
        text = str(item.get("text", item.get("message", "")))[:1000]
        events.append({"timestamp": round(t, 3),
                       "hype": bool(_CHAT_HYPE.search(text))})
    return sorted(events, key=lambda event: event["timestamp"])


def chat_bursts(events, duration, interval=5):
    """Measure chat messages per interval against recording-local activity."""
    if not events:
        return []
    counts = {}
    hype = {}
    for e in events:
        if e["timestamp"] >= duration:
            continue
        index = int(e["timestamp"] // interval)
        counts[index] = counts.get(index, 0) + 1
        hype[index] = hype.get(index, 0) + int(e["hype"])
    size = max(1, int(math.ceil(duration / interval)))
    if size > 100000:
        raise ValueError("Unreasonable chat timeline")
    dense = [counts.get(i, 0) for i in range(size)]
    spikes = _robust_spikes(dense)
    results = []
    for i, score in enumerate(spikes):
        if counts.get(i, 0) <= 0:
            continue
        results.append({"timestamp": round((i + .5) * interval, 2),
                        "count": counts[i],
                        "hype_count": hype.get(i, 0),
                        "spike": round(min(1.0, .85 * score + .15 * min(1, hype.get(i, 0)/3)), 4)})
    return results


def audio_events(signals):
    times = signals.get("timestamps") or []
    rms = signals.get("rms_timeline") or []
    if len(times) != len(rms):
        return []
    spikes = _robust_spikes(rms)
    events = []
    for i, (t, db, spike) in enumerate(zip(times, rms, spikes)):
        # Sudden onset independently matters, but never treat loudness as semantics.
        onset = max(0.0, float(db) - float(rms[i-1])) if i else 0.0
        onset_score = min(1.0, onset / 15.0)
        energy = min(1.0, .65 * spike + .35 * onset_score)
        if energy >= .40:
            events.append({"timestamp": float(t), "energy": round(energy, 4)})
    return events


def _window_strength(events, start, end, key):
    values = [e[key] for e in events if start <= e["timestamp"] < end]
    if not values:
        return 0.0, 0
    # Reward sustained events while avoiding the number of samples dominating.
    strong = sum(1 for x in values if x >= .6)
    return min(1.0, (.58 * max(values) + .42 * min(1.0, strong / 4))), len(values)


def rank_stream_highlights(duration, motion, audio, chat=None, scene_cuts=None,
                           *, profile="livestream", target_duration=40,
                           num_clips=8, context_before=12):
    """Rank non-overlapping highlight windows from observed, timestamped signals."""
    if profile not in PROFILES:
        raise ValueError("Unknown content profile")
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(target_duration) or target_duration <= 0:
        raise ValueError("Duration must be positive and finite")
    if not 1 <= num_clips <= 100:
        raise ValueError("Clip count must be between 1 and 100")
    chat, scene_cuts = chat or [], sorted(scene_cuts or [])
    audio = sorted(audio, key=lambda e: e["timestamp"])
    motion = sorted(motion, key=lambda e: e["timestamp"])
    chats = sorted(chat, key=lambda e: e["timestamp"])
    wm, wa, wc = SIGNAL_WEIGHTS.get(profile, SIGNAL_WEIGHTS["general"])
    if not chat:
        total = wm + wa
        wm, wa, wc = wm / total, wa / total, 0.0
    seed = sorted([(v["motion_spike"], v["timestamp"], "motion") for v in motion
                   if v.get("motion_spike", 0) >= .40] +
                  [(v["energy"], v["timestamp"], "audio") for v in audio
                   if v.get("energy", 0) >= .48] +
                  [(v["spike"], v["timestamp"], "chat") for v in chat
                   if v.get("spike", 0) >= .40], reverse=True)
    if not seed:
        return []
    windows = []
    unique = set()
    for strength, t, source in seed[:1200]:
        length = min(duration, target_duration)
        # Keep the triggering event inside the window even for very short clips.
        effective_padding = min(context_before, length * .45)
        start = max(0.0, min(t - effective_padding, duration - length))
        end = start + length
        key = round(start, 1)
        if key in unique:
            continue
        unique.add(key)
        m, n_motion = _window_strength(motion, start, end, "motion_spike")
        a, n_audio = _window_strength(audio, start, end, "energy")
        c, n_chat = _window_strength(chats, start, end, "spike")
        if not max(m, a, c):
            continue
        cuts = bisect.bisect_left(scene_cuts, end) - bisect.bisect_right(scene_cuts, start)
        score = 100.0 * (wm*m + wa*a + wc*c)
        evidence = {
            "peak_time": round(t, 2),
            "trigger": source,
            "motion_strength": round(m, 3),
            "audio_strength": round(a, 3),
            "chat_strength": round(c, 3),
            "motion_samples": n_motion, "audio_events": n_audio,
            "chat_burst_bins": n_chat, "scene_cuts": cuts,
            "signal_weights": {"motion": round(wm, 3), "audio": round(wa, 3),
                               "chat": round(wc, 3)},
            "note": "Measured relative peaks, not confirmed game/sport events."
        }
        windows.append({
            "start": round(start, 2), "end": round(end, 2),
            "duration": round(length, 2), "score": round(min(100.0, score), 2),
            "score_type": "relative_activity_heuristic_not_virality_probability",
            "selection_method": "stream_audio_motion_chat",
            "title": "Activity near %02d:%02d:%02d" % (t // 3600, (t % 3600)//60, t % 60),
            "explanation": "Measured relative " + source + " spike; verify video context.",
            "evidence": evidence, "text": ""
        })
    windows.sort(key=lambda w: (-w["score"], w["start"]))
    chosen = []
    for window in windows:
        if all(window["end"] <= v["start"] or window["start"] >= v["end"] for v in chosen):
            chosen.append(window)
            if len(chosen) >= num_clips:
                break
    chosen.sort(key=lambda w: w["start"])
    for i, item in enumerate(chosen, 1):
        item["index"] = i
    return chosen


def analyze_activity(source, metadata, audio_signals, chat_log=None,
                     profile="livestream", target_duration=40, num_clips=10):
    motion = sample_motion(source)
    audio = audio_events(audio_signals)
    chat = chat_bursts(parse_chat(chat_log), float(metadata["duration"])) if chat_log else []
    selected = rank_stream_highlights(
        float(metadata["duration"]), motion, audio, chat, [],
        profile=profile, target_duration=target_duration, num_clips=num_clips)
    return {"motion": motion, "audio_events": audio, "chat_bursts": chat,
            "highlight_candidates": selected,
            "method": "downsampled_frame_differences_audio_relative_onsets_optional_chat",
            "limitations": ["Action is not semantically recognized; review source frames.",
                            "Fast flashes/camera cuts can cause false positives.",
                            "Sampled motion is not optical-flow tracking."]}
