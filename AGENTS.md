# AGENTS.md — AI-Clipping agent operations contract

This file is for **any coding agent, local LLM agent, IDE agent, or external workflow**.
Do not rewrite Python modules just to edit a new video. Use the JSON EDL interface.
The agent is the creative director; the engine is the deterministic execution tool.

## Tool interface (model-neutral)

Run from repository root on Kali Linux after installing FFmpeg/FFprobe and Python dependencies.

- Inspect and transcribe real source:
  python -m src.agent_cli analyze --source raw/my_video.mp4 --model small --duration 50 --vocabulary GTA Rockstar NPC
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
   candidate_highlights and caption_review_flags. Watch original material when
   visual understanding is required. Never claim to have seen a frame unless
   an actual image or decoder frame has been inspected.
2. Identify what kind of video it is. Use general when uncertain.
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

The runtime currently offers blur_fill, center_crop and fit_pad; subtle static
zoom, per-shot color toggles, caption burn-in and part-card text. More complex
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
