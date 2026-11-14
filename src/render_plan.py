"""Execute an agent-authored edit plan against actual media with FFmpeg.

Supports arbitrary ordered source shots, per-shot framing, captions retimed to
the assembled audio, Part 1/Part 2 exports, and decode validation.
"""
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from config.settings import (ASPECT_RATIOS, EXPORT_DIR, PREVIEWS_DIR,
                             FFMPEG_BIN, FFPROBE_BIN, ENCODER_PRESET,
                             ENCODER_CRF_FINAL, ENCODER_CRF_PREVIEW,
                             RENDER_THREADS)
from src.agent_workflow import validate_plan, write_json
from src.caption_generator import CaptionGenerator, format_timestamp_ass
from src.transcript_tools import (correct_transcript, retime_shots,
                                  caption_cues, review_transcript)
from src.video_editor import VideoEditor
from src.video_analyzer import VideoAnalyzer

logger = logging.getLogger("AI-Clipping.AgentRender")


def _run(cmd, timeout=3600):
    process = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if process.returncode:
        raise RuntimeError("FFmpeg/FFprobe failed: " + process.stderr[-1500:])
    return process


def _probe(path):
    result = _run([FFPROBE_BIN, "-v", "error", "-print_format", "json",
                   "-show_format", "-show_streams", str(path)], timeout=60)
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration") or 0)
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if duration <= 0 or video is None:
        raise RuntimeError("Missing valid video or duration: " + str(path))
    return {"duration": duration, "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name") if audio else None,
            "width": video.get("width"), "height": video.get("height")}


def _ass_filter(path):
    # FFmpeg ASS filter accepts a path with escaped filter separators.
    escaped = str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return "ass='" + escaped + "'"


def _render_part(part, plan, source, out_dir, transcript, source_has_audio):
    settings = plan.get("settings") or {}
    mode = settings.get("quality", "final")
    aspect = settings.get("aspect_ratio", "9:16")
    width, height = ASPECT_RATIOS[aspect][mode]
    number = int(part["part"])
    output = out_dir / ("Part_%02d.mp4" % number)
    srt_output = out_dir / ("Part_%02d.srt" % number)
    ass_output = out_dir / ("Part_%02d.ass" % number)
    editor = VideoEditor()
    generator = CaptionGenerator()

    with tempfile.TemporaryDirectory(prefix="agent_edit_") as temp_name:
        temp = Path(temp_name)
        shot_paths = []
        durations = []
        for index, shot in enumerate(part["shots"], 1):
            shot_path = temp / ("shot_%03d.mp4" % index)
            editor.render_clip(
                source_video=source, start_time=float(shot["source_start"]),
                end_time=float(shot["source_end"]), output_path=shot_path,
                aspect_ratio=aspect, mode=mode, burn_captions=False,
                word_highlight=False, transcript_segments=[],
                style=shot.get("layout", settings.get("layout", "blur_fill")),
                normalize_audio=False,
                color_correction=bool(shot.get("color_correction", False)),
                zoom_effect=bool(shot.get("zoom_effect", False)))
            measured = _probe(shot_path)
            if bool(measured["audio_codec"]) != bool(source_has_audio):
                raise RuntimeError("Shot audio streams are inconsistent")
            shot_paths.append(shot_path)
            durations.append(measured["duration"])

        # All segments are from the same source and encoded to matching formats.
        playlist = temp / "shots.txt"
        playlist.write_text("".join("file '%s'\n" % p.name for p in shot_paths),
                            encoding="utf-8")
        assembled = temp / "assembled.mp4"
        _run([FFMPEG_BIN, "-y", "-v", "error", "-f", "concat",
              "-safe", "0", "-i", str(playlist), "-c", "copy",
              "-movflags", "+faststart", str(assembled)])
        actual_segments = retime_shots(part["shots"], transcript, durations)
        cues = caption_cues(actual_segments)
        generator.generate_srt(cues, srt_output)
        generator.generate_styled_ass(
            cues, ass_output, video_width=width, video_height=height,
            word_level_highlight=bool(settings.get("word_highlight", True)))
        title = part.get("title_card") or ""
        if title:
            # Text supplied by an agent never becomes raw ASS control codes.
            safe_title = re.sub(r"[^A-Za-z0-9 #._-]", "", str(title))[:64]
            if safe_title:
                with ass_output.open("a", encoding="utf-8") as subtitles:
                    end = min(2.0, sum(durations))
                    subtitles.write(
                        "Dialogue: 2,0:00:00.00,%s,Default,,0,0,0,,"
                        "{\\an8\\fs72\\bord5\\shad2}%s\n"
                        % (format_timestamp_ass(end), safe_title))
        partial = temp / "final.mp4"
        if settings.get("captions", True):
            cmd = [FFMPEG_BIN, "-y", "-v", "error",
                   "-threads", str(RENDER_THREADS),
                   "-i", str(assembled), "-vf", _ass_filter(ass_output),
                   "-map", "0:v:0"]
            if source_has_audio:
                cmd += ["-map", "0:a:0"]
            cmd += ["-c:v", "libx264", "-preset", ENCODER_PRESET,
                    "-crf", str(ENCODER_CRF_FINAL if mode == "final" else ENCODER_CRF_PREVIEW),
                    "-pix_fmt", "yuv420p"]
            cmd += ["-c:a", "copy"] if source_has_audio else ["-an"]
            cmd += ["-movflags", "+faststart", str(partial)]
            _run(cmd)
        else:
            _run([FFMPEG_BIN, "-y", "-v", "error", "-i", str(assembled),
                  "-c", "copy", "-movflags", "+faststart", str(partial)])
        # Only publish a validated playable export.
        probe = _probe(partial)
        decode = subprocess.run([FFMPEG_BIN, "-v", "error", "-i", str(partial),
                                 "-f", "null", "-"],
                                capture_output=True, text=True, timeout=3600)
        issues = []
        if decode.returncode or decode.stderr.strip():
            issues.append("Decode error: " + decode.stderr[-500:])
        if probe["width"] != width or probe["height"] != height:
            issues.append("Unexpected output resolution")
        if probe["video_codec"] != "h264":
            issues.append("Unexpected video codec")
        expected = sum(durations)
        if abs(probe["duration"] - expected) > max(.75, .03 * expected):
            issues.append("Assembled duration differs from source shot sum")
        if issues:
            raise RuntimeError("; ".join(issues))
        partial.replace(output)

    review = review_transcript(actual_segments)
    report = {
        "part": number, "title": part.get("title", ""),
        "output": str(output.resolve()),
        "srt": str(srt_output.resolve()),
        "ass": str(ass_output.resolve()),
        "shot_count": len(part["shots"]),
        "source_intervals": [{"start": s["source_start"], "end": s["source_end"]}
                             for s in part["shots"]],
        "duration": probe["duration"], "video_codec": probe["video_codec"],
        "audio_codec": probe["audio_codec"],
        "resolution": [probe["width"], probe["height"]],
        "full_decode_passed": not issues, "caption_review_flags": review,
        "caption_accuracy_guaranteed": False,
    }
    write_json(out_dir / ("Part_%02d_quality_report.json" % number), report)
    return report


def render_plan(plan, output_dir=None):
    """Render the actual video specified by a validated agent EDL."""
    source = Path(plan["source"]).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    meta = VideoAnalyzer().probe_video(source)
    validate_plan(plan, meta["duration"])
    settings = plan.get("settings") or {}
    out_dir = Path(output_dir) if output_dir else (
        EXPORT_DIR if settings.get("quality", "final") == "final" else PREVIEWS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = correct_transcript(
        plan.get("transcript") or [], plan.get("caption_corrections") or {})
    results = []
    for part in sorted(plan["parts"], key=lambda item: item["part"]):
        results.append(_render_part(part, plan, source, out_dir, transcript,
                                    meta["has_audio"]))
    write_json(out_dir / "edit_plan.json", plan)
    return {"status": "completed", "source": str(source),
            "output_dir": str(out_dir.resolve()), "parts": results}
