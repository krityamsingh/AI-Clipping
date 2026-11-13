"""
End-to-End Pipeline Integration Test
Creates a realistic sample video with speech and visual scenes,
runs the complete autonomous clipping and editing engine,
and verifies output MP4 integrity and playback.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import TESTS_DIR, FFMPEG_BIN, FFPROBE_BIN
from src.tts_generator import TTSGenerator
from src.video_analyzer import VideoAnalyzer
from src.video_editor import VideoEditor


def create_sample_video_with_speech(output_path: Path) -> Path:
    """Generate a 14-second video with scene changes and synthesized speech."""
    output_path = Path(output_path)
    tts_wav = TESTS_DIR / "sample_speech.wav"
    if not tts_wav.is_file():
        tts = TTSGenerator()
        tts.synthesize_sync(
            "Artificial intelligence is transforming how videos are edited and delivered to millions of people worldwide.",
            tts_wav
        )

    # Combine 3 visual patterns with the speech audio
    cmd = [
        FFMPEG_BIN, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=4:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "smptebars=duration=5:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "testsrc=duration=5:size=1280x720:rate=30",
        "-i", str(tts_wav),
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0[vconcat];"
        "[3:a]aloop=loop=-1:size=2e+09,atrim=0:14[aout]",
        "-map", "[vconcat]",
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "128k",
        "-t", "14",
        str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return output_path


def test_full_pipeline_end_to_end():
    print("Generating synthetic full test video... ", end="")
    test_input = TESTS_DIR / "full_sample_input.mp4"
    create_sample_video_with_speech(test_input)
    print(f"PASS ({test_input.stat().st_size} bytes)")

    print("Running VideoAnalyzer (Probe, Audio, Scenes, Peaks, Whisper)... ")
    analyzer = VideoAnalyzer(whisper_model_name="base")
    meta = analyzer.probe_video(test_input)
    assert meta["duration"] >= 10.0, "Video duration invalid"

    wav_path = analyzer.extract_audio(test_input)
    assert wav_path.is_file(), "Audio extraction failed"

    scene_cuts = analyzer.detect_scenes(test_input)
    assert len(scene_cuts) >= 1, "Scene cuts not detected"

    audio_signals = analyzer.analyze_audio_signals(wav_path)
    assert len(audio_signals["rms_timeline"]) > 0, "Audio signals analysis failed"

    segments = analyzer.transcribe_audio(wav_path)
    assert len(segments) > 0, "Transcription segments empty"

    highlights = analyzer.rank_candidate_highlights(
        target_duration=10.0,
        num_clips=1,
        video_metadata=meta,
        segments=segments,
        audio_signals=audio_signals,
        scene_cuts=scene_cuts
    )
    assert len(highlights) > 0, "No highlights returned"
    highlight = highlights[0]
    print(f"PASS (Highlight selected: '{highlight['title']}' [{highlight['start']}s - {highlight['end']}s])")

    print("Running VideoEditor (9:16 Vertical, Blur-fill, Loudnorm, Karaoke Captions)... ")
    editor = VideoEditor()
    rendered_output = TESTS_DIR / "final_test_clip.mp4"

    editor.render_clip(
        source_video=test_input,
        start_time=highlight["start"],
        end_time=highlight["end"],
        output_path=rendered_output,
        aspect_ratio="9:16",
        mode="preview", # 720x1280
        burn_captions=True,
        word_highlight=True,
        transcript_segments=segments,
        style="blur_fill",
        normalize_audio=True,
        color_correction=True,
        zoom_effect=False
    )

    assert rendered_output.is_file(), "Rendered MP4 file does not exist"
    assert rendered_output.stat().st_size > 50000, "Rendered MP4 file is too small"
    print(f"PASS (Rendered: {rendered_output.name}, size: {rendered_output.stat().st_size / 1024:.1f} KB)")

    print("Verifying MP4 stream integrity and playback with FFmpeg decoder... ", end="")
    verify_cmd = [
        FFMPEG_BIN,
        "-v", "error",
        "-i", str(rendered_output),
        "-f", "null", "-"
    ]
    res = subprocess.run(verify_cmd, capture_output=True, text=True)
    assert res.returncode == 0 and len(res.stderr.strip()) == 0, f"MP4 decoding integrity failed: {res.stderr}"
    print("PASS (Zero decoding errors, valid H.264/AAC bitstream)")


if __name__ == "__main__":
    print("--- RUNNING END-TO-END PIPELINE TESTS ---")
    test_full_pipeline_end_to_end()
    print("--- ALL PIPELINE TESTS PASSED ---")
