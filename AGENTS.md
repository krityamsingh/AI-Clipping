# AGENTS.md — AI-Clipping agent operations contract

This file is for **any coding agent, local LLM agent, IDE agent, or external workflow**.
Do not rewrite Python modules just to edit a new video. Use the JSON EDL interface.
The agent is the creative director; the engine is the deterministic execution tool.

## Tool interface (model-neutral)

Run from repository root on Kali Linux after installing FFmpeg/FFprobe and Python dependencies.

- Inspect and transcribe real source:
  python -m src.agent_cli analyze --source raw/my_video.mp4 --model small --duration 50 --vocabulary GTA Rockstar NPC
- Extract actual scene frames for vision-capable agents:
  python -m src.agent_cli frames --analysis analysis_report.json --output-dir previews/agent_frames --max-frames 24
- Generate an editable plan:
  python -m src.agent_cli plan --analysis analysis_report.json --profile gaming --duration 50 --parts 2 --output edit_plan.json
- Validate an agent-authored plan:
  python -m src.agent_cli validate --plan edit_plan.json
- Render the exact plan:
  python -m src.agent_cli render --plan edit_plan.json --output-dir export/my_video
- Fully automatic local fallback:
  python -m src.agent_cli auto --source raw/podcast.mp4 --profile podcast --parts 2 --duration 60 --model small
- Apply verified spellings:
  python -m src.agent_cli render --plan edit_plan.json --corrections corrections.json

Python functions: src.agent_workflow.analyze_source, build_auto_plan,
validate_plan; src.render_plan.render_plan; src.transcript_tools.correct_transcript.
Available editing-agent HTTP routes: GET /api/agent/spec,
POST /api/agent/analyze, POST /api/agent/plan, POST /api/agent/render,
and GET /api/status/{job_id}. Server is local and unauthenticated; bind only to
127.0.0.1, never expose it publicly without authentication.

## What the agent MUST do before editing

1. Read the real analysis_report.json, metadata, transcript, word timings,
   candidate_highlights and caption_review_flags. Use the frames subcommand
   to inspect actual timestamped JPEGs if the agent supports vision. Watch original material when
   visual understanding is required. Never claim to have seen a frame unless
   an actual image or decoder frame has been inspected.
2. Identify the content type using the extended profile taxonomy below. Use general when uncertain.
3. Select a self-contained story with a meaningful hook, necessary context,
   coherent progression, and satisfying final sentence.
4. Do not invent source timestamps, dialogue, scene events, sound effects,
   scores, or claims. Preserve the creator's meaning.
5. Generate a new edit_plan.json using the actual source file and measured
   timestamps. Agents can choose any number and order of source shots. Every
   shot must have source_start < source_end and duration >= 0.2 seconds.
6. Each part should be a coherent standalone episode. Part numbers must be
   1, 2, 3, etc. and should be chronological unless narrative ordering
   genuinely benefits from rearrangement. Use title_card "PART 1", "PART 2".
7. Remove only unnecessary pauses or fillers; preserve word beginnings and
   endings. If a cut removes context, expand or discard the shot.
8. Inspect captions in the SRT and ASS files, especially names, numbers,
   mixed Hindi/English speech and low-confidence transcription.
9. Inspect preview and final renders. The tool tests codec, resolution,
   duration and full-stream decoding; the agent should still evaluate
   hook relevance, cropping, legibility and whether words match the audio.
10. If review finds a mistake, fix the plan or corrections mapping, rerender
    the affected part, and validate again.

## Editing decisions by content

| Profile | Select | Prefer | Avoid |
|---|---|---|---|
| podcast | strong Q&A, useful stories, debates | intelligible uninterrupted speech, clean cuts, 1 or 2 speaker-focused episodes | irrelevant reaction inserts, cuts in mid-sentence |
| gaming | reveals, major action and gameplay explanations | important visual continuity, legible gameplay in 9:16, optional split into related topics | center-crop cutting off HUD or action |
| talking_head | clear advice, personal narrative, compelling statement | careful pause removal, framed speaker, understated captions | zoom on every word |
| tutorial | complete demonstrable learning steps | screen visibility, longer explanatory holds, ordered parts | missing prerequisite steps |
| general | self-contained highlights | simple cuts, original sound, evidence-led pacing | generic over-edited templates |

The runtime offers blur_fill, center_crop and fit_pad; restrained static
zoom, per-shot color toggles, style-driven captions, and part-card text. More complex
split-screen, tracked crops, music inserts, semantic b-roll or animated cut
transitions are not currently implemented. Never specify unsupported effects
as if they worked. Use fit_pad when a crop would hide important UI.

## Editable edit_plan.json schema (v1)

Example (replace all paths/timestamps/text with observed data):

    {
      "version": 1,
      "source": "/absolute/path/to/raw/podcast.mp4",
      "profile": "podcast",
      "settings": {
        "aspect_ratio": "9:16",
        "quality": "final",
        "captions": true,
        "word_highlight": true,
        "normalize_audio": true
      },
      "caption_corrections": {
        "Rock star": "Rockstar",
        "G T A": "GTA"
      },
      "transcript": [],
      "parts": [
        {
          "part": 1,
          "title": "Key question and answer",
          "title_card": "PART 1",
          "shots": [
            {
              "shot_id": "hook",
              "source_start": 42.2,
              "source_end": 48.9,
              "purpose": "opening question",
              "layout": "blur_fill",
              "zoom_effect": false,
              "color_correction": false
            },
            {
              "shot_id": "answer",
              "source_start": 53.1,
              "source_end": 82.6,
              "purpose": "answer and conclusion",
              "layout": "blur_fill"
            }
          ]
        }
      ]
    }

The transcript must contain observed start/end/text and (where present) Whisper
word-level start/end/probability data. Never write a fake transcript: copy it from
analysis_report.json or deliberately omit it and disable captions.

Agents can insert/remove/reorder shots, edit purposes, title card, layout,
caption corrections and per-shot zoom/color flags. The renderer enforces bounds
against the real source; it does not execute arbitrary shell strings.

## Caption correction policy — critical

Transcription cannot be guaranteed perfect by spellcheck alone. Use
Faster-Whisper small instead of base where practical. Supply domain vocabulary
when analyzing names and technical terms. Read low-confidence flags and listen
to the matching original timestamps. Add **verified** replacements to
corrections.json as a JSON dictionary, e.g.:

    {"rock star": "Rockstar", "g t a": "GTA", "play station": "PlayStation"}

Word-level corrections are applied to captions and SRT consistently. If
replacements change the number of words, timestamps are estimated over the
original phrase and explicitly flagged. Do not blindly change dialogue meaning.
A missing word timing should not be presented as verified alignment.
A segment cut mid-phrase without words is intentionally omitted from captions.

Caption rules: max ~5 words / 42 characters per cue, natural punctuation,
no misleading carry-over across cuts, and subtitle text must describe
what is audibly spoken. Never silently add words the speaker did not say.
The final output includes separate .srt and .ass files for further inspection.

## Multi-part rules

For long podcasts or videos, the auto planner selects multiple non-overlapping
highlight windows and names them Part_01.mp4, Part_02.mp4, etc. Their order
is chronological by original source timestamp. Explicit --parts N overrides
the automatically chosen count. An agent should make each part independently
meaningful. Part 2 need not be a continuation of Part 1 unless the source really
contains a linked story. If the requested narrative does not fit the target
length, extend the target duration or author multiple adjacent shots.

## Runtime constraints, tests and failure behavior

Use bounded CPU work on 4 cores / 8 threads and 15 GiB RAM. Avoid parallel
heavy ASR and final video encodes. Work with original sources only and use
licensed audio. Do not claim clips are fully edited when only analysis ran.
Render is local; downloading from YouTube may fail. In that case use an
authorized local MP4 and do not substitute unrelated media.

Run:
  python -m unittest discover -s tests -p 'test_agent_pipeline.py' -v
  python -m unittest discover -s tests -p 'test_regressions.py' -v
  python -m compileall -q main.py src web

The CLI emits JSON results on stdout (human tool output from FFmpeg may appear
on stderr). Any failed render raises an error and exits nonzero. Each rendered
part is checked with FFprobe and a full FFmpeg decoding pass. This does not
replace human/vision review of creative quality. Do not fabricate QA scores.


## Livestream and multi-hour VOD clipping

Stream highlights need *multiple* signals, not audio loudness alone:
- Frame motion: FFmpeg continuously decodes low-resolution grayscale frames
  (2fps, 144x80); successive-frame difference and changed-pixel fractions
  estimate movement. Isolated huge scene jumps are downweighted.
- Audio: recording-relative RMS energy and sudden onsets.
- Optional live chat: timestamped message counts, bursts and excitement terms.
- Transcript: speech context, topics and word-level timing when Whisper
  transcription is enabled.

Motion, loudness and chat are candidate evidence, **NOT** proof that a goal,
kill, jump, joke or incredible event happened. Vision-capable agents must
inspect original source frames and surrounding footage before labeling a
moment. Inspect the generated frame samples and do not invent events.

### Multi-hour livestream recording: fast pass

    python -m src.agent_cli analyze \
      --source raw/my_6hour_stream.mp4 --profile livestream \
      --signals-only --duration 45 --candidates 25 \
      --output stream_analysis.json

    python -m src.agent_cli frames \
      --analysis stream_analysis.json --max-frames 48 \
      --output-dir previews/stream_frames

    python -m src.agent_cli plan \
      --analysis stream_analysis.json --profile livestream --style energetic \
      --parts 10 --duration 45 --output stream_edit_plan.json

    python -m src.agent_cli render \
      --plan stream_edit_plan.json --output-dir export/stream_best

Signal-only skips full-length ASR to save CPU/RAM on multi-hour streams and
automatically disables speech captions. No invented subtitles. To have
accurate captions, analyze without --signals-only or attach actual timestamped
speech transcript. Compare corrected subtitles to source audio.

### Chat-augmented selection

    python -m src.agent_cli analyze --source raw/stream.mp4 \
      --profile livestream --chat-log raw/chat.json \
      --signals-only --candidates 15

Accepted chat file examples:

    [{"time": 20.5, "text": "POG"}, {"time": 21.0, "text": "no way"}]

A JSON messages array wrapper also works, as do JSONL files and TXT lines
written as [HH:MM:SS] message. Times are **relative seconds since start of
this exact recording**. Never guess start time or align Unix timestamps
without externally verified timing. Do not disclose raw user chat in titles.

### Finite capture of a playable live feed

    python -m src.agent_cli capture-live \
      --url "https://example.com/live.m3u8" \
      --chunk-seconds 180 --chunks 4 --output-dir raw/live_session_001

    python -m src.agent_cli clip-live \
      --url "https://example.com/live.m3u8" \
      --chunk-seconds 180 --chunks 4 --clips-per-chunk 1 \
      --duration 45 --quality preview \
      --capture-dir raw/live_session_002 --output-dir export/live_session_002

These commands require an HLS/RTMP URL that FFmpeg itself can play (not a
generic YouTube/Twitch webpage). Recording is finite and complete before
the chunk analysis runs. It is **not** instant real-time detection, not an
indefinite watcher, and not an authenticated/DRM downloader. Stream segment
boundaries depend on keyframes. Always use a fresh capture directory.
Network interruptions can leave partial captures; review output status and
actual duration. Respect creators' rights and platform rules.

### Signal reports and ranking

The analysis report includes the activity_analysis object containing motion,
audio_events, chat_bursts, and candidate_highlights. Each selected candidate
includes peak timestamp, motion/audio/chat strengths, signal weights and
the triggering signal. Scores reflect relative measured activity, NOT
virality probability. A static and silent stream may yield zero candidates.
Do not fabricate highlights to meet a requested count.

## Video category profiles

Profiles express the requested editing task; they do not classify the video
by AI understanding. Set the one that matches real source content.

| Profile | Search for | Editing priority |
|---|---|---|
| livestream | chat bursts, action/reaction spikes | preserve cause + reaction |
| gaming | major plays, reveals, gameplay changes | retain HUD and action |
| esports | decisive competitive fights | preserve match context |
| sports | high-motion plays and crowds | preserve scoreboard and event |
| podcast | interesting Q&A, useful stories | complete thought |
| interview | surprising answer or story | question before answer |
| talking_head | clear tips, arguments | readable captions |
| reaction | surprise plus genuine reaction | keep original context |
| comedy | setup and punchline | no cut before payoff |
| vlog | mini-stories and changes | natural pacing |
| travel | place and scenic reveal | let visuals breathe |
| tutorial | demonstrable complete steps | readable interface |
| education | correct explanation | uninterrupted steps |
| technology | factual demos and explanations | accurate terminology |
| product_demo | actual product use and results | preserve evidence |
| review | verdict plus supporting point | avoid misleading edits |
| documentary | connected factual passages | visual continuity |
| news | dated factual context | source and timing |
| music | performance or musical passage | preserve real audio |
| dance | significant coordinated movement | full-body framing |
| cooking | step, transformation and result | ordered process |
| trailer | meaningful reveal | avoid unrelated splices |
| general | coherent self-contained highlight | context first |

Action-oriented profiles use motion/audio/chat evidence when available.
Dialogue-oriented profiles use transcript-based story boundaries. Neither
approach can substitute for a vision-language model examining frames.
Never claim a video contains a particular action without evidence.

## Real editing style presets

The style option chooses different **implemented** caption appearance,
default framing and modest color-grading choices. Agents may use a
settings.edit_style on the whole plan or parts[].edit_style per part.

| Style | Actual changes | Suggested content |
|---|---|---|
| clean | neutral readable captions, minimal grading | vlogs, reviews |
| energetic | larger high-contrast captions, modest grade | stream reactions, sports |
| gaming | compact word highlights, preserve full viewport | gaming, esports |
| podcast | understated long phrases | interviews, podcasts |
| tutorial | smaller captions, full-screen information | screen/tutorial |
| cinematic | white text and less aggressive visuals | trailers, travel |
| documentary | neutral subtitling | education, news |
| minimal | restrained typography | polished excerpts |

The code does **not** currently implement tracking crops, split screens,
automated b-roll insertion, generated memes, royalty-free music search,
beat-perfect edits or instantaneous live decisions. Do not promise those
features. Agents can select/reorder source shots, per-shot layout,
color_correction, zoom_effect and title_card, and choose an implemented style.

## Quality requirements for high-motion streams

1. Inspect the source around the observed peak, including the event setup
   and payoff; do not use loudness or chat spikes alone as a definitive hook.
2. Avoid jump cuts that disconnect cause and effect. Use generous padding
   around a peak, then trim against visible action and spoken-word boundaries.
3. Preserve sports scoreboards, gaming HUD, tutorial controls, moving actors.
   For 9:16 use fit_pad rather than destructive center_crop when appropriate.
4. If captions are present, verify words and proper nouns against sound,
   preserve observed word timings and flag uncertain words.
5. Build parts by independent meaningful episodes or related chapters.
   Never create filler Part 2 solely to match a requested number.
6. Preview/review every completed part and check actual MP4 decoding. An
   FFmpeg pass establishes playability, not narrative quality.
