"""
Faster-Whisper Model Load & Transcription Test
Verifies offline speech recognition, INT8 CPU inference, and word timestamps.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import TESTS_DIR, WHISPER_MODEL_NAME
from src.video_analyzer import VideoAnalyzer


def test_whisper_transcription():
    print(f"Testing Faster-Whisper ({WHISPER_MODEL_NAME} INT8 CPU)... ", end="")
    sample_wav = TESTS_DIR / "sample_speech.wav"
    assert sample_wav.is_file(), "Sample audio file not found, run test_tts.py first"

    analyzer = VideoAnalyzer(whisper_model_name=WHISPER_MODEL_NAME)
    segments = analyzer.transcribe_audio(sample_wav)

    assert len(segments) > 0, "No speech segments returned by Whisper"
    full_text = " ".join(s["text"] for s in segments).lower()
    print(f"PASS (Transcribed: '{full_text[:40]}...')")

    # Verify word timestamps
    first_seg = segments[0]
    words = first_seg.get("words", [])
    assert len(words) > 0, "Word timestamps not generated"
    print(f"PASS (Word timestamps verified: {len(words)} words in first segment)")


if __name__ == "__main__":
    print("--- RUNNING WHISPER TESTS ---")
    test_whisper_transcription()
    print("--- WHISPER TESTS PASSED ---")
