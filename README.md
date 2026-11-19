# AI Video Clipping & Editing Engine 🎬⚡

An autonomous, local-first, free, and open-source AI video clipping engine designed for Kali Linux and optimized for Intel Tiger Lake hardware.

Automatically transcribes long-form video, detects visual scene changes, analyzes audio volume peaks, ranks candidate highlights, snaps cuts to sentence boundaries, and renders professional captioned 9:16 vertical Shorts, Reels, and TikToks.

**Using an AI assistant?** Start with [installation](#install-from-a-fresh-clone),
then [Codex, Gemini or Claude in VS Code or Antigravity](#use-with-codex-gemini-or-claude).
The assistant directs the edit through JSON; FFmpeg and Whisper run locally.

---

## 🌟 Key Capabilities

- **100% Free & Open-Source:** Runs locally with zero paid API requirements.
- **Hardware-Tuned for Intel Core i3-1125G4:**
  - 8 logical threads allocated for maximum multi-core INT8 Whisper inference and FFmpeg parallel encoding.
  - Video streaming pipeline preventing excessive RAM consumption.
  - Optimized FFmpeg `libx264` software encoding (`veryfast` preset).
- **Multi-Signal Highlight Ranking:**
  - Combines speech pacing (WPM), volume bursts (RMS peaks), and visual scene frequency.
  - Uses available speech timings to improve cut boundaries; review each edit for complete sentences.
- **Professional Vertical Video Composer:**
  - **Blurred Background Fill:** Transposes 16:9 widescreen footage into modern 9:16 vertical reels with no black bars.
  - **Fit Pad:** Keeps the full source viewport visible, including gameplay HUD and tutorial controls.
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

### Install from a fresh clone

These commands target Kali Linux / Debian / Ubuntu. On Windows, use a Linux
environment such as WSL and open this project in that environment so the agent,
Python and FFmpeg use the same filesystem.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip ffmpeg fonts-dejavu-core fonts-noto-core
git clone https://github.com/krityamsingh/AI-Clipping.git
cd AI-Clipping
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
python -m src.agent_cli --help
```

Use Python 3.11 or newer and an FFmpeg build with `libx264` and the `ass`
subtitle filter. The first transcription downloads the selected Whisper model;
later runs reuse the local cache. The engine uses CPU INT8 inference and does
not require a GPU or an LLM API key. External assistants have their own account,
usage limits and possible subscription/API costs. Node.js is optional for the
Python editing workflow; a terminal assistant may require it separately.

Place an authorized source video at `raw/my_video.mp4`. Input videos, exported
clips, model caches and generated analysis files are excluded from Git. Run
all following commands from the repository root with `.venv` activated. If an
agent starts a fresh shell, tell it to use `.venv/bin/python` explicitly.

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

- FFmpeg editing and Faster-Whisper transcription run locally. They do not require a cloud editing or transcription service.
- Cloud assistants can send the frames, transcripts and other context you provide to their model provider. Use an appropriate local agent for material that must stay on-device. Optional URL downloads and online voice generation also require network services.
- The web interface defaults to localhost (`127.0.0.1`). It is unauthenticated; keep it bound to loopback.

## Use with Codex, Gemini or Claude

AI-Clipping exposes the same CLI and JSON edit-plan interface to each assistant.
Choose an agent that can read workspace files and run terminal commands. Frame
review additionally needs image inspection; audio review needs playback or an
audio-capable tool. Ask it to report any review it cannot perform.

### VS Code

1. Open the cloned **AI-Clipping folder**, then open its integrated terminal
   and run `source .venv/bin/activate`.
2. Choose one assistant and sign in using its supported account method:

   | Assistant | Start in VS Code |
   | --- | --- |
   | Codex | Install the official OpenAI Codex extension, open its panel and start a local session. Follow the [Codex IDE setup](https://developers.openai.com/codex/ide/). |
   | Gemini | Run Gemini CLI in the integrated terminal using the [official installation guide](https://geminicli.com/docs/get-started/installation/). With a compatible Node.js installation, `npx @google/gemini-cli` starts it without a permanent install. |
   | Claude | Install the official Anthropic Claude Code extension and open its panel. Follow the [Claude Code VS Code setup](https://code.claude.com/docs/en/vs-code). |

3. Give the assistant the prompt below and let it read `AGENTS.md`. Keep the
   work local so it can access your source video and installed dependencies.

### Antigravity

1. Follow the [official Antigravity setup](https://antigravity.google/docs/getting-started),
   open the cloned **AI-Clipping folder** as your workspace and activate `.venv`
   in its terminal.
2. Open the Agent panel, sign in and select a Gemini model offered by your
   installation. If your model picker offers Claude, you can use it with the
   same prompt; model availability depends on your installation and account.
3. To use Codex or standalone Claude Code from Antigravity, install the
   [Codex CLI](https://developers.openai.com/codex/cli/) or
   [Claude Code CLI](https://code.claude.com/docs/en/quickstart) using the vendor
   instructions, then run `codex` or `claude` from the workspace terminal.
   Gemini CLI can also run there. These terminal options do not require an IDE
   extension to be available in Antigravity's marketplace.
4. Paste the prompt below. Explicitly ask the agent to read `AGENTS.md`; do not
   assume every assistant automatically loads that filename.

### Copy-and-paste editing prompt

Change the source path, content profile, number of parts and target length to
match your footage. For example:

```text
Read AGENTS.md and follow its editing contract. Use .venv/bin/python from
this repository root for every Python command.

Edit raw/my_video.mp4 into up to two standalone 45-second vertical gaming
highlights using the gaming style. Analyze the real source with Whisper
small and relevant vocabulary. Read the report, transcript, word timings,
candidate highlights and caption review flags. Extract and inspect actual
source frames and surrounding footage before describing events.

Create edit_plan.json through src.agent_cli and refine its shots using
observed timestamps. Preserve the setup and payoff. Use fit_pad to retain
the HUD. Do not rewrite Python modules to make this edit. Do not invent
dialogue or subtitles, and do not create filler to reach two parts.

Validate the plan, render a preview, review its framing and caption wording,
then set settings.quality to final and render into export/my_video_final.
Use verified caption corrections only. If you cannot inspect images or
listen to audio, say which checks remain for me. Report the output paths,
decode results and any uncertain captions. Keep generated media out of Git.
```

### Exact commands the agent can run

```bash
python -m src.agent_cli analyze --source raw/my_video.mp4 \
  --profile gaming --model small --duration 45 --vocabulary GTA Rockstar NPC \
  --output analysis_report.json
python -m src.agent_cli frames --analysis analysis_report.json \
  --output-dir previews/agent_frames --max-frames 24
python -m src.agent_cli plan --analysis analysis_report.json \
  --profile gaming --style gaming --parts 2 --duration 45 --quality preview \
  --output edit_plan.json
```

The agent reads the actual report and JPEGs, then edits `edit_plan.json` to
choose coherent shots and layouts. Keep observed transcript word timings.
Available layouts are `blur_fill`, `center_crop` and `fit_pad`. The complete
schema, profiles and supported effects are in [AGENTS.md](AGENTS.md).

```bash
python -m src.agent_cli validate --plan edit_plan.json
python -m src.agent_cli render --plan edit_plan.json --output-dir previews/my_video
```

Review the preview and its `.srt`/`.ass` captions against the source. After any
corrections, set `settings.quality` to `"final"` in `edit_plan.json`, validate
again and render:

```bash
python -m src.agent_cli validate --plan edit_plan.json
python -m src.agent_cli render --plan edit_plan.json --output-dir export/my_video_final
```

For verified spelling corrections, save a JSON dictionary in `corrections.json`
and add `--corrections corrections.json` to the render command. Each completed
part includes `Part_01.mp4`, `.srt`, `.ass` and a quality report. Full decoding
checks playability; source context, framing and caption accuracy need review.
Use `--signals-only` for a faster pass over multi-hour recordings when no
transcript is needed; this disables speech captions.

### Copy-and-paste continuous livestream prompt

```text
Read AGENTS.md and the README watch-live section. Use .venv/bin/python.
Start watch-live for https://www.twitch.tv/CHANNEL_NAME with 60-second
chunks, 45-second target clips, Whisper small, preview quality, a 10 GiB
session disk budget and --max-runtime 3600. Run it as a managed background
process so I can keep using the IDE. Report its process/session and status
file path, check errors and review saved clips from real frames and audio
where your tools support it. Treat activity scores as candidate signals.
Do not claim guaranteed virality. Stop gracefully on request and let queued
work finish. Keep all recordings and renders out of Git.
```

For offline streams, blocked downloads, missing FFmpeg or transcription errors,
report the actual error and resolve the prerequisite before claiming an edit
is complete. A local MP4 can be used when platform downloading is unavailable.


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

## Continuous live stream watcher

`watch-live` keeps capturing while a single background worker ranks finalized
windows, transcribes selected windows with Faster-Whisper, and renders clips.
It accepts public YouTube/Twitch live pages through yt-dlp, or a direct playable
HTTP(S)/HLS/RTMP stream URL. Platform extraction requires a current yt-dlp and
may fail when a stream is private, restricted, offline, or blocked by the site.
It retries offline/disconnected streams and resolves fresh media URLs each time.
Separate HLS video and audio renditions are joined through a shared manifest,
including YouTube streams that do not offer a combined format.
It does not bypass login, DRM, or platform access restrictions.

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install --upgrade yt-dlp
python -m src.agent_cli watch-live \
  --url 'https://www.youtube.com/watch?v=LIVE_VIDEO_ID' \
  --twitch-channel CHANNEL_NAME \
  --model small --vocabulary GTA Rockstar NPC \
  --chunk-seconds 60 --duration 45 --min-score 35 \
  --quality preview --max-disk-gb 10
```

For Twitch video, the chat channel is inferred from the link:

```bash
python -m src.agent_cli watch-live --url 'https://www.twitch.tv/CHANNEL_NAME'
```

The dashboard at `http://127.0.0.1:8000` has a **Continuous live stream clipper**
section with Start/Stop controls, chat messages per five seconds, chat spike
ratio, activity spike count, queue depth, reconnects, dropped chunks and clips.
Run the existing server with `python main.py --web`. Keep it bound to loopback.
The REST equivalents are:

- `POST /api/live/start` with `{"url":"https://…","twitch_channel":"channel"}`
- `GET /api/live` to list current process sessions
- `GET /api/live/{session_id}` for counters, errors and downloadable clips
- `POST /api/live/{session_id}/stop` to stop capture and finish pending work

CLI sessions get unique `raw/watch_<id>/` and `export/watch_<id>/` directories.
`export/watch_<id>/status.json` is updated while running. Use Ctrl+C/SIGTERM to
stop capture gracefully; current ASR/render and the bounded pending queue drain
before exit. `--max-runtime 3600` stops after approximately an hour;
`--max-runtime 0` (default) watches until stopped or the disk budget is reached.
Captures do not resume after a process restart; start a new session. Selected
source windows remain available for reviewing and rerendering the saved EDL.
Nonselected raw chunks and temporary audio are deleted after processing.

How selection works:

- FFmpeg copies the live stream into keyframe-aligned chunks without waiting
  for the entire broadcast. It only queues chunks listed as finalized by FFmpeg.
- A rolling window includes the preceding and following chunk when available,
  preserving setup/payoff across boundaries. Peaks belong to one central chunk;
  overlapping exported source intervals are suppressed. Gaps/reconnects start
  a new context window. Startup/shutdown chunks can have less context.
- Motion differences, relative audio onsets, and optional Twitch chat bursts
  contribute to an activity score. `--min-score` filters candidates. Quiet
  windows may produce no clip. The spike counter counts candidate windows
  above this threshold, before export deduplication. It is not a viewer count
  or a probability that a clip will go viral.
- Twitch chat uses a read-only anonymous TLS IRC connection and reconnects
  independently. No chat messages are sent. Only bounded arrival timestamps
  and excitement flags are retained; usernames/raw chat are not saved.
  A YouTube video can use a Twitch chat channel if that channel is relevant;
  this does not collect YouTube chat. An unavailable chat connection is shown
  in status and leaves motion/audio selection running.
- Chat/media alignment is **estimated**, because chat arrival and playback
  latency differ. `--chat-offset -5` maps a chat arrival five seconds earlier
  in the recording. Calibrate against a known visible event; offset is added
  to each chat arrival timestamp relative to capture startup.
- Whisper small runs only when activity candidates survive selection. It
  supplies real word timings and captions, expands nearby utterance boundaries,
  and emits caption review flags. It is reused across windows. First use can
  download the model. `--signals-only` skips ASR and disables speech captions.
- Vertical clips use `fit_pad` to preserve gameplay/HUD. `--aspect 16:9`,
  `--profile`, `--style`, `--vocabulary` and `--quality final` are available.
  Each selected window has its report, editable plan, MP4, SRT, ASS, and full
  FFprobe/decode validation reports. Automated renders still need visual and
  caption review; the tool does not recognize game events semantically.

Capture continues during processing. ASR and final encodes run serially; the web
watcher shares the existing heavy-job semaphore. If processing falls behind,
`--queue-size` (default 4) bounds pending chunks and **drops newly finalized
chunks**, recording the count. Reduce the Whisper model, use signals-only or
preview quality, or increase chunk length on a slower machine. Typical latency
is at least two chunks plus processing and stream playback delay. This is a
rolling clipper, not frame-instant event detection.

`--max-disk-gb` limits this session's raw captures and output together (default
10 GiB). The watcher stops with a failure status at the limit. A current chunk,
ASR/render temporary files and draining queued jobs can overshoot the limit;
leave free disk headroom. Archive exports and start a new session to continue.
Whisper models outside the session are not included in this budget.

Implementation references: [yt-dlp embedding and formats](https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp),
[FFmpeg segment muxer](https://ffmpeg.org/ffmpeg-formats.html#segment),
and [Twitch IRC](https://dev.twitch.tv/docs/chat/irc/).
