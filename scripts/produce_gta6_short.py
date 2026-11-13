#!/usr/bin/env python3
"""
Professional GTA 6 YouTube Short Production Script
Produces one fully edited, professional-quality 9:16 Short from the GTA 6 source video.

Stages:
  1. Environment verification
  2. Source validation
  3. Audio extraction (reuse cached)
  4. Transcription (Faster-Whisper base INT8)
  5. Scene detection (PyAV backend)
  6. Audio signal analysis
  7. Content-aware highlight ranking (GTA 6 specific)
  8. 720p preview render + inspection
  9. Final 1080x1920 render
 10. SRT generation + JSON report + FFmpeg decode verification
"""

import json
import logging
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Project root
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import (
    FFMPEG_BIN, FFPROBE_BIN,
    RAW_DIR, EXPORT_DIR, PREVIEWS_DIR, AUDIO_DIR, CAPTIONS_DIR,
    WHISPER_MODEL_NAME, CPU_THREADS, RENDER_THREADS,
    ENCODER_CODEC, ENCODER_PRESET, ENCODER_CRF_FINAL,
    AUDIO_CODEC, AUDIO_BITRATE, AUDIO_SAMPLE_RATE
)
from src.video_analyzer import VideoAnalyzer
from src.video_editor import VideoEditor
from src.caption_generator import CaptionGenerator, format_timestamp_srt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("GTA6-Pro")

# ─── Configuration ───────────────────────────────────────────
SOURCE_VIDEO = RAW_DIR / "download_20261113_003958_EDaMIIk8oGk.mp4"
SOURCE_URL = "https://youtu.be/EDaMIIk8oGk"
TARGET_DURATION = 38.0  # 30-45s sweet spot
FINAL_OUTPUT = EXPORT_DIR / "GTA6_Final_Short.mp4"
SRT_OUTPUT = EXPORT_DIR / "GTA6_Final_Short.srt"
REPORT_OUTPUT = EXPORT_DIR / "GTA6_Clip_Report.json"
PREVIEW_OUTPUT = PREVIEWS_DIR / "GTA6_Preview_720p.mp4"

# GTA 6 content keywords for boosting relevance
GTA6_KEYWORDS = [
    "gta", "gta 6", "gta6", "rockstar", "vice city", "trailer",
    "open world", "map", "detail", "secret", "easter egg", "gameplay",
    "npc", "character", "weapon", "vehicle", "car", "police", "wanted",
    "swimming", "animation", "physics", "graphics", "rain", "weather",
    "mission", "heist", "robbery", "gang", "drive", "explosion",
    "tattoo", "hospital", "realistic", "new feature", "motorcycle",
    "helicopter", "boat", "plane", "sunset", "ocean", "beach",
    "girlfriend", "relationship", "gun", "shooting",
    "red dead", "rdr", "crazy", "insane", "amazing", "unbelievable",
]


def verify_environment():
    """Stage 1: Verify all critical components."""
    print("\n" + "=" * 70)
    print(" STAGE 1: ENVIRONMENT VERIFICATION")
    print("=" * 70)

    checks = []
    # FFmpeg
    r = subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, text=True, timeout=5)
    ok = r.returncode == 0
    checks.append(("FFmpeg", ok))
    print(f"  {'✅' if ok else '❌'} FFmpeg: {r.stdout.splitlines()[0][:60] if ok else 'MISSING'}")

    # FFprobe
    r = subprocess.run([FFPROBE_BIN, "-version"], capture_output=True, text=True, timeout=5)
    ok = r.returncode == 0
    checks.append(("FFprobe", ok))
    print(f"  {'✅' if ok else '❌'} FFprobe")

    # Python packages
    for pkg in ("faster_whisper", "scenedetect", "cv2", "numpy", "soundfile"):
        try:
            __import__(pkg)
            checks.append((pkg, True))
            print(f"  ✅ {pkg}")
        except ImportError:
            checks.append((pkg, False))
            print(f"  ❌ {pkg} MISSING")

    print(f"  ✅ CPU Threads: {CPU_THREADS} | Render Threads: {RENDER_THREADS}")

    if not all(c[1] for c in checks):
        raise RuntimeError("Environment checks failed")
    return True


def validate_source():
    """Stage 2: Validate the source video."""
    print("\n" + "=" * 70)
    print(" STAGE 2: SOURCE VIDEO VALIDATION")
    print("=" * 70)

    if not SOURCE_VIDEO.is_file():
        raise FileNotFoundError(f"Source video not found: {SOURCE_VIDEO}")

    analyzer = VideoAnalyzer()
    meta = analyzer.probe_video(SOURCE_VIDEO)
    print(f"  File: {SOURCE_VIDEO.name}")
    print(f"  Size: {SOURCE_VIDEO.stat().st_size / 1048576:.1f} MB")
    print(f"  Duration: {meta['duration']:.1f}s ({meta['duration']/60:.1f} min)")
    print(f"  Video: {meta['video_codec']} {meta['width']}x{meta['height']} @ {meta['fps']}fps")
    print(f"  Audio: {meta['audio_codec']}")
    return meta


def extract_and_cache_audio(meta):
    """Stage 3: Extract audio (reuse if cached)."""
    print("\n" + "=" * 70)
    print(" STAGE 3: AUDIO EXTRACTION")
    print("=" * 70)

    wav_path = AUDIO_DIR / f"{SOURCE_VIDEO.stem}_audio16k.wav"
    if wav_path.is_file() and wav_path.stat().st_size > 1000:
        print(f"  ✅ Cached audio found: {wav_path.name} ({wav_path.stat().st_size / 1048576:.1f} MB)")
        return wav_path

    analyzer = VideoAnalyzer()
    wav_path = analyzer.extract_audio(SOURCE_VIDEO, output_wav=wav_path)
    print(f"  ✅ Extracted: {wav_path.name} ({wav_path.stat().st_size / 1048576:.1f} MB)")
    return wav_path


def transcribe_speech(wav_path):
    """Stage 4: Transcribe with Faster-Whisper."""
    print("\n" + "=" * 70)
    print(" STAGE 4: SPEECH TRANSCRIPTION (Faster-Whisper base INT8)")
    print("=" * 70)

    # Check for cached transcript
    cache_path = AUDIO_DIR / f"{SOURCE_VIDEO.stem}_transcript.json"
    if cache_path.is_file():
        print(f"  ✅ Cached transcript found: {cache_path.name}")
        with open(cache_path) as f:
            segments = json.load(f)
        print(f"  Loaded {len(segments)} segments from cache")
        return segments

    t0 = time.time()
    analyzer = VideoAnalyzer()
    segments = analyzer.transcribe_audio(wav_path)
    elapsed = time.time() - t0
    print(f"  ✅ Transcribed {len(segments)} segments in {elapsed:.1f}s")

    # Cache for reuse
    with open(cache_path, "w") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"  Cached to {cache_path.name}")
    return segments


def detect_scenes():
    """Stage 5: Scene detection."""
    print("\n" + "=" * 70)
    print(" STAGE 5: SCENE DETECTION (PyAV + FFmpeg fallback)")
    print("=" * 70)

    # Check for cached
    cache_path = AUDIO_DIR / f"{SOURCE_VIDEO.stem}_scenes.json"
    if cache_path.is_file():
        print(f"  ✅ Cached scene data found")
        with open(cache_path) as f:
            cuts = json.load(f)
        print(f"  Loaded {len(cuts)} scene cuts from cache")
        return cuts

    t0 = time.time()
    analyzer = VideoAnalyzer()
    cuts = analyzer.detect_scenes(SOURCE_VIDEO)
    elapsed = time.time() - t0
    print(f"  ✅ Detected {len(cuts)} visual scene cuts in {elapsed:.1f}s")

    with open(cache_path, "w") as f:
        json.dump(cuts, f)
    return cuts


def analyze_audio_signals(wav_path):
    """Stage 6: Audio energy analysis."""
    print("\n" + "=" * 70)
    print(" STAGE 6: AUDIO SIGNAL ANALYSIS")
    print("=" * 70)

    cache_path = AUDIO_DIR / f"{SOURCE_VIDEO.stem}_audio_signals.json"
    if cache_path.is_file():
        print(f"  ✅ Cached audio signals found")
        with open(cache_path) as f:
            signals = json.load(f)
        print(f"  {len(signals.get('peak_timestamps', []))} peaks, mean {signals.get('mean_db', 0):.1f}dB")
        return signals

    t0 = time.time()
    analyzer = VideoAnalyzer()
    signals = analyzer.analyze_audio_signals(wav_path)
    elapsed = time.time() - t0
    print(f"  ✅ Analyzed in {elapsed:.1f}s: {len(signals['peak_timestamps'])} peaks, mean {signals['mean_db']:.1f}dB")

    with open(cache_path, "w") as f:
        json.dump(signals, f)
    return signals


def gta6_content_score(text: str) -> float:
    """Score text for GTA 6 relevance (0-100)."""
    text_lower = text.lower()
    hits = sum(1 for kw in GTA6_KEYWORDS if kw in text_lower)
    # Bonus for exciting language
    excitement = sum(1 for c in text if c in "?!") * 5
    return min(100.0, hits * 8.0 + excitement)


def select_best_highlight(meta, segments, audio_signals, scene_cuts):
    """Stage 7: Content-aware GTA 6 highlight selection."""
    print("\n" + "=" * 70)
    print(" STAGE 7: CONTENT-AWARE HIGHLIGHT RANKING")
    print("=" * 70)

    import bisect

    video_duration = meta["duration"]
    all_words = []
    for s in segments:
        all_words.extend(s.get("words", []))
    all_words.sort(key=lambda w: w["start"])
    word_starts = [w["start"] for w in all_words]
    word_ends = sorted(w["end"] for w in all_words)
    peak_times = sorted(set(audio_signals.get("peak_timestamps", [])))

    candidates = []
    step = 1.0  # finer grain for best selection

    curr = 0.0
    while curr + TARGET_DURATION * 0.70 <= video_duration:
        ideal_start = curr
        ideal_end = min(video_duration, curr + TARGET_DURATION)

        # Snap to word boundaries
        snapped_start = ideal_start
        near = bisect.bisect_left(word_starts, ideal_start)
        opts = word_starts[max(0, near - 1):near + 2]
        if opts:
            closest = min(opts, key=lambda t: abs(t - ideal_start))
            if abs(closest - ideal_start) <= 1.5:
                snapped_start = closest

        snapped_end = ideal_end
        near = bisect.bisect_left(word_ends, ideal_end)
        opts = word_ends[max(0, near - 1):near + 2]
        if opts:
            closest = min(opts, key=lambda t: abs(t - ideal_end))
            if abs(closest - ideal_end) <= 2.0:
                snapped_end = closest

        clip_dur = snapped_end - snapped_start
        if clip_dur < TARGET_DURATION * 0.65 or clip_dur > TARGET_DURATION * 1.35:
            curr += step
            continue

        # Words in window
        left = bisect.bisect_left(word_starts, snapped_start)
        right = bisect.bisect_right(word_starts, snapped_end)
        words_in = all_words[left:right]
        window_text = " ".join(w["word"] for w in words_in)

        # Speech density
        wpm = (len(words_in) / (clip_dur / 60.0)) if clip_dur > 0 else 0
        speech_score = min(100.0, (wpm / 140.0) * 100.0) if wpm > 0 else 5.0

        # Audio peaks
        peaks_in = bisect.bisect_right(peak_times, snapped_end) - bisect.bisect_left(peak_times, snapped_start)
        peak_score = min(100.0, (peaks_in / max(1.0, clip_dur / 5.0)) * 50.0)

        # Scene cuts (visual pacing)
        cuts_in = bisect.bisect_right(scene_cuts, snapped_end) - bisect.bisect_left(scene_cuts, snapped_start)
        scene_score = min(100.0, (cuts_in / max(1.0, clip_dur / 6.0)) * 50.0)

        # GTA 6 content relevance
        content_score = gta6_content_score(window_text)

        # Hook strength: first 3 seconds must have words
        hook_words = [w for w in words_in if w["start"] < snapped_start + 3.0]
        hook_score = min(100.0, len(hook_words) * 15.0) if hook_words else 0

        # Boundary penalty
        boundary_penalty = 0.0
        for w in all_words[max(0, left-1):right+1]:
            if w["start"] < snapped_start < w["end"] or w["start"] < snapped_end < w["end"]:
                boundary_penalty += 15.0

        # Composite score with GTA 6 content weighting
        composite = (
            0.20 * speech_score +
            0.15 * peak_score +
            0.10 * scene_score +
            0.30 * content_score +
            0.15 * hook_score -
            boundary_penalty
        )
        composite = round(max(0.0, min(100.0, composite)), 2)

        candidates.append({
            "start": round(snapped_start, 2),
            "end": round(snapped_end, 2),
            "duration": round(clip_dur, 2),
            "score": composite,
            "text": window_text,
            "speech_wpm": round(wpm, 1),
            "cuts": cuts_in,
            "peaks": peaks_in,
            "content_score": round(content_score, 1),
            "hook_score": round(hook_score, 1),
        })
        curr += step

    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Show top 5
    print(f"  Evaluated {len(candidates)} candidate windows")
    print(f"  Top 5 highlights:")
    for i, c in enumerate(candidates[:5]):
        first_words = " ".join(c["text"].split()[:10])
        print(f"    #{i+1} Score={c['score']:.1f} | {c['start']:.1f}s-{c['end']:.1f}s | "
              f"Content={c['content_score']:.0f} Hook={c['hook_score']:.0f} | \"{first_words}...\"")

    best = candidates[0]
    print(f"\n  🏆 SELECTED: {best['start']:.1f}s - {best['end']:.1f}s (Score: {best['score']:.1f})")
    print(f"     Duration: {best['duration']:.1f}s | WPM: {best['speech_wpm']:.0f}")
    print(f"     Content relevance: {best['content_score']:.0f}/100")
    print(f"     First words: \"{' '.join(best['text'].split()[:15])}...\"")
    return best


def render_preview(best, segments):
    """Stage 8: Quick 720p preview."""
    print("\n" + "=" * 70)
    print(" STAGE 8: 720p PREVIEW RENDER")
    print("=" * 70)

    editor = VideoEditor()
    t0 = time.time()
    editor.render_clip(
        source_video=SOURCE_VIDEO,
        start_time=best["start"],
        end_time=best["end"],
        output_path=PREVIEW_OUTPUT,
        aspect_ratio="9:16",
        mode="preview",
        burn_captions=True,
        word_highlight=True,
        transcript_segments=segments,
        style="blur_fill",
        normalize_audio=True,
        color_correction=True,
        zoom_effect=False
    )
    elapsed = time.time() - t0
    size_mb = PREVIEW_OUTPUT.stat().st_size / 1048576
    print(f"  ✅ Preview rendered in {elapsed:.1f}s: {PREVIEW_OUTPUT.name} ({size_mb:.1f} MB)")

    # Quick probe
    r = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(PREVIEW_OUTPUT)],
        capture_output=True, text=True
    )
    info = json.loads(r.stdout)
    vs = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    print(f"  Preview: {vs.get('width')}x{vs.get('height')} @ {vs.get('r_frame_rate')}fps, "
          f"duration={float(info['format']['duration']):.1f}s")
    return PREVIEW_OUTPUT


def render_final(best, segments):
    """Stage 9: Full 1080x1920 final render."""
    print("\n" + "=" * 70)
    print(" STAGE 9: FINAL 1080×1920 RENDER")
    print("=" * 70)

    editor = VideoEditor()
    t0 = time.time()
    editor.render_clip(
        source_video=SOURCE_VIDEO,
        start_time=best["start"],
        end_time=best["end"],
        output_path=FINAL_OUTPUT,
        aspect_ratio="9:16",
        mode="final",
        burn_captions=True,
        word_highlight=True,
        transcript_segments=segments,
        style="blur_fill",
        normalize_audio=True,
        color_correction=True,
        zoom_effect=False
    )
    elapsed = time.time() - t0
    size_mb = FINAL_OUTPUT.stat().st_size / 1048576
    print(f"  ✅ Final rendered in {elapsed:.1f}s: {FINAL_OUTPUT.name} ({size_mb:.1f} MB)")
    return FINAL_OUTPUT, elapsed


def generate_srt(best, segments):
    """Stage 10: Generate SRT file."""
    print("\n" + "=" * 70)
    print(" STAGE 10: SRT SUBTITLE GENERATION")
    print("=" * 70)

    cg = CaptionGenerator()
    cg.generate_srt(
        segments=segments,
        output_path=SRT_OUTPUT,
        clip_start=best["start"],
        clip_end=best["end"]
    )
    lines = SRT_OUTPUT.read_text().count("\n")
    print(f"  ✅ Generated: {SRT_OUTPUT.name} ({lines} lines)")
    return SRT_OUTPUT


def validate_output():
    """Stage 11: Full FFmpeg decode verification."""
    print("\n" + "=" * 70)
    print(" STAGE 11: OUTPUT VALIDATION")
    print("=" * 70)

    if not FINAL_OUTPUT.is_file():
        raise RuntimeError("Final output file missing")

    # FFprobe
    r = subprocess.run(
        [FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(FINAL_OUTPUT)],
        capture_output=True, text=True
    )
    info = json.loads(r.stdout)
    vs = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    au = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    duration = float(info["format"]["duration"])
    size_mb = int(info["format"]["size"]) / 1048576

    print(f"  Video: {vs.get('codec_name')} {vs.get('width')}x{vs.get('height')} @ {vs.get('r_frame_rate')}fps")
    print(f"  Audio: {au.get('codec_name')} {au.get('sample_rate')}Hz {au.get('channels')}ch")
    print(f"  Duration: {duration:.2f}s")
    print(f"  Size: {size_mb:.2f} MB")

    # Full decode test
    r = subprocess.run(
        [FFMPEG_BIN, "-v", "error", "-i", str(FINAL_OUTPUT), "-f", "null", "-"],
        capture_output=True, text=True, timeout=120
    )
    if r.returncode != 0 or r.stderr.strip():
        print(f"  ⚠️ Decode warnings: {r.stderr[:300]}")
    else:
        print(f"  ✅ Full FFmpeg decode test: PASSED (zero errors)")

    result = {
        "codec": vs.get("codec_name"),
        "width": int(vs.get("width", 0)),
        "height": int(vs.get("height", 0)),
        "fps": vs.get("r_frame_rate"),
        "audio_codec": au.get("codec_name"),
        "duration": duration,
        "size_mb": round(size_mb, 2),
        "decode_errors": r.stderr.strip() if r.stderr.strip() else None
    }
    return result


def generate_report(best, meta, validation, render_time, total_time):
    """Stage 12: Generate JSON report."""
    print("\n" + "=" * 70)
    print(" STAGE 12: CLIP REPORT")
    print("=" * 70)

    report = {
        "source": {
            "url": SOURCE_URL,
            "file": str(SOURCE_VIDEO),
            "duration": meta["duration"],
            "resolution": f"{meta['width']}x{meta['height']}",
            "video_codec": meta["video_codec"],
            "audio_codec": meta["audio_codec"],
            "fps": meta["fps"]
        },
        "highlight": {
            "start": best["start"],
            "end": best["end"],
            "duration": best["duration"],
            "score": best["score"],
            "content_score": best.get("content_score", 0),
            "hook_score": best.get("hook_score", 0),
            "speech_wpm": best.get("speech_wpm", 0),
            "scene_cuts": best.get("cuts", 0),
            "audio_peaks": best.get("peaks", 0),
            "first_words": " ".join(best["text"].split()[:20]),
            "reasons": [
                f"Content relevance score: {best.get('content_score', 0)}/100 (GTA 6 keywords detected)",
                f"Hook strength: {best.get('hook_score', 0)}/100 (words in first 3 seconds)",
                f"Speech density: {best.get('speech_wpm', 0)} WPM (engaging pace)",
                f"Visual pacing: {best.get('cuts', 0)} scene cuts",
                f"Audio energy: {best.get('peaks', 0)} volume peaks",
            ]
        },
        "output": {
            "file": str(FINAL_OUTPUT),
            "srt_file": str(SRT_OUTPUT),
            "duration": validation["duration"],
            "resolution": f"{validation['width']}x{validation['height']}",
            "fps": validation["fps"],
            "video_codec": validation["codec"],
            "audio_codec": validation["audio_codec"],
            "size_mb": validation["size_mb"],
            "decode_errors": validation.get("decode_errors")
        },
        "processing": {
            "render_time_seconds": round(render_time, 1),
            "total_time_seconds": round(total_time, 1),
            "encoder": f"{ENCODER_CODEC} preset={ENCODER_PRESET} crf={ENCODER_CRF_FINAL}",
            "cpu_threads": CPU_THREADS,
            "render_threads": RENDER_THREADS,
            "whisper_model": f"{WHISPER_MODEL_NAME} (INT8 CPU)",
        },
        "warnings": []
    }

    if validation.get("decode_errors"):
        report["warnings"].append(f"Decode warnings: {validation['decode_errors']}")

    with open(REPORT_OUTPUT, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"  ✅ Report saved: {REPORT_OUTPUT.name}")
    return report


def main():
    total_t0 = time.time()

    print("\n" + "█" * 70)
    print(" GTA 6 YOUTUBE SHORT — PROFESSIONAL PRODUCTION PIPELINE")
    print(" Source: 100+ Secret Details of GTA 6! — Tech Burner")
    print("█" * 70)

    # Stage 1
    verify_environment()

    # Stage 2
    meta = validate_source()

    # Stage 3
    wav_path = extract_and_cache_audio(meta)

    # Stage 4
    segments = transcribe_speech(wav_path)

    # Stage 5
    scene_cuts = detect_scenes()

    # Stage 6
    audio_signals = analyze_audio_signals(wav_path)

    # Stage 7
    best = select_best_highlight(meta, segments, audio_signals, scene_cuts)

    # Stage 8
    render_preview(best, segments)

    # Stage 9
    final_path, render_time = render_final(best, segments)

    # Stage 10
    generate_srt(best, segments)

    # Stage 11
    validation = validate_output()

    # Stage 12
    total_time = time.time() - total_t0
    report = generate_report(best, meta, validation, render_time, total_time)

    # Final summary
    print("\n" + "█" * 70)
    print(" ✅ PRODUCTION COMPLETE")
    print("█" * 70)
    print(f"  📹 Final Video:  {FINAL_OUTPUT}")
    print(f"  📝 SRT Captions: {SRT_OUTPUT}")
    print(f"  📊 Report:       {REPORT_OUTPUT}")
    print(f"  📐 Resolution:   {validation['width']}x{validation['height']}")
    print(f"  ⏱️  Duration:     {validation['duration']:.1f}s")
    print(f"  📦 Size:         {validation['size_mb']:.1f} MB")
    print(f"  🎬 Clip:         {best['start']:.1f}s - {best['end']:.1f}s")
    print(f"  ⚡ Total Time:   {total_time:.0f}s ({total_time/60:.1f} min)")
    print("█" * 70)


if __name__ == "__main__":
    main()
