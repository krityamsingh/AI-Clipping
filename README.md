# AI Video Clipping & Editing Engine 🎬⚡

An autonomous, local-first, free, and open-source AI video clipping engine designed for Kali Linux and optimized for Intel Tiger Lake hardware.

Automatically transcribes long-form video, detects visual scene changes, analyzes audio volume peaks, ranks candidate highlights, snaps cuts to sentence boundaries, and renders professional captioned 9:16 vertical Shorts, Reels, and TikToks.

---

## 🌟 Key Capabilities

- **100% Free & Open-Source:** Runs locally with zero paid API requirements.
- **Hardware-Tuned for Intel Core i3-1125G4:**
  - 4 CPU threads allocated for multithreaded INT8 Whisper inference.
  - Video streaming pipeline preventing excessive RAM consumption.
  - Optimized FFmpeg `libx264` software encoding (`veryfast` preset).
- **Multi-Signal Highlight Ranking:**
  - Combines speech pacing (WPM), volume bursts (RMS peaks), and visual scene frequency.
  - Snaps clip start/end boundaries to sentence endings—never cuts speech mid-sentence.
- **Professional Vertical Video Composer:**
  - **Blurred Background Fill:** Transposes 16:9 widescreen footage into modern 9:16 vertical reels with no black bars.
  - **Stack Layout:** Black canvas with bold title banner at top and captions at bottom.
  - **Center Crop:** Direct full-frame 9:16 crop.
  - **Animated Subtitles (ASS):** Yellow active-word karaoke pop with black outline and crisp typography.
  - **Audio Normalization:** EBU R128 loudness standard (-16 LUFS integrated).
  - **Color Correction:** Boosts contrast and saturation (+12%) for mobile screens.
- **YouTube & URL Downloader:**
  - Integrated `yt-dlp` support for direct clipping from YouTube links or local MP4/MOV/MKV files.
- **Reference-Style Profile Analyzer:**
  - Drops reference reels into `style/` to automatically measure shot pacing and audio dynamics into `STYLE.md`.
- **FastAPI Modern Web Dashboard:**
  - Dark-themed UI with real-time progress tracking, inline video player previews, and metadata export.

---

## 📁 Directory Structure

```text
AI-Clipping/
├── raw/                # Input videos (local uploads or yt-dlp downloads)
├── style/              # Reference reels and STYLE.md profile
├── models/             # Cached AI models (Faster-Whisper INT8)
├── audio/              # Extracted 16kHz speech waveforms
├── captions/           # Generated SRT, VTT, and styled ASS subtitles
├── thumbnails/         # Generated video thumbnails
├── previews/           # Fast 720p preview exports
├── export/             # High-quality 1080p final master renders
├── scripts/            # Helper scripts (run_web.sh, run_tests.sh)
├── src/                # Core engine modules
│   ├── video_analyzer.py
│   ├── video_editor.py
│   ├── caption_generator.py
│   ├── tts_generator.py
│   ├── downloader.py
│   └── style_analyzer.py
├── config/             # Settings and hardware configurations
├── tests/              # Comprehensive verification test suite
├── web/                # FastAPI application and responsive UI
├── .venv/              # Isolated Python virtual environment
├── requirements.txt    # Project dependencies
├── SETUP_REPORT.md     # Installation & hardware benchmark report
├── README.md           # Documentation
└── main.py             # CLI and Web server launcher
```

---

## 🚀 Quick Start Guide

### 1. Launch the Web Interface
Run the launch script from the project directory:
```bash
cd ~/AI-Clipping
./scripts/run_web.sh
```
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

### 2. Run CLI Clipping
Generate 3 clips of 45 seconds each from a local video or YouTube URL:
```bash
cd ~/AI-Clipping
.venv/bin/python3 main.py "raw/sample_demo.mp4" -n 3 --duration 45 --aspect 9:16 --layout blur_fill
```

### 3. Run System Diagnostics
```bash
cd ~/AI-Clipping
./scripts/run_tests.sh
```

---

## 🛠️ CLI Options

| Argument | Description | Default |
| :--- | :--- | :--- |
| `source` | Local video file path or YouTube / Web URL | Optional (starts Web UI if omitted) |
| `--web` | Launch the local web interface | `False` |
| `--port` | Port for the web interface | `8000` |
| `-n, --num-clips` | Number of candidate highlight clips | `3` |
| `-d, --duration` | Target duration in seconds (`15`, `30`, `45`, `60`) | `45.0` |
| `--aspect` | Output aspect ratio (`9:16`, `16:9`, `1:1`) | `9:16` |
| `--layout` | Composition mode (`blur_fill`, `center_crop`, `fit_pad`) | `blur_fill` |
| `--quality` | Render quality (`preview` 720p or `final` 1080p) | `final` |
| `--model` | Faster-Whisper model (`tiny`, `base`, `small`) | `base` |
| `--no-captions` | Disable subtitle burn-in | Enabled |
| `--no-word-highlight` | Disable yellow word-level karaoke pop | Enabled |
| `--no-loudnorm` | Disable EBU R128 audio normalization | Enabled |
| `--analyze-style` | Scan `style/` reference reels and update `STYLE.md` | `False` |
| `--check` | Run system self-diagnostics | `False` |

---

## 🔒 Security & Privacy

- All video frames, audio tracks, and speech transcripts remain 100% on your local laptop.
- No media is uploaded to external clouds or third-party servers.
- The web interface binds strictly to localhost (`127.0.0.1`).
