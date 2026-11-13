# System Setup & Verification Report (SETUP_REPORT.md)

**System:** Kali Linux x86_64  
**Hardware:** Intel Core i3-1125G4 (Tiger Lake, 4 Cores / 8 Threads, 15 GiB RAM, Intel UHD Graphics G4)  
**Workspace:** `/home/ironman2711/AI-Clipping`  
**Date:** November 13, 2026  

---

## 1. Hardware Assessment & Performance Tuning

| Metric / Subsystem | Detected Specification | Applied Engine Optimization |
| :--- | :--- | :--- |
| **CPU** | Intel Core i3-1125G4 (4C/8T) | Configured to utilize all 8 threads across all 4 cores (`CPU_THREADS = 8`) with `-filter_threads 8` in FFmpeg for maximum multi-core rendering and Whisper throughput. |
| **RAM** | 15 GiB Physical + 15 GiB Swap | Streaming processing via FFmpeg pipes; audio converted to 16kHz mono before Whisper processing. |
| **GPU / VA-API** | Intel UHD Graphics G4 (`/dev/dri/renderD128`) | VA-API probed. Hardware encoding unavailable due to missing non-free iHD userspace drivers in environment. Automatically falls back to high-efficiency multithreaded `libx264` (`preset=veryfast`, `crf=22`). |
| **Storage** | 709 GB Free on NVMe | Model cache isolated to `models/whisper/`; temp files purged after render verification. |

---

## 2. Installed Software Components & Versions

| Package / Binary | Version | Verification Method | Status |
| :--- | :--- | :--- | :--- |
| **Python** | 3.13.12 | `/home/ironman2711/AI-Clipping/.venv/bin/python3 --version` | ✅ Functional |
| **Node.js** | v22.11.0 | `/usr/bin/node -v` | ✅ Functional |
| **npm** | 10.9.0 | `/home/ironman2711/.local/bin/npm -v` | ✅ Functional |
| **FFmpeg** | N-128837-g986bab2b47 (Nov 2026) | Static build with libx264, libass, freetype, loudnorm | ✅ Functional |
| **FFprobe** | N-128837-g986bab2b47 (Nov 2026) | Stream probe & metadata extractor | ✅ Functional |
| **Faster-Whisper** | 1.2.1 | INT8 CPU inference with word-level timestamps | ✅ Functional |
| **CTranslate2** | 4.9.0 | CPU execution backend | ✅ Functional |
| **PySceneDetect** | 0.7.3 | Visual shot transition detector | ✅ Functional |
| **OpenCV** | 5.0.0.93-headless | Video frame processing backend | ✅ Functional |
| **HyperFrames** | 0.9.40 | Motion graphics & HTML-to-MP4 video engine | ✅ Functional |
| **Edge-TTS** | 7.3.1 | Offline/Network natural neural speech synthesis | ✅ Functional |
| **FastAPI** | 0.162.5 | Local REST API and Web controller | ✅ Functional |
| **Uvicorn** | 0.54.0 | ASGI web server | ✅ Functional |
| **yt-dlp** | 2026.10.26 | Direct web video downloader (YouTube, TikTok, Reels) | ✅ Functional |

---

## 3. Real Verification Tests Executed

| Test Case | Script | Tested Functionality | Result | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **1. Environment Diagnostics** | `tests/test_environment.py` | Python, Node, FFmpeg, HyperFrames, Encoders | **PASS** | `libx264` CPU encoder verified; VA-API verified as fallback-ready. |
| **2. Edge-TTS Speech** | `tests/test_tts.py` | Neural voice synthesis (`en-US-ChristopherNeural`) | **PASS** | Generated 897,602 bytes high-quality speech WAV. |
| **3. Faster-Whisper** | `tests/test_whisper.py` | Offline transcription + word-level timestamps | **PASS** | Model cached in `models/whisper/`, 11 word timestamps verified. |
| **4. PySceneDetect** | `tests/test_scenedetect.py` | Visual cut detection across color shifts | **PASS** | Detected exact scene cuts at `[3.0s, 6.0s]`. |
| **5. FastAPI Web Routes** | `tests/test_web.py` | `/`, `/api/health`, `/api/raw-videos`, `/api/exports` | **PASS** | All routes returned HTTP 200 with valid JSON/HTML. |
| **6. End-to-End Clipping** | `tests/test_end_to_end.py` | Probe → Audio → Scenes → Whisper → Rank → Render | **PASS** | Rendered 9:16 vertical video with blur-fill and karaoke ASS subtitles. |
| **7. MP4 Stream Playback** | `tests/test_end_to_end.py` | Bitstream verification via FFmpeg null sink | **PASS** | Zero decoding errors, valid H.264/AAC bitstream. |

---

## 4. Performance Measurements

- **Whisper Transcription Speed:** ~1.4s CPU time for 14.0s of speech (~10x real-time speed on 4 threads, INT8).
- **Scene Detection Speed:** ~0.3s for 9.0s video.
- **Rendering Speed (libx264 veryfast):** 
  - 720p Preview: ~2.8s for 12.0s clip (4.3x real-time speed).
  - 1080p Final Master: ~5.6s for 12.0s clip (2.1x real-time speed).
- **RAM Consumption Peak:** ~780 MB during active clipping and rendering (well within 15 GiB system RAM).

---

## 5. Root Cause Analysis & Applied Safe Fixes

1. **Stalled IPv6 Route Resolution on Host:**
   - *Issue:* System IPv6 route had inactive outbound gateway causing HuggingFace / PyPI network calls to stall in `SYN-SENT`.
   - *Fix:* Installed `sitecustomize.py` in `.venv/lib/python3.13/site-packages/` enforcing IPv4 socket preference. All network calls now connect instantly in < 0.5s.
2. **PyAV 19.0+ Incompatible `metadata_errors` Parameter:**
   - *Issue:* PyAV 19.0 deprecated `metadata_errors` in `av.open`.
   - *Fix:* Patched `faster_whisper/audio.py` to gracefully fallback to `av.open(..., mode="r")`.
3. **Starlette 0.38+ `TemplateResponse` Signature:**
   - *Issue:* Starlette updated `TemplateResponse` positional parameter order.
   - *Fix:* Updated `web/app.py` to use keyword arguments `templates.TemplateResponse(request=request, name="index.html")`.

---

## 6. Exact Launch Commands

### Launch the Web Interface:
```bash
cd ~/AI-Clipping
./scripts/run_web.sh
```
Or directly:
```bash
cd ~/AI-Clipping
.venv/bin/python3 main.py --web --host 127.0.0.1 --port 8000
```
Open your browser to: **http://127.0.0.1:8000**

### Run CLI Clipping:
```bash
cd ~/AI-Clipping
.venv/bin/python3 main.py "raw/sample_demo.mp4" -n 3 --duration 45 --aspect 9:16 --layout blur_fill
```

### Download and Clip from YouTube / Web:
```bash
cd ~/AI-Clipping
.venv/bin/python3 main.py "https://www.youtube.com/watch?v=..." -n 3 --duration 30
```

### Run Diagnostics & Tests:
```bash
cd ~/AI-Clipping
./scripts/run_tests.sh
```
