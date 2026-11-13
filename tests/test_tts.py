"""
Edge-TTS Functionality Test
Verifies voice synthesis with network connectivity.
"""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import TESTS_DIR
from src.tts_generator import TTSGenerator


def test_edge_tts_synthesis():
    print("Testing Edge-TTS voice synthesis... ", end="")
    generator = TTSGenerator(default_voice="en-US-ChristopherNeural")
    test_output = TESTS_DIR / "sample_speech.wav"

    sample_text = "Welcome to the autonomous AI video clipping and highlight detection engine."
    result_path = generator.synthesize_sync(sample_text, test_output)

    assert result_path.is_file(), "TTS output file not created"
    assert result_path.stat().st_size > 1000, "TTS output file is empty"
    print(f"PASS (Generated {result_path.stat().st_size} bytes speech audio)")


if __name__ == "__main__":
    print("--- RUNNING TTS TESTS ---")
    test_edge_tts_synthesis()
    print("--- TTS TESTS PASSED ---")
