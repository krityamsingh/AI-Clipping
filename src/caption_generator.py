"""
Subtitle and Caption Generator
Generates SRT, VTT, and styled ASS subtitles with word-level highlight animation.
Optimized for 9:16 Shorts/Reels/TikTok and 16:9 Landscape videos.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import math


def format_timestamp_srt(seconds: float) -> str:
    """Format seconds into SRT timestamp HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def format_timestamp_vtt(seconds: float) -> str:
    """Format seconds into VTT timestamp HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis = 999
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_timestamp_ass(seconds: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cc (centiseconds)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours:01d}:{minutes:02d}:{secs:02d}.{centis:02d}"


class CaptionGenerator:
    """
    Transforms word and segment timestamps into SRT, VTT, and animated ASS captions.
    """

    def __init__(
        self,
        font_name: str = "DejaVu Sans",
        font_size: int = 48,
        primary_color: str = "&H00FFFFFF",      # White (AABBGGRR)
        highlight_color: str = "&H0000FFFF",    # Bright Yellow
        outline_color: str = "&H00000000",      # Black outline
        outline_width: float = 3.5,
        shadow_width: float = 1.5,
        alignment: int = 2,                     # 2 = Bottom-Center
        margin_v: int = 180,                    # Vertical margin
        max_words_per_group: int = 4
    ):
        self.font_name = font_name
        self.font_size = font_size
        self.primary_color = primary_color
        self.highlight_color = highlight_color
        self.outline_color = outline_color
        self.outline_width = outline_width
        self.shadow_width = shadow_width
        self.alignment = alignment
        self.margin_v = margin_v
        self.max_words_per_group = max_words_per_group

    def generate_srt(
        self,
        segments: List[Dict[str, Any]],
        output_path: Path,
        clip_start: float = 0.0,
        clip_end: Optional[float] = None
    ) -> Path:
        """
        Generate SubRip (.srt) subtitle file relative to clip start.
        """
        lines = []
        index = 1

        for seg in segments:
            start = seg["start"] - clip_start
            end = seg["end"] - clip_start

            if clip_end is not None and start >= (clip_end - clip_start):
                break
            if end <= 0:
                continue

            start = max(0.0, start)
            if clip_end is not None:
                end = min(end, clip_end - clip_start)

            text = seg.get("text", "").strip()
            if end <= start or not text:
                continue

            lines.append(f"{index}")
            lines.append(f"{format_timestamp_srt(start)} --> {format_timestamp_srt(end)}")
            lines.append(f"{text}\n")
            index += 1

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    def generate_vtt(
        self,
        segments: List[Dict[str, Any]],
        output_path: Path,
        clip_start: float = 0.0,
        clip_end: Optional[float] = None
    ) -> Path:
        """
        Generate WebVTT (.vtt) subtitle file relative to clip start.
        """
        lines = ["WEBVTT\n"]
        index = 1

        for seg in segments:
            start = seg["start"] - clip_start
            end = seg["end"] - clip_start

            if clip_end is not None and start >= (clip_end - clip_start):
                break
            if end <= 0:
                continue

            start = max(0.0, start)
            if clip_end is not None:
                end = min(end, clip_end - clip_start)

            text = seg.get("text", "").strip()
            if end <= start or not text:
                continue

            lines.append(f"{index}")
            lines.append(f"{format_timestamp_vtt(start)} --> {format_timestamp_vtt(end)}")
            lines.append(f"{text}\n")
            index += 1

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    def generate_styled_ass(
        self,
        segments: List[Dict[str, Any]],
        output_path: Path,
        clip_start: float = 0.0,
        clip_end: Optional[float] = None,
        video_width: int = 1080,
        video_height: int = 1920,
        word_level_highlight: bool = True
    ) -> Path:
        """
        Generate ASS subtitle file with high-impact typography and word-by-word active highlighting.
        """
        # Dynamic font sizing based on resolution
        scale = video_height / 1920.0
        scaled_font_size = max(24, int(self.font_size * scale))
        scaled_margin_v = max(40, int(self.margin_v * scale))
        scaled_outline = max(1.5, self.outline_width * scale)

        # Script-aware font selection: fallback to FreeSans for Indic / non-Latin Unicode scripts
        full_text = " ".join(s.get("text", "") for s in segments)
        font_to_use = self.font_name
        if any(0x0900 <= ord(c) <= 0x0D7F for c in full_text):
            font_to_use = "FreeSans"

        ass_header = f"""[Script Info]
Title: AI Clipping Styled Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: {video_width}
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_to_use},{scaled_font_size},{self.primary_color},&H000000FF,{self.outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{scaled_outline:.1f},{self.shadow_width:.1f},{self.alignment},30,30,{scaled_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines = []

        all_words = []
        for seg in segments:
            seg_words = seg.get("words", [])
            if seg_words:
                all_words.extend(seg_words)
            else:
                # Fallback if segment lacks word timestamps: split words evenly
                seg_text = seg.get("text", "").strip()
                tokens = seg_text.split()
                if not tokens:
                    continue
                seg_dur = max(0.3, seg["end"] - seg["start"])
                word_dur = seg_dur / len(tokens)
                for idx, token in enumerate(tokens):
                    w_start = seg["start"] + idx * word_dur
                    w_end = w_start + word_dur
                    all_words.append({
                        "word": token,
                        "start": w_start,
                        "end": w_end
                    })

        # Filter words to the clip boundary
        clip_duration = (clip_end - clip_start) if clip_end else None
        valid_words = []
        for w in all_words:
            w_start = w["start"] - clip_start
            w_end = w["end"] - clip_start
            if clip_duration is not None and w_start >= clip_duration:
                continue
            if w_end <= 0:
                continue
            valid_words.append({
                "word": w["word"].strip(),
                "start": max(0.0, w_start),
                "end": min(w_end, clip_duration) if clip_duration else w_end
            })

        if not valid_words:
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(ass_header, encoding="utf-8")
            return output_path

        # Group words into short 2-4 word punchy phrases
        groups = []
        curr_group = []
        for w in valid_words:
            if curr_group and w["start"] - curr_group[-1]["end"] > 0.48:
                groups.append(curr_group)
                curr_group = []
            curr_group.append(w)
            # Break group if max words reached or there is a natural pause (> 0.4s)
            if len(curr_group) >= self.max_words_per_group or w["word"].endswith((".", "!", "?", ",")):
                groups.append(curr_group)
                curr_group = []
            elif len(groups) > 0 and (w["end"] - w["start"] > 1.2):
                groups.append(curr_group)
                curr_group = []

        if curr_group:
            groups.append(curr_group)

        # Generate dialogue events for each group
        for group in groups:
            g_start = group[0]["start"]
            g_end = group[-1]["end"]
            if g_end <= g_start:
                g_end = g_start + 0.3

            if word_level_highlight:
                # Active highlight effect: highlight current active word with color & scale
                for i, active_word in enumerate(group):
                    w_sub_start = active_word["start"]
                    w_sub_end = active_word["end"]
                    if w_sub_end <= w_sub_start:
                        w_sub_end = w_sub_start + 0.15

                    formatted_words = []
                    for j, item in enumerate(group):
                        token = item["word"].upper()
                        if j == i:
                            # Highlighted word: change color, slight scale up
                            formatted_words.append(r"{\c" + self.highlight_color + r"\fscx108\fscy108}" + token + r"{\r}")
                        else:
                            formatted_words.append(token)

                    text_payload = " ".join(formatted_words)
                    ass_line = (
                        f"Dialogue: 0,{format_timestamp_ass(w_sub_start)},"
                        f"{format_timestamp_ass(w_sub_end)},Default,,0,0,0,,{text_payload}"
                    )
                    dialogue_lines.append(ass_line)
            else:
                # Standard segment display without karaoke
                text_payload = " ".join([w["word"].upper() for w in group])
                ass_line = (
                    f"Dialogue: 0,{format_timestamp_ass(g_start)},"
                    f"{format_timestamp_ass(g_end)},Default,,0,0,0,,{text_payload}"
                )
                dialogue_lines.append(ass_line)

        full_ass = ass_header + "\n".join(dialogue_lines) + "\n"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(full_ass, encoding="utf-8")
        return output_path
