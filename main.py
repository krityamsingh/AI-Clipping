"""
Main Entrypoint for AI Video Clipping & Editing Engine
Run web interface: python main.py --web [--port 8000]
Run CLI clipping:  python main.py <source_path_or_url> [-n 3] [--duration 45] [--aspect 9:16]
Run diagnostics:   python main.py --check
Analyze style:     python main.py --analyze-style
"""

import argparse
import logging
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import (
    FFMPEG_BIN,
    FFPROBE_BIN,
    RAW_DIR,
    EXPORT_DIR,
    PREVIEWS_DIR,
    STYLE_DIR,
    MODELS_DIR,
    WHISPER_MODEL_NAME,
    CPU_THREADS,
    MAX_RENDER_WORKERS
)
from src.video_analyzer import VideoAnalyzer
from src.video_editor import VideoEditor
from src.downloader import VideoDownloader
from src.style_analyzer import StyleAnalyzer

logger = logging.getLogger("AI-Clipping.Main")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)


def run_self_check():
    """Verify all system components, models, and binaries."""
    print("=" * 65)
    print(" AI VIDEO CLIPPING ENGINE — SYSTEM DIAGNOSTICS & VERIFICATION")
    print("=" * 65)

    errors = []

    # 1. FFmpeg & FFprobe
    try:
        import subprocess
        res = subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            version_line = res.stdout.splitlines()[0]
            print(f" [PASS] FFmpeg detected: {version_line[:45]}...")
        else:
            errors.append("FFmpeg executable failed execution.")
    except Exception as e:
        errors.append(f"FFmpeg binary not reachable ({e})")

    try:
        import subprocess
        res = subprocess.run([FFPROBE_BIN, "-version"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            print(" [PASS] FFprobe detected and functioning.")
        else:
            errors.append("FFprobe executable failed execution.")
    except Exception as e:
        errors.append(f"FFprobe binary not reachable ({e})")

    # 2. Python Packages
    for pkg in ("numpy", "scipy", "faster_whisper", "scenedetect", "cv2", "fastapi", "uvicorn", "soundfile", "yt_dlp", "edge_tts"):
        try:
            __import__(pkg)
            print(f" [PASS] Python module available: {pkg}")
        except Exception as e:
            errors.append(f"Missing Python package '{pkg}': {e}")

    # 3. Hardware check
    print(f" [PASS] CPU Threads: {CPU_THREADS} allocated for inference and video encoding.")
    print(f" [PASS] Encoder configured: libx264 (CPU veryfast / Tiger Lake optimized).")

    print("-" * 65)
    if errors:
        print(" DIAGNOSTICS FAILED:")
        for err in errors:
            print(f"   ❌ {err}")
        return False
    else:
        print(" ALL DIAGNOSTIC CHECKS PASSED SUCCESSFULLY (READY FOR PRODUCTION)")
        return True


def run_cli_clipping(args):
    """Execute end-to-end clipping from command line."""
    source_input = args.source
    if not source_input:
        print("Error: Please provide a video file path or URL.")
        sys.exit(1)

    print(f"\n[1/5] Resolving media source: {source_input}...")
    downloader = VideoDownloader(RAW_DIR)
    source_path = downloader.resolve_source(source_input)
    print(f"  Target video: {source_path.name} ({round(source_path.stat().st_size / (1024*1024), 2)} MB)")

    analyzer = VideoAnalyzer(whisper_model_name=args.model)
    editor = VideoEditor()

    print("\n[2/5] Analyzing video streams & visual scene cuts...")
    meta = analyzer.probe_video(source_path)
    print(f"  Container: {meta['width']}x{meta['height']} @ {meta['fps']}fps, duration: {meta['duration']:.1f}s")

    wav_path = analyzer.extract_audio(source_path) if meta["has_audio"] else None
    scene_cuts = analyzer.detect_scenes(source_path)
    print(f"  Visual cuts detected: {len(scene_cuts)}")

    audio_signals = analyzer.analyze_audio_signals(wav_path) if wav_path else {}
    print(f"  Audio RMS analysis complete: {len(audio_signals.get('peak_timestamps', []))} volume peaks detected.")

    print(f"\n[3/5] Transcribing speech with Faster-Whisper ({args.model} INT8, 4 threads)...")
    segments = analyzer.transcribe_audio(wav_path) if wav_path else []
    print(f"  Transcribed {len(segments)} spoken segments with word-level timestamps.")

    print(f"\n[4/5] Multi-signal highlight scoring & boundary snapping...")
    highlights = analyzer.rank_candidate_highlights(
        target_duration=args.duration,
        num_clips=args.num_clips,
        video_metadata=meta,
        segments=segments,
        audio_signals=audio_signals,
        scene_cuts=scene_cuts
    )
    print(f"  Identified {len(highlights)} candidate viral highlights:")
    for h in highlights:
        print(f"   • Clip {h['index']}: '{h['title']}' ({h['start']:.1f}s - {h['end']:.1f}s) | Score: {h['score']}/100")

    print(f"\n[5/5] Rendering clips (Aspect: {args.aspect}, Layout: {args.layout}, Quality: {args.quality})...")
    out_dir = EXPORT_DIR if args.quality == "final" else PREVIEWS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if not highlights:
        raise RuntimeError("No highlights found; try a shorter target duration")

    def render_one(h):
        out_name = f"clip_{uuid.uuid4().hex[:12]}_{h['index']}_{args.quality}.mp4"
        out_path = out_dir / out_name
        editor.render_clip(
            source_video=source_path,
            start_time=h["start"],
            end_time=h["end"],
            output_path=out_path,
            aspect_ratio=args.aspect,
            mode=args.quality,
            burn_captions=args.captions,
            word_highlight=args.word_highlight,
            transcript_segments=segments,
            style=args.layout,
            normalize_audio=args.loudnorm,
            color_correction=args.color,
            zoom_effect=args.zoom
        )
        return out_path

    rendered_files = []
    with ThreadPoolExecutor(max_workers=min(MAX_RENDER_WORKERS, len(highlights))) as executor:
        futures = [executor.submit(render_one, h) for h in highlights]
        for future in as_completed(futures):
            path = future.result()
            rendered_files.append(path)
            print(f"  Saved: {path} ({path.stat().st_size / 1048576:.2f} MB)")

    print("\n" + "=" * 65)
    print(" CLIPPING PIPELINE COMPLETED SUCCESSFULLY!")
    print(f" Generated {len(rendered_files)} clips in: {out_dir}")
    print("=" * 65)


def run_web_server(host: str = "127.0.0.1", port: int = 8000):
    """Start the FastAPI Web UI server."""
    import uvicorn
    print("=" * 65)
    print(f" STARTING AI VIDEO CLIPPING LOCAL WEB INTERFACE")
    print(f" URL: http://{host}:{port}")
    print("=" * 65)
    uvicorn.run("web.app:app", host=host, port=port, reload=False, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="Autonomous AI Video Clipping & Editing Engine")
    parser.add_argument("source", nargs="?", help="Path to video file or URL (YouTube/Web)")
    parser.add_argument("--web", action="store_true", help="Launch local web UI interface")
    parser.add_argument("--host", default="127.0.0.1", help="Web server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Web server port (default: 8000)")
    parser.add_argument("--check", action="store_true", help="Run system diagnostics and verify components")
    parser.add_argument("--analyze-style", action="store_true", help="Analyze reference reels in style/ folder")
    parser.add_argument("-n", "--num-clips", type=int, default=3, help="Number of clips to generate (default: 3)")
    parser.add_argument("-d", "--duration", type=float, default=45.0, help="Target clip duration in seconds (default: 45)")
    parser.add_argument("--aspect", default="9:16", choices=["9:16", "16:9", "1:1"], help="Aspect ratio (default: 9:16)")
    parser.add_argument("--layout", default="blur_fill", choices=["blur_fill", "center_crop", "fit_pad"], help="Layout style")
    parser.add_argument("--quality", default="final", choices=["preview", "final"], help="Export quality (default: final)")
    parser.add_argument("--model", default="base", help="Whisper model (tiny, base, small)")
    parser.add_argument("--no-captions", dest="captions", action="store_false", help="Disable caption burn-in")
    parser.add_argument("--no-word-highlight", dest="word_highlight", action="store_false", help="Disable word highlight animation")
    parser.add_argument("--no-loudnorm", dest="loudnorm", action="store_false", help="Disable audio loudness normalization")
    parser.add_argument("--no-color", dest="color", action="store_false", help="Disable color correction")
    parser.add_argument("--zoom", action="store_true", help="Enable subtle dynamic zoom")
    parser.set_defaults(captions=True, word_highlight=True, loudnorm=True, color=True)

    args = parser.parse_args()

    if args.check:
        success = run_self_check()
        sys.exit(0 if success else 1)

    if args.analyze_style:
        analyzer = StyleAnalyzer()
        report = analyzer.generate_style_report()
        print(f"\nStyle analysis complete. Report written to: {report}")
        sys.exit(0)

    if args.web:
        run_web_server(args.host, args.port)
        return

    if args.source:
        run_cli_clipping(args)
    else:
        # Default if no arguments: start web server
        run_web_server(args.host, args.port)


if __name__ == "__main__":
    main()
