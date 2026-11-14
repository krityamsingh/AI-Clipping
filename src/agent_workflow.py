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


PROFILES = {"general", "podcast", "gaming", "talking_head", "tutorial"}
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
                   max_candidates=10, vocabulary=None, force=False):
    """Analyze actual media. Reuse a cache tied to file mtime, model and vocab."""
    from src.downloader import VideoDownloader
    from src.video_analyzer import VideoAnalyzer

    path = VideoDownloader(RAW_DIR).resolve_source(str(source))
    vocabulary = list(vocabulary or [])
    if not isinstance(vocabulary, list) or any(not isinstance(v, str) for v in vocabulary):
        raise ValueError("Vocabulary must be a list of strings")
    stat = path.stat()
    key = json.dumps([str(path), stat.st_size, stat.st_mtime_ns,
                      model, float(target_duration), max_candidates, vocabulary])
    cache = BASE_DIR / "analysis" / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".json")
    if cache.is_file() and not force:
        return read_json(cache)
    if not 1 <= max_candidates <= 100:
        raise ValueError("Candidate count must be 1..100")
    analyzer = VideoAnalyzer(whisper_model_name=model)
    meta = analyzer.probe_video(path)
    audio = analyzer.extract_audio(path) if meta["has_audio"] else None
    try:
        segments = analyzer.transcribe_audio(
            audio, initial_prompt=", ".join(vocabulary) if vocabulary else None) if audio else []
        signals = analyzer.analyze_audio_signals(audio) if audio else {}
    finally:
        # Cache file name is source-based; don't remove persistent user audio.
        pass
    cuts = analyzer.detect_scenes(path)
    candidates = analyzer.rank_candidate_highlights(
        target_duration=target_duration, num_clips=max_candidates,
        video_metadata=meta, segments=segments, audio_signals=signals,
        scene_cuts=cuts)
    report = {
        "version": PLAN_VERSION, "source": str(path.resolve()),
        "model": model, "vocabulary": vocabulary, "metadata": meta,
        "transcript": segments, "scene_cuts": cuts,
        "candidate_highlights": candidates,
        "caption_review_flags": review_transcript(segments),
        "analysis_limitations": [
            "Transcript ranking is heuristic, not visual-language understanding.",
            "Audio recognition may contain errors; review low-confidence words.",
            "No model can guarantee captions match speech without listening."
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
                    captions=True):
    """Create chronologically ordered episodic cuts from observed highlights."""
    if profile not in PROFILES:
        raise ValueError("Invalid profile")
    if aspect_ratio not in ASPECTS or quality not in QUALITIES:
        raise ValueError("Invalid output settings")
    if not math.isfinite(target_duration) or not 5 <= target_duration <= 600:
        raise ValueError("Target duration must be 5..600 seconds")
    duration = float(report["metadata"]["duration"])
    if max_parts is None:
        count = 4 if duration >= 1200 else 3 if duration >= 600 else 2 if duration >= 180 else 1
    else:
        count = int(max_parts)
        if count < 1 or count > 100:
            raise ValueError("max_parts must be 1..100")
    # Use the candidate's existing observed evidence where available.
    candidates = list(report.get("candidate_highlights") or [])
    if len(candidates) < count:
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
            "shots": [{
                "shot_id": "shot_1",
                "source_start": candidate["start"],
                "source_end": candidate["end"],
                "purpose": "complete highlight / episode",
                "reason": candidate.get("explanation") or "Selected from observed transcript",
                "layout": "blur_fill" if profile in {"podcast", "talking_head", "general"} else "fit_pad",
                "zoom_effect": False,
                "color_correction": False,
            }],
            "evidence": candidate.get("evidence") or {},
        })
    if not parts:
        raise ValueError("No valid candidate highlights. Provide agent-selected shots.")
    plan = {
        "version": PLAN_VERSION, "source": report["source"],
        "profile": profile, "model": report.get("model"),
        "settings": {"aspect_ratio": aspect_ratio, "quality": quality,
                     "captions": bool(captions), "word_highlight": True,
                     "normalize_audio": True},
        "caption_corrections": {},
        "transcript": report.get("transcript") or [],
        "parts": parts
    }
    return validate_plan(plan, duration)
