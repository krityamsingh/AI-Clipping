"""
Edge-TTS AI Voiceover Generator
Generates high quality, natural AI speech for introductions, hooks, and voiceovers.
"""

import asyncio
from pathlib import Path
from typing import Optional, List, Dict
import subprocess

from config.settings import AUDIO_DIR, FFMPEG_BIN


DEFAULT_VOICES = [
    {"name": "en-US-ChristopherNeural", "gender": "Male", "description": "Authoritative, Clear (US)"},
    {"name": "en-US-JennyNeural", "gender": "Female", "description": "Warm, Engaging (US)"},
    {"name": "en-US-GuyNeural", "gender": "Male", "description": "Casual, Conversational (US)"},
    {"name": "en-GB-RyanNeural", "gender": "Male", "description": "Articulate, British"},
]


class TTSGenerator:
    """
    Asynchronous Edge-TTS voice synthesis engine.
    """

    def __init__(self, default_voice: str = "en-US-ChristopherNeural"):
        self.default_voice = default_voice

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: Optional[str] = None,
        rate: str = "+0%",
        pitch: str = "+0Hz"
    ) -> Path:
        """
        Synthesize text to an audio file (mp3 or wav).
        """
        try:
            import edge_tts
        except ImportError:
            raise RuntimeError("edge-tts is not installed in the environment.")

        selected_voice = voice or self.default_voice
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        communicate = edge_tts.Communicate(
            text=text,
            voice=selected_voice,
            rate=rate,
            pitch=pitch
        )

        temp_mp3 = output_path.with_suffix(".temp.mp3")
        await communicate.save(str(temp_mp3))

        # Convert to target format (e.g. wav or standard 44.1kHz mp3) using ffmpeg
        if output_path.suffix.lower() == ".wav":
            cmd = [
                FFMPEG_BIN, "-y",
                "-i", str(temp_mp3),
                "-ar", "44100",
                "-ac", "2",
                str(output_path)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            if temp_mp3.exists():
                temp_mp3.unlink()
        else:
            temp_mp3.replace(output_path)

        return output_path

    def synthesize_sync(
        self,
        text: str,
        output_path: Path,
        voice: Optional[str] = None,
        rate: str = "+0%",
        pitch: str = "+0Hz"
    ) -> Path:
        """Synchronous wrapper for synthesize"""
        return asyncio.run(self.synthesize(text, output_path, voice, rate, pitch))
