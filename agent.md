# agent.md — AI-Clipping editor agent instructions

**Canonical full instructions: [AGENTS.md](AGENTS.md). Read that file before editing.**
This alias is for agents that look for the lowercase agent.md filename.

## Workflow for any autonomous AI agent

1. Inspect the actual source using python -m src.agent_cli analyze.
2. Optionally run python -m src.agent_cli frames --analysis analysis_report.json
   to inspect source video JPEGs, if the agent supports visual inputs.
3. Read the generated analysis_report.json including transcript timestamps,
   candidate highlights and low-confidence caption flags.
4. Identify the content as podcast, gaming, talking_head, tutorial or general.
5. Choose a self-contained story, then create/edit edit_plan.json with
   source_start/source_end for every selected shot and the intended shot order.
6. When the source is long, create separate numbered episodes with titles
   PART 1, PART 2 and so on. Preserve chronological story progression.
7. Choose framing based on what is visible. Use fit_pad for screen tutorials
   or gameplay HUD; use blur_fill for landscape podcasts where full width matters.
8. Create a corrections.json dictionary of verified spoken name/term corrections.
   Preserve real speech and word-level timings. Do not invent caption text.
9. Validate: python -m src.agent_cli validate --plan edit_plan.json
10. Render: python -m src.agent_cli render --plan edit_plan.json --corrections corrections.json
11. Inspect output MP4 and SRT, compare text to audio, fix errors and rerender.

The automatic selector is an offline transcript-based heuristic, not a full
multimodal reasoning model. External agents should make visual and narrative
decisions only from actual source evidence.

**For full schema, tool endpoints, quality requirements, constraints and
content-specific editing decisions, use AGENTS.md.**


## New activity-driven clipping workflow

For a multi-hour game stream, esports match, sports stream or reaction video:

    python -m src.agent_cli analyze --source raw/stream.mp4 \
      --profile livestream --signals-only --candidates 25 \
      --duration 45 --output analysis_report.json
    python -m src.agent_cli frames --analysis analysis_report.json --max-frames 48
    python -m src.agent_cli plan --analysis analysis_report.json \
      --profile livestream --style energetic --parts 5
    python -m src.agent_cli render --plan edit_plan.json

Supported content profiles: general, livestream, gaming, esports, sports,
podcast, interview, talking_head, reaction, comedy, vlog, travel, tutorial,
education, technology, product_demo, review, documentary, news, music,
dance, cooking and trailer.

Choose one implemented edit style: clean, energetic, gaming, podcast,
tutorial, cinematic, documentary or minimal. Style changes actual captions,
framing and modest grading. Do not confuse profile with style.

For optional chat spikes supply --chat-log raw/chat.json with timestamps
measured relative to recording start. For directly playable HLS/RTMP:

    python -m src.agent_cli clip-live --url "https://example.com/live.m3u8" \
      --chunks 4 --chunk-seconds 180 --duration 45 \
      --capture-dir raw/live_001 --output-dir export/live_001

This capture is finite; the actual clipping happens after recording completes.
Use fresh folders per capture. A page URL from Twitch/YouTube is not necessarily
a playable FFmpeg URL. Captions are unavailable in --signals-only unless an
actual timed transcript is supplied later.

**Crucial**: measured audio, motion and chat peaks indicate possible action,
not semantic certainty (goals, kills, record-breaking moments, comedy).
Inspect video frames and listen to source audio before generating factual
titles or declaring the clip accurate. Continue using the full AGENTS.md
quality, caption and unsupported-feature requirements.
