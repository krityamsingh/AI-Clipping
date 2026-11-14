"""Agent-facing video analysis and edit decision list (EDL) API.

Any agent can read a JSON analysis report, select shots, edit the JSON plan,
then call the render CLI. No model vendor, cloud API, or Python code mutation.
"""
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from config.settings import BASE_DIR, RAW_DIR
from src.transcript_tools import correct_transcript, review_transcript
from src.clip_profiles import PROFILES, EDIT_STYLES, get_style, SIGNAL_WEIGHTS


LAYOUTS = {"blur_fill", "center_crop", "fit_pad"}
ASPECTS = {"9:16", "16:9", "1:1"}
QUALITIES = {"final", "preview"}
PLAN_VERSION = 1


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8",
                                         dir=path.parent, prefix=".agent_",
                                         suffix=".json", delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return path


def read_json(path):
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def analyze_source(source, model="base", target_duration=45.0,
                   max_candidates=10, vocabulary=None, force=False,
                   profile="general", chat_log=None, signals_only=False):
    """Analyze actual media. Reuse a cache tied to file mtime, model and vocab."""
    from src.downloader import VideoDownloader
    from src.video_analyzer import VideoAnalyzer

    if profile not in PROFILES:
        raise ValueError("Unknown clipping profile")
    if chat_log and not Path(chat_log).is_file():
        raise FileNotFoundError(chat_log)
    path = VideoDownloader(RAW_DIR).resolve_source(str(source))
    vocabulary = list(vocabulary or [])
    if not isinstance(vocabulary, list) or any(not isinstance(v, str) for v in vocabulary):
        raise ValueError("Vocabulary must be a list of strings")
    stat = path.stat()
    chat_meta = None
    if chat_log:
        chat_stat = Path(chat_log).stat()
        chat_meta = [str(Path(chat_log).resolve()), chat_stat.st_size, chat_stat.st_mtime_ns]
    key = json.dumps([str(path), stat.st_size, stat.st_mtime_ns,
                      model, float(target_duration), max_candidates, vocabulary,
                      profile, chat_meta, bool(signals_only)])
    cache = BASE_DIR / "analysis" / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".json")
    if cache.is_file() and not force:
        return read_json(cache)
    if not 1 <= max_candidates <= 100:
        raise ValueError("Candidate count must be 1..100")
    analyzer = VideoAnalyzer(whisper_model_name=model)
    meta = analyzer.probe_video(path)
    audio = analyzer.extract_audio(path) if meta["has_audio"] else None
    segments = (analyzer.transcribe_audio(
        audio, initial_prompt=", ".join(vocabulary) if vocabulary else None)
        if audio and not signals_only else [])
    signals = analyzer.analyze_audio_signals(audio) if audio else {}
    from src.stream_highlights import (sample_motion, audio_events, chat_bursts,
                                       parse_chat, rank_stream_highlights)
    # Visual evidence is generated for action-oriented profiles or fast VOD/stream
    # mode. Do not claim semantic action recognition from frame differences.
    activity = None
    if profile in SIGNAL_WEIGHTS or signals_only or chat_log:
        motion = sample_motion(path)
        chat = chat_bursts(parse_chat(chat_log), meta["duration"]) if chat_log else []
        audio_spikes = audio_events(signals)
        cuts = [m["timestamp"] for m in motion if m["scene_jump"]]
        activity_candidates = rank_stream_highlights(
            meta["duration"], motion, audio_spikes, chat, cuts,
            profile=profile, target_duration=target_duration,
            num_clips=max_candidates)
        activity = {"method": "observed_motion_audio_chat_relative_spikes",
                    "motion": motion, "audio_events": audio_spikes,
                    "chat_bursts": chat, "candidate_highlights": activity_candidates,
                    "limitations": [
                        "Detected movement is not proof of a kill, goal, or exciting event.",
                        "Scene cuts and camera shakes can produce false positives.",
                        "Chat timestamps must be seconds relative to recording start."
                    ]}
    else:
        cuts = analyzer.detect_scenes(path)
    transcript_candidates = (analyzer.rank_candidate_highlights(
        target_duration=target_duration, num_clips=max_candidates,
        video_metadata=meta, segments=segments, audio_signals=signals,
        scene_cuts=cuts) if segments and not signals_only else [])
    # For action-oriented videos use actual motion/audio evidence to propose
    # windows. For dialogue formats prefer self-contained transcript candidates.
    candidates = (activity["candidate_highlights"] if activity else [])
    if not candidates:
        candidates = transcript_candidates
    elif profile not in SIGNAL_WEIGHTS and transcript_candidates:
        candidates = transcript_candidates
    # For silent, visually static inputs there may genuinely be no highlights.
    if not candidates and not activity:
        candidates = analyzer.rank_candidate_highlights(
            target_duration=target_duration, num_clips=max_candidates,
            video_metadata=meta, segments=segments, audio_signals=signals,
            scene_cuts=cuts)
    report = {
        "version": PLAN_VERSION, "source": str(path.resolve()),
        "model": model, "vocabulary": vocabulary, "profile": profile,
        "signals_only": bool(signals_only), "metadata": meta,
        "transcript": segments, "scene_cuts": cuts,
        "activity_analysis": activity,
        "candidate_highlights": candidates,
        "caption_review_flags": review_transcript(segments),
        "analysis_limitations": [
            "Transcript ranking is heuristic, not visual-language understanding.",
            "Audio recognition may contain errors; review low-confidence words.",
            "No model can guarantee captions match speech without listening.",
            "High movement/audio/chat scores do not prove that events are spectacular."
        ]
    }
    write_json(cache, report)
    return report


def validate_plan(plan, source_duration=None):
    """Validate untrusted agent-generated EDL before running FFmpeg."""
    if not isinstance(plan, dict) or plan.get("version") != PLAN_VERSION:
        raise ValueError("Plan version must be 1")
    source = plan.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("A source file path is required")
    settings = plan.get("settings") or {}
    if settings.get("aspect_ratio", "9:16") not in ASPECTS:
        raise ValueError("Unsupported output aspect")
    if settings.get("quality", "final") not in QUALITIES:
        raise ValueError("Unsupported quality")
    if not isinstance(plan.get("caption_corrections", {}), dict):
        raise ValueError("caption_corrections must be an object")
    profile = plan.get("profile", "general")
    if profile not in PROFILES:
        raise ValueError("Unsupported edit profile")
    get_style(settings.get("edit_style"), profile)
    parts = plan.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 100:
        raise ValueError("A plan must have between 1 and 100 parts")
    numbers = set()
    for part in parts:
        if not isinstance(part, dict):
            raise ValueError("Each part must be an object")
        number = part.get("part")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1 or number in numbers:
            raise ValueError("Part numbers must be unique positive integers")
        numbers.add(number)
        get_style(part.get("edit_style", settings.get("edit_style")), profile)
        shots = part.get("shots")
        if not isinstance(shots, list) or not 1 <= len(shots) <= 200:
            raise ValueError("Each part must contain 1 to 200 shots")
        total = 0.0
        for shot in shots:
            if not isinstance(shot, dict):
                raise ValueError("Shot entries must be objects")
            try:
                start, end = float(shot["source_start"]), float(shot["source_end"])
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError("Shot must contain numeric source_start/source_end") from e
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or end - start < 0.2:
                raise ValueError("Shot timestamps must be finite and at least 0.2s")
            if source_duration is not None and end > source_duration + .05:
                raise ValueError("Shot exceeds source media duration")
            layout = shot.get("layout", settings.get("layout", "blur_fill"))
            if layout not in LAYOUTS:
                raise ValueError("Unsupported shot layout")
            total += end - start
        if total > 7200:
            raise ValueError("Part exceeds two-hour render safety limit")
    return plan


def build_auto_plan(report, *, profile="general", target_duration=45.0,
                    max_parts=None, aspect_ratio="9:16", quality="final",
                    captions=True, edit_style=None):
    """Create chronologically ordered episodic cuts from observed highlights."""
    if profile not in PROFILES:
        raise ValueError("Invalid profile")
    style_name, style_def = get_style(edit_style, profile)
    if aspect_ratio not in ASPECTS or quality not in QUALITIES:
        raise ValueError("Invalid output settings")
    if not math.isfinite(target_duration) or not 5 <= target_duration <= 600:
        raise ValueError("Target duration must be 5..600 seconds")
    duration = float(report["metadata"]["duration"])
    if max_parts is None:
        count = (min(12, max(3, int(duration // 900))) if profile in {"livestream", "gaming", "esports", "sports"} and duration >= 1200
                 else 4 if duration >= 1200 else 3 if duration >= 600 else 2 if duration >= 180 else 1)
    else:
        count = int(max_parts)
        if count < 1 or count > 100:
            raise ValueError("max_parts must be 1..100")
    # Use the candidate's existing observed evidence where available.
    candidates = list(report.get("candidate_highlights") or [])
    if len(candidates) < count and report.get("transcript"):
        from src.video_analyzer import VideoAnalyzer
        candidates = VideoAnalyzer().rank_candidate_highlights(
            target_duration=target_duration, num_clips=count,
            video_metadata=report["metadata"], segments=report.get("transcript") or [],
            audio_signals={}, scene_cuts=report.get("scene_cuts") or [])
    candidates = sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)
    best = []
    for candidate in candidates:
        if all(candidate["end"] <= chosen["start"] or candidate["start"] >= chosen["end"] for chosen in best):
            best.append(candidate)
        if len(best) >= count:
            break
    candidates = sorted(best, key=lambda item: (item["start"], item["end"]))
    if max_parts is not None and len(candidates) < count:
        raise ValueError("Not enough distinct source highlights for requested parts; select shots manually or reduce --parts")
    parts = []
    for index, candidate in enumerate(candidates[:count], 1):
        parts.append({
            "part": index,
            "title": candidate.get("title", "Highlight"),
            "title_card": "PART " + str(index) if count > 1 else "",
            "edit_style": style_name,
            "shots": [{
                "shot_id": "shot_1",
                "source_start": candidate["start"],
                "source_end": candidate["end"],
                "purpose": "complete highlight / episode",
                "reason": candidate.get("explanation") or "Selected from observed transcript",
                "layout": style_def["layout"],
                "zoom_effect": False,
                "color_correction": style_def["color_correction"],
            }],
            "evidence": candidate.get("evidence") or {},
        })
    if not parts:
        raise ValueError("No valid candidate highlights. Provide agent-selected shots.")
    plan = {
        "version": PLAN_VERSION, "source": report["source"],
        "profile": profile, "model": report.get("model"),
        "selection_method": report.get("candidate_highlights", [{}])[0].get("selection_method") if report.get("candidate_highlights") else None,
        "settings": {"aspect_ratio": aspect_ratio, "quality": quality,
                     "edit_style": style_name,
                     "captions": bool(captions and report.get("transcript")), "word_highlight": True,
                     "normalize_audio": True},
        "caption_corrections": {},
        "transcript": report.get("transcript") or [],
        "parts": parts
    }
    return validate_plan(plan, duration)
