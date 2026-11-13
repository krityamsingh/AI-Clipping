"""
Professional Video Editor & Processing Engine
Handles aspect ratio conversion (9:16 vertical blur-fill, 16:9, 1:1),
audio normalization (loudnorm), dynamic zooms, color correction,
styled subtitle burn-in, and multi-tier rendering (720p preview / 1080p final).
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from config.settings import (
    FFMPEG_BIN,
    FFPROBE_BIN,
    ASPECT_RATIOS,
    ENCODER_CODEC,
    ENCODER_PRESET,
    ENCODER_CRF_FINAL,
    ENCODER_CRF_PREVIEW,
    AUDIO_CODEC,
    AUDIO_BITRATE,
    AUDIO_SAMPLE_RATE,
    CPU_THREADS,
    RENDER_THREADS,
    PREVIEWS_DIR,
    EXPORT_DIR,
    CAPTIONS_DIR
)
from src.caption_generator import CaptionGenerator

logger = logging.getLogger("AI-Clipping.Editor")


class VideoEditor:
    """
    Video rendering and composition engine using FFmpeg and CaptionGenerator.
    """

    def __init__(self, caption_generator: Optional[CaptionGenerator] = None):
        self.caption_generator = caption_generator or CaptionGenerator()

    def build_crop_filter(
        self,
        src_w: int,
        src_h: int,
        target_w: int,
        target_h: int,
        style: str = "blur_fill"
    ) -> str:
        """
        Construct FFmpeg filtergraph for aspect ratio conversion.
        Supported styles:
        - blur_fill: Blurred background with centered sharp foreground (ideal for 16:9 to 9:16 Shorts)
        - center_crop: Crops center to fill target aspect ratio
        - fit_pad: Letterbox/pillarbox padding
        """
        target_aspect = target_w / target_h
        src_aspect = src_w / src_h

        # If aspect ratios are almost identical, simple scale
        if abs(target_aspect - src_aspect) < 0.02:
            return f"scale={target_w}:{target_h}:flags=lanczos"

        if style == "blur_fill":
            # Split input: background is blurred & darkened, foreground is scaled to fit
            filter_graph = (
                f"[0:v]split=2[bg_src][fg_src];"
                f"[bg_src]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h},"
                f"boxblur=luma_radius=min(h\\,w)/15:luma_power=3,"
                f"eq=brightness=-0.12:contrast=0.92[bg];"
                f"[fg_src]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
            )
            return filter_graph

        elif style == "center_crop":
            filter_graph = (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
                f"crop={target_w}:{target_h}"
            )
            return filter_graph

        else: # fit_pad
            filter_graph = (
                f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
            return filter_graph

    def render_clip(
        self,
        source_video: Path,
        start_time: float,
        end_time: float,
        output_path: Path,
        aspect_ratio: str = "9:16",
        mode: str = "final",            # 'final' or 'preview'
        burn_captions: bool = True,
        word_highlight: bool = True,
        transcript_segments: Optional[List[Dict[str, Any]]] = None,
        style: str = "blur_fill",
        normalize_audio: bool = True,
        color_correction: bool = True,
        zoom_effect: bool = False
    ) -> Path:
        """
        Render a single clip from source video with trimming, formatting,
        color grading, audio normalization, and styled subtitle burn-in.
        """
        source_video = Path(source_video)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if not source_video.is_file():
            raise FileNotFoundError(source_video)
        if start_time < 0 or end_time <= start_time:
            raise ValueError("Clip bounds must satisfy 0 <= start_time < end_time")
        if aspect_ratio not in ASPECT_RATIOS or mode not in ("final", "preview"):
            raise ValueError("Unsupported aspect ratio or export mode")
        duration = end_time - start_time

        # Target dimensions
        preset = ASPECT_RATIOS.get(aspect_ratio, ASPECT_RATIOS["9:16"])
        target_w, target_h = preset[mode]

        # Probe source dimensions
        probe_cmd = [
            FFPROBE_BIN, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", str(source_video)
        ]
        probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, text=True)
        if probe_res.returncode != 0:
            raise RuntimeError(f"Cannot probe input: {source_video}")
        p_data = json.loads(probe_res.stdout)
        v_s = next((s for s in p_data.get("streams", []) if s.get("codec_type") == "video"), None)
        if v_s is None:
            raise ValueError("Input is missing a video stream")
        has_audio = any(st.get("codec_type") == "audio" for st in p_data.get("streams", []))
        src_w = int(v_s.get("width", 1920))
        src_h = int(v_s.get("height", 1080))

        # 1. Prepare Subtitle File if requested
        ass_path = None
        if burn_captions and transcript_segments:
            ass_filename = f"{output_path.stem}_subtitles.ass"
            ass_path = CAPTIONS_DIR / ass_filename
            self.caption_generator.generate_styled_ass(
                segments=transcript_segments,
                output_path=ass_path,
                clip_start=start_time,
                clip_end=end_time,
                video_width=target_w,
                video_height=target_h,
                word_level_highlight=word_highlight
            )

        # 2. Build Video Filtergraph
        v_filters = []

        # Aspect ratio conversion & crop
        base_crop_filter = self.build_crop_filter(src_w, src_h, target_w, target_h, style=style)

        # Post-crop effects (color correction, zoom, subtitles)
        post_filters = []

        if color_correction:
            # Subtle punchy contrast and saturation boost
            post_filters.append("eq=contrast=1.05:brightness=0.02:saturation=1.12")

        if zoom_effect:
            # Stable subtle crop instead of multiplying source frames with zoompan.
            post_filters.append(f"crop=iw/1.04:ih/1.04:(iw-ow)/2:(ih-oh)/2,scale={target_w}:{target_h}")

        if ass_path and ass_path.is_file():
            # Escape path for FFmpeg filter syntax
            escaped_ass = str(ass_path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
            post_filters.append(f"ass='{escaped_ass}'")

        # Combine filter graphs
        if style == "blur_fill" and abs(target_w / target_h - src_w / src_h) >= 0.02:
            filter_str = base_crop_filter
            if post_filters:
                filter_str += f"," + ",".join(post_filters)
        else:
            all_v = [base_crop_filter] + post_filters
            filter_str = ",".join(all_v)

        filter_str += "[vout]"

        # 3. Audio Filters (Loudnorm standard)
        a_filters = []
        if normalize_audio:
            # EBU R128 loudness normalization
            a_filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        audio_filter_str = ",".join(a_filters) if a_filters else None

        # 4. Encoding Parameters
        crf = ENCODER_CRF_PREVIEW if mode == "preview" else ENCODER_CRF_FINAL
        preset = "ultrafast" if mode == "preview" else ENCODER_PRESET

        cmd = [
            FFMPEG_BIN, "-y",
            "-threads", str(RENDER_THREADS),
            "-filter_threads", str(RENDER_THREADS),
            "-ss", f"{start_time:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(source_video),
            "-filter_complex", filter_str,
            "-map", "[vout]",
            "-c:v", ENCODER_CODEC,
            "-preset", preset,
            "-crf", str(crf),
            "-threads", str(RENDER_THREADS),
            "-pix_fmt", "yuv420p"
        ]

        if has_audio:
            cmd.extend(["-map", "0:a:0"])
            if audio_filter_str:
                cmd.extend(["-af", audio_filter_str])
            cmd.extend(["-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE,
                        "-ar", str(AUDIO_SAMPLE_RATE)])
        else:
            cmd.append("-an")
        # A unique temporary output prevents exposing broken/partial MP4 files.
        import uuid
        temp_path = output_path.with_name(f".{output_path.stem}.{uuid.uuid4().hex}.partial.mp4")
        cmd.extend(["-movflags", "+faststart", str(temp_path)])

        logger.info("Rendering %s clip: %.2fs - %.2fs", mode, start_time, end_time)
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 text=True, timeout=3600)
            if res.returncode != 0:
                raise RuntimeError(f"Video render failed: {res.stderr[-1200:]}")
            if not temp_path.is_file() or temp_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg returned success without a playable output")
            verify = subprocess.run(
                [FFPROBE_BIN, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name", "-of", "default=nw=1",
                 str(temp_path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if verify.returncode or "codec_name=" not in verify.stdout:
                raise RuntimeError(f"Export verification failed: {verify.stderr[-300:]}")
            temp_path.replace(output_path)
        finally:
            temp_path.unlink(missing_ok=True)

        logger.info("Rendered: %s (%.2f MB)", output_path, output_path.stat().st_size / 1048576)
        return output_path

    def generate_thumbnail(
        self,
        video_path: Path,
        timestamp: float,
        output_image: Path,
        width: int = 720
    ) -> Path:
        """
        Extract high-resolution video thumbnail at given timestamp.
        """
        output_image = Path(output_image)
        output_image.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", f"{timestamp:.3f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", f"scale={width}:-1",
            "-q:v", "2",
            str(output_image)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_image
