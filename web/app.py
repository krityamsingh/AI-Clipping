"""
FastAPI Backend Application for AI Video Clipping Engine
Provides REST API and lightweight UI for automated highlight detection,
editing, style analysis, and export management.
"""

import asyncio
import logging
import os
import shutil
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from config.settings import (
    BASE_DIR,
    RAW_DIR,
    EXPORT_DIR,
    PREVIEWS_DIR,
    STYLE_DIR,
    WHISPER_MODEL_NAME,
    CPU_THREADS,
    MAX_CONCURRENT_JOBS,
    MAX_RENDER_WORKERS
)
from src.video_analyzer import VideoAnalyzer
from src.video_editor import VideoEditor
from src.style_analyzer import StyleAnalyzer
from src.downloader import VideoDownloader

logger = logging.getLogger("AI-Clipping.Web")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Video Clipping Engine", version="1.0.0")

# Mount static and templates
static_dir = BASE_DIR / "web" / "static"
templates_dir = BASE_DIR / "web" / "templates"
static_dir.mkdir(parents=True, exist_ok=True)
templates_dir.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates = Jinja2Templates(directory=str(templates_dir))

# In-memory jobs tracking
jobs: Dict[str, Dict[str, Any]] = {}
job_slots = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)
jobs_lock = threading.RLock()
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB

def allowed_source(source: str) -> Path:
    """Only process files already imported into the local raw/ workspace."""
    path = Path(source).resolve()
    if not path.is_file() or not path.is_relative_to(RAW_DIR.resolve()):
        raise ValueError("Source must be a file inside raw/; upload or download it first")
    return path



class ProcessRequest(BaseModel):
    source: str
    target_duration: float = Field(default=45.0, gt=0, le=600)
    num_clips: int = Field(default=3, ge=1, le=30)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")
    layout_style: str = Field(default="blur_fill", pattern=r"^(blur_fill|center_crop|fit_pad)$")
    export_quality: str = Field(default="final", pattern=r"^(preview|final)$")
    whisper_model: str = Field(default="base", pattern=r"^(tiny|base|small)$")
    burn_captions: bool = True
    word_highlight: bool = True
    normalize_audio: bool = True
    color_correction: bool = True
    zoom_effect: bool = False


class DownloadUrlRequest(BaseModel):
    url: str


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve main web interface."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/health")
async def health_check():
    """System health and hardware status."""
    return {
        "status": "healthy",
        "cpu_cores": os.cpu_count(),
        "cpu_threads_configured": CPU_THREADS,
        "whisper_model": WHISPER_MODEL_NAME,
        "encoder": "libx264 (Tiger Lake optimized)",
        "active_jobs": len([j for j in jobs.values() if j.get("status") == "processing"])
    }


@app.get("/api/raw-videos")
async def list_raw_videos():
    """List available video files in raw/ directory."""
    extensions = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
    videos = []
    for f in RAW_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in extensions:
            videos.append({
                "name": f.name,
                "path": str(f.resolve()),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2)
            })
    videos.sort(key=lambda x: x["name"])
    return {"videos": videos}


@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    """Stream uploads in chunks, enforce a size limit and never trust client paths."""
    import re
    original_name = Path((file.filename or "video.mp4").replace("\\", "/")).name
    ext = Path(original_name).suffix.lower()
    if ext not in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
        raise HTTPException(status_code=415, detail="Unsupported video format")
    basename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(original_name).stem)[:64] or "video"
    safe_filename = f"{basename}_{uuid.uuid4().hex[:12]}{ext}"
    target_path = RAW_DIR / safe_filename
    pending_path = RAW_DIR / f".{safe_filename}.uploading"
    size = 0
    try:
        with pending_path.open("xb") as buffer:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File exceeds 4 GiB limit")
                await run_in_threadpool(buffer.write, chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty upload")
        pending_path.replace(target_path)
    finally:
        pending_path.unlink(missing_ok=True)
        await file.close()
    return {
        "status": "success", "filename": safe_filename,
        "path": str(target_path.resolve()),
        "size_mb": round(size / 1048576, 2)
    }


@app.post("/api/download-url")
async def download_from_url(req: DownloadUrlRequest):
    """Download video from URL (YouTube, TikTok, Reels, etc.) via yt-dlp."""
    downloader = VideoDownloader(download_dir=RAW_DIR)
    try:
        saved_path = await run_in_threadpool(downloader.download_url, req.url)
        return {
            "status": "success",
            "filename": saved_path.name,
            "path": str(saved_path.resolve()),
            "size_mb": round(saved_path.stat().st_size / (1024 * 1024), 2)
        }
    except Exception as e:
        logger.error(f"Download URL failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


def run_pipeline_sync(job_id: str, req_data: Dict[str, Any]):
    """Synchronous background execution of the full clipping engine."""
    job = jobs[job_id]
    job_slots.acquire()
    job["status"] = "processing"
    job["progress"] = 5
    job["current_step"] = "Resolving video source..."

    try:
        source_path = allowed_source(req_data["source"])

        analyzer = VideoAnalyzer(whisper_model_name=req_data.get("whisper_model", "base"))
        editor = VideoEditor()

        # Step 1: Probe metadata
        job["progress"] = 12
        job["current_step"] = "Probing video container and audio streams..."
        meta = analyzer.probe_video(source_path)
        job["log"] = f"Probed: {meta['width']}x{meta['height']} @ {meta['fps']}fps, duration: {meta['duration']}s"

        # Step 2: Audio extraction
        job["progress"] = 25
        job["current_step"] = "Extracting high-fidelity 16kHz speech waveform..."
        if meta["has_audio"]:
            wav_path = analyzer.extract_audio(source_path, output_wav=RAW_DIR / f".{job_id}_audio.wav")
        else:
            wav_path = None

        # Step 3: PySceneDetect Scene cuts
        job["progress"] = 38
        job["current_step"] = "Detecting shot boundaries & visual scene transitions..."
        scene_cuts = analyzer.detect_scenes(source_path)
        job["log"] = f"Detected {len(scene_cuts)} visual scene cuts."

        # Step 4: Audio signal analysis (peaks & silence)
        job["progress"] = 48
        job["current_step"] = "Computing RMS audio energy, peaks, and silence intervals..."
        audio_signals = analyzer.analyze_audio_signals(wav_path) if wav_path else {}

        # Step 5: Speech Recognition (Faster-Whisper INT8)
        job["progress"] = 62
        job["current_step"] = f"Transcribing speech with Faster-Whisper ({req_data.get('whisper_model', 'base')} INT8)..."
        segments = analyzer.transcribe_audio(wav_path) if wav_path else []
        job["log"] = f"Transcribed {len(segments)} spoken segments."

        # Step 6: Highlight Ranking & Boundary Snapping
        job["progress"] = 72
        job["current_step"] = "Ranking highlights (speech density + audio peaks + scene cuts)..."
        candidate_clips = analyzer.rank_candidate_highlights(
            target_duration=req_data["target_duration"],
            num_clips=req_data["num_clips"],
            video_metadata=meta,
            segments=segments,
            audio_signals=audio_signals,
            scene_cuts=scene_cuts
        )

        # Step 7: Render clips
        job["progress"] = 80
        rendered_clips = []
        out_dir = EXPORT_DIR if req_data["export_quality"] == "final" else PREVIEWS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        if not candidate_clips:
            raise RuntimeError("No valid highlights were found; try a shorter duration")

        def render_one(i, clip):
            # Each render has its own file and subtitle path; FFmpeg threads are bounded.
            clip_filename = f"clip_{job_id}_{i+1}_{req_data['export_quality']}.mp4"
            clip_out = out_dir / clip_filename
            editor.render_clip(
                source_video=source_path, start_time=clip["start"],
                end_time=clip["end"], output_path=clip_out,
                aspect_ratio=req_data["aspect_ratio"],
                mode=req_data["export_quality"],
                burn_captions=req_data["burn_captions"],
                word_highlight=req_data["word_highlight"],
                transcript_segments=segments,
                style=req_data["layout_style"],
                normalize_audio=req_data["normalize_audio"],
                color_correction=req_data["color_correction"],
                zoom_effect=req_data["zoom_effect"]
            )
            url_path = f"/media/{'export' if req_data['export_quality'] == 'final' else 'previews'}/{clip_filename}"
            return {
                "index": i + 1, "title": clip["title"],
                "score": clip.get("score", 0),
                "explanation": clip.get("explanation", ""),
                "start": clip["start"], "end": clip["end"],
                "duration": clip["duration"],
                "aspect_ratio": req_data["aspect_ratio"],
                "filename": clip_filename,
                "size_mb": round(clip_out.stat().st_size / 1048576, 2),
                "url": url_path, "download_url": url_path,
                "text": clip.get("text", "")
            }

        worker_count = min(MAX_RENDER_WORKERS, len(candidate_clips))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(render_one, i, clip): i
                       for i, clip in enumerate(candidate_clips)}
            for future in as_completed(futures):
                rendered_clips.append(future.result())
                finished = len(rendered_clips)
                job["progress"] = 80 + int(finished / len(candidate_clips) * 18)
                job["current_step"] = f"Rendered {finished} of {len(candidate_clips)} clips..."
        rendered_clips.sort(key=lambda item: item["index"])

        # Finish Job
        job["progress"] = 100
        job["status"] = "completed"
        job["current_step"] = "Completed successfully!"
        job["details"] = f"Rendered {len(rendered_clips)} clips."
        job["clips"] = rendered_clips

    except Exception as e:
        logger.exception("Pipeline failed")
        job["status"] = "failed"
        job["error"] = str(e)
        job["current_step"] = "Error encountered"
    finally:
        (RAW_DIR / f".{job_id}_audio.wav").unlink(missing_ok=True)
        job_slots.release()


@app.post("/api/process")
async def start_process(req: ProcessRequest, background_tasks: BackgroundTasks):
    """Trigger background highlight clipping process."""
    try:
        allowed_source(req.source)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = uuid.uuid4().hex
    jobs[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "progress": 0,
        "current_step": "Queued",
        "details": "",
        "log": "",
        "clips": [],
        "created_at": time.time()
    }
    background_tasks.add_task(run_pipeline_sync, job_id, req.model_dump())
    return {"status": "queued", "job_id": job_id}


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Get real-time job status, progress percentage, and results."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/exports")
async def list_exports():
    """List all available generated clips in export/ and previews/."""
    clips = []
    for d, category in [(EXPORT_DIR, "final"), (PREVIEWS_DIR, "preview")]:
        for f in d.glob("*.mp4"):
            clips.append({
                "filename": f.name,
                "title": f.stem.replace("_", " ").title(),
                "duration": "N/A",
                "start": 0,
                "end": 0,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "url": f"/media/{'export' if category == 'final' else 'previews'}/{f.name}",
                "download_url": f"/media/{'export' if category == 'final' else 'previews'}/{f.name}",
                "score": 92,
                "aspect_ratio": "9:16",
                "explanation": f"Saved export ({category})"
            })
    clips.sort(key=lambda x: x["filename"], reverse=True)
    return {"clips": clips}


@app.post("/api/analyze-style")
async def analyze_style():
    """Analyze reference reels in style/ and update STYLE.md."""
    analyzer = StyleAnalyzer()
    report_path = analyzer.generate_style_report()
    content = report_path.read_text(encoding="utf-8")
    return {"status": "success", "markdown": content}


@app.get("/media/export/{filename}")
async def serve_export_file(filename: str):
    path = EXPORT_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), media_type="video/mp4")


@app.get("/media/previews/{filename}")
async def serve_preview_file(filename: str):
    path = PREVIEWS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), media_type="video/mp4")
