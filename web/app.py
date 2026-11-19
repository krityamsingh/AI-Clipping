"""
FastAPI Backend Application for AI Video Clipping Engine
Provides REST API and lightweight UI for automated highlight detection,
editing, style analysis, and export management.
"""

import asyncio
import logging
import re
import os
import shutil
import time
import uuid
import threading
from contextlib import asynccontextmanager
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

live_sessions = {}
live_sessions_lock = threading.Lock()


@asynccontextmanager
async def lifespan(application):
    yield
    with live_sessions_lock:
        sessions = list(live_sessions.values())
    for session in sessions:
        session["watcher"].stop()
    for session in sessions:
        await run_in_threadpool(session["thread"].join)


app = FastAPI(title="AI Video Clipping Engine", version="1.0.0", lifespan=lifespan)

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
        job["current_step"] = "Ranking transcript-grounded highlights with visual/audio evidence..."
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
                "score": None,
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


# ---------------------------------------------------------------------------
# Model-neutral editing agent API. The web server is local-only by default.
# ---------------------------------------------------------------------------
from src.agent_workflow import analyze_source, build_auto_plan, validate_plan
from src.render_plan import render_plan
from src.clip_profiles import PROFILES, EDIT_STYLES


class AgentAnalyzeRequest(BaseModel):
    source: str
    model: str = Field(default="base", pattern=r"^(tiny|base|small|medium)$")
    target_duration: float = Field(default=45.0, gt=5, le=600)
    vocabulary: List[str] = Field(default_factory=list)
    profile: str = "general"
    chat_log: Optional[str] = None
    signals_only: bool = False


class AgentPlanRequest(BaseModel):
    analysis: Dict[str, Any]
    profile: str = "general"
    edit_style: Optional[str] = None
    target_duration: float = Field(default=45, ge=5, le=600)
    parts: Optional[int] = Field(default=None, ge=1, le=100)
    aspect_ratio: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")
    quality: str = Field(default="final", pattern=r"^(final|preview)$")


class AgentRenderRequest(BaseModel):
    plan: Dict[str, Any]


@app.get("/api/agent/spec")
async def agent_spec():
    """Discover tools and EDL semantics without model-specific SDKs."""
    return {
        "api_version": 1,
        "documentation": "AGENTS.md",
        "profiles": list(PROFILES),
        "editing_styles": list(EDIT_STYLES),
        "operations": {
            "analyze": "POST /api/agent/analyze, then GET /api/status/{job_id}",
            "livestream": "POST /api/live/start; GET /api/live/{session_id}; POST /api/live/{session_id}/stop",
            "plan": "POST /api/agent/plan with analysis JSON",
            "render": "POST /api/agent/render with edited plan JSON, then GET /api/status/{job_id}",
            "download": "GET /api/agent/media/{job_id}/{filename}"
        },
        "edit_plan_fields": {
            "version": 1, "source": "path in raw/",
            "profile": "podcast", "settings": {"aspect_ratio": "9:16", "quality": "final",
                                               "edit_style": "podcast",
                                               "captions": True, "word_highlight": True},
            "caption_corrections": {"observed incorrect phrase": "verified corrected phrase"},
            "transcript": [{"start": 0, "end": 1, "text": "verified words", "words": []}],
            "parts": [{"part": 1, "title": "observed title", "title_card": "PART 1",
                       "shots": [{"shot_id": "first", "source_start": 0.5,
                                  "source_end": 10.0, "layout": "blur_fill"}]}]
        }
    }


def _agent_analyze_job(job_id, data):
    job_slots.acquire()
    job = jobs[job_id]
    job["status"] = "processing"
    job["progress"] = 10
    job["current_step"] = "Analyzing source and checking captions..."
    try:
        report = analyze_source(
            data["source"], model=data.get("model", "base"),
            target_duration=data.get("target_duration", 45),
            vocabulary=data.get("vocabulary") or [],
            profile=data.get("profile", "general"),
            chat_log=data.get("chat_log"), signals_only=bool(data.get("signals_only", False)))
        job["analysis_report"] = report
        job.update(status="completed", progress=100,
                   current_step="Analysis complete",
                   details="Use analysis_report in POST /api/agent/plan")
    except Exception as exc:
        logger.exception("Agent analysis failed")
        job.update(status="failed", current_step="Analysis failed", error=str(exc))
    finally:
        job_slots.release()


@app.post("/api/agent/analyze")
async def start_agent_analysis(req: AgentAnalyzeRequest, background_tasks: BackgroundTasks):
    try:
        source = allowed_source(req.source)
        if req.profile not in PROFILES:
            raise ValueError("Unsupported video profile")
        if req.chat_log:
            allowed_source(req.chat_log)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"job_id": job_id, "status": "queued", "progress": 0,
                    "current_step": "Queued for analysis", "clips": [],
                    "created_at": time.time()}
    payload = req.model_dump()
    payload["source"] = str(source)
    if payload.get("chat_log"):
        payload["chat_log"] = str(allowed_source(payload["chat_log"]))
    background_tasks.add_task(_agent_analyze_job, job_id, payload)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/agent/plan")
async def make_agent_plan(req: AgentPlanRequest):
    try:
        allowed_source(str(req.analysis.get("source") or ""))
        if req.profile not in PROFILES:
            raise ValueError("Unsupported video profile")
        if req.edit_style is not None and req.edit_style not in EDIT_STYLES:
            raise ValueError("Unsupported editing style")
        plan = await run_in_threadpool(
            build_auto_plan, req.analysis, profile=req.profile,
            target_duration=req.target_duration, max_parts=req.parts,
            aspect_ratio=req.aspect_ratio, quality=req.quality,
            edit_style=req.edit_style)
        return {"status": "planned", "plan": plan}
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _agent_render_job(job_id, plan):
    job_slots.acquire()
    job = jobs[job_id]
    job["status"] = "processing"
    job["progress"] = 10
    job["current_step"] = "Rendering agent-selected shots..."
    try:
        result = render_plan(plan, output_dir=EXPORT_DIR / job_id)
        for part in result["parts"]:
            number = part["part"]
            part["url"] = "/api/agent/media/%s/Part_%02d.mp4" % (job_id, number)
            part["srt_url"] = "/api/agent/media/%s/Part_%02d.srt" % (job_id, number)
        job.update(status="completed", progress=100, current_step="Render validated",
                   result=result, parts=result["parts"])
    except Exception as exc:
        logger.exception("Agent render failed")
        job.update(status="failed", current_step="Render failed", error=str(exc))
    finally:
        job_slots.release()


@app.post("/api/agent/render")
async def start_agent_render(req: AgentRenderRequest, background_tasks: BackgroundTasks):
    try:
        allowed_source(str(req.plan.get("source") or ""))
        validate_plan(req.plan)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"job_id": job_id, "status": "queued", "progress": 0,
                    "current_step": "Queued for agent edit render", "clips": [],
                    "created_at": time.time()}
    background_tasks.add_task(_agent_render_job, job_id, req.plan)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/agent/media/{job_id}/{filename}")
async def agent_download(job_id: str, filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise HTTPException(status_code=404, detail="Not found")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", filename):
        raise HTTPException(status_code=404, detail="Not found")
    if filename.endswith(".mp4"):
        media_type = "video/mp4"
    elif filename.endswith(".srt"):
        media_type = "text/plain"
    elif filename.endswith((".ass", ".json")):
        media_type = "text/plain"
    else:
        raise HTTPException(status_code=404, detail="Unsupported extension")
    if job_id not in jobs or jobs[job_id].get("status") != "completed":
        raise HTTPException(status_code=404, detail="Not found")
    path = EXPORT_DIR / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type=media_type)


# Continuous capture runs independently from the serialized ASR/render job slot.
from src.live_watcher import LiveWatcher, WatchConfig


class LiveStartRequest(BaseModel):
    url: str
    twitch_channel: str = ""
    chat_offset: float = Field(default=0, ge=-300, le=300)
    chunk_seconds: float = Field(default=60, ge=10, le=300)
    duration: float = Field(default=45, ge=5, le=120)
    min_score: float = Field(default=35, ge=0, le=100)
    clips_per_window: int = Field(default=1, ge=1, le=5)
    model: str = Field(default="small", pattern=r"^(tiny|base|small|medium)$")
    vocabulary: List[str] = Field(default_factory=list)
    signals_only: bool = False
    profile: str = "livestream"
    style: str = "gaming"
    quality: str = Field(default="preview", pattern=r"^(preview|final)$")
    aspect: str = Field(default="9:16", pattern=r"^(9:16|16:9|1:1)$")
    max_disk_gb: float = Field(default=10, ge=.1, le=1000)
    max_runtime: float = Field(default=0, ge=0, le=604800)


def _run_live_session(watcher):
    try:
        watcher.run()
    except Exception as exc:
        logger.exception("Live watcher failed")
        watcher.error(exc)
        watcher.update(status="failed", error=str(exc))
        watcher.stop_event.set()


def _live_status(session_id):
    with live_sessions_lock:
        session = live_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Live session not found")
    snapshot = session["watcher"].snapshot()
    for clip in snapshot["clips"]:
        relative = Path(clip["output"]).relative_to(EXPORT_DIR / session_id)
        clip["url"] = f"/api/live/{session_id}/media/{relative.as_posix()}"
        clip["download_url"] = clip["url"]
        clip["size_mb"] = round(Path(clip["output"]).stat().st_size / 1048576, 2)
    return {"session_id": session_id, **snapshot}


@app.post("/api/live/start")
async def start_live(req: LiveStartRequest):
    session_id = uuid.uuid4().hex
    try:
        config = WatchConfig(**req.model_dump(), capture_dir=str(RAW_DIR / session_id),
                             output_dir=str(EXPORT_DIR / session_id)).validate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with live_sessions_lock:
        if any(session["thread"].is_alive() for session in live_sessions.values()):
            raise HTTPException(status_code=409, detail="Stop the active live watcher before starting another")
        watcher = LiveWatcher(config, processing_lock=job_slots)
        thread = threading.Thread(target=_run_live_session, args=(watcher,),
                                  name=f"watch-{session_id[:8]}", daemon=True)
        live_sessions[session_id] = {"watcher": watcher, "thread": thread}
        thread.start()
    return {"session_id": session_id, "status": "starting"}


@app.get("/api/live")
async def list_live_sessions():
    with live_sessions_lock:
        ids = list(live_sessions)
    return {"sessions": [_live_status(key) for key in ids]}


@app.get("/api/live/{session_id}")
async def live_status(session_id: str):
    return _live_status(session_id)


@app.post("/api/live/{session_id}/stop")
async def stop_live(session_id: str):
    with live_sessions_lock:
        session = live_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Live session not found")
    if session["thread"].is_alive():
        session["watcher"].stop()
    return _live_status(session_id)


@app.get("/api/live/{session_id}/media/{filename:path}")
async def live_media(session_id: str, filename: str):
    if not re.fullmatch(r"[a-f0-9]{32}", session_id):
        raise HTTPException(status_code=404, detail="Not found")
    root = (EXPORT_DIR / session_id).resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix not in {".mp4", ".srt", ".ass", ".json"}:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="video/mp4" if path.suffix == ".mp4" else "text/plain")
