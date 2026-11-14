# AI Video Clipping & Editing Engine 🎬⚡

An autonomous, local-first, free, and open-source AI video clipping engine designed for Kali Linux and optimized for Intel Tiger Lake hardware.

Automatically transcribes long-form video, detects visual scene changes, analyzes audio volume peaks, ranks candidate highlights, snaps cuts to sentence boundaries, and renders professional captioned 9:16 vertical Shorts, Reels, and TikToks.

---

## 🌟 Key Capabilities

- **100% Free & Open-Source:** Runs locally with zero paid API requirements.
- **Hardware-Tuned for Intel Core i3-1125G4:**
  - 8 logical threads allocated for maximum multi-core INT8 Whisper inference and FFmpeg parallel encoding.
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


## Autonomous editing agent interface (v2)

AI-Clipping now provides a **model-neutral command line and REST interface**
for agents (including IDE assistants and local LLMs). Agents can analyze real
videos, select exact shots, modify a JSON edit decision list, split long
podcasts into Part 1 / Part 2 episodes, correct verified caption errors and
render the selected result. **Read [AGENTS.md](AGENTS.md) first.**

### Quick start

    python -m src.agent_cli analyze --source raw/my_video.mp4 --model small --vocabulary GTA Rockstar NPC --output analysis_report.json
    python -m src.agent_cli frames --analysis analysis_report.json --output-dir previews/agent_frames
    python -m src.agent_cli plan --analysis analysis_report.json --profile gaming --parts 2 --output edit_plan.json
    python -m src.agent_cli validate --plan edit_plan.json
    python -m src.agent_cli render --plan edit_plan.json --output-dir export/agent_edit

An external agent may edit edit_plan.json between plan and render: rearrange
source_start/source_end clips, shot order, title cards, layouts, visual toggles
and caption_corrections. No source-code changes are needed for a new edit.

For a long podcast in one command:

    python -m src.agent_cli auto --source raw/podcast.mp4 --profile podcast --parts 2 --duration 60 --model small --quality preview

To correct names and phrases, create corrections.json, e.g.:

    {"g t a": "GTA", "rock star": "Rockstar"}

Then render with:

    python -m src.agent_cli render --plan edit_plan.json --corrections corrections.json

The web API supports GET /api/agent/spec and POST /api/agent/analyze,
/api/agent/plan, and /api/agent/render; poll GET /api/status/{job_id}.

The output includes Part_01.mp4, Part_01.srt, Part_01.ass,
Part_01_quality_report.json, and additional parts as applicable.
Each export is decoded fully and probed for dimensions, codec and duration.
Transcript accuracy is not guaranteed: the engine flags uncertain words,
accepts verified corrections and preserves corrected subtitles across edits.
A local agent should listen to the source and verify final caption wording.
The automatic candidate scoring is still a heuristic; advanced visual
understanding and semantic self-review require a compatible external agent.


## Long livestream, sports and action highlights

The multi-signal clipper can examine large recorded streams without loading
video frames into RAM. It computes frame motion spikes (2 fps), relative audio
onsets and optional chat bursts; the agent chooses actual source timestamps
from evidence, not invented "viral" events. For long VODs:

    python -m src.agent_cli analyze --source raw/long_stream.mp4 \
      --profile livestream --signals-only --duration 45 \
      --candidates 20 --output analysis_report.json
    python -m src.agent_cli plan --analysis analysis_report.json \
      --profile livestream --style energetic --parts 5 --output edit_plan.json
    python -m src.agent_cli render --plan edit_plan.json

For direct playable HLS/RTMP streams, finite capture plus clip export:

    python -m src.agent_cli clip-live --url "https://example.com/live.m3u8" \
      --chunks 4 --chunk-seconds 180 --clips-per-chunk 1 \
      --capture-dir raw/live_001 --output-dir export/live_001

Video category profiles now include livestream, gaming, esports, sports,
podcast, interview, talking_head, reaction, comedy, vlog, travel, tutorial,
education, technology, product_demo, review, documentary, news, music,
dance, cooking, trailer, general. Implemented edit styles: clean, energetic,
gaming, podcast, tutorial, cinematic, documentary and minimal.
These change actual caption typography and default framing, not arbitrary
random effects. See AGENTS.md for category-specific decisions and limitations.

Use --chat-log with relative timestamped messages in JSON, JSONL, or
[HH:MM:SS] TXT format. With --signals-only Whisper is intentionally skipped
and speech captions are disabled; speech accuracy requires real ASR and
verification. The capture operation records for a finite duration and **then**
analyzes chunks; it is not continuous live classification. Agent models can
inspect sampled original frames via the frames command.
