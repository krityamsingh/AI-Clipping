# agent.md — AI-Clipping editor agent instructions

**Canonical full instructions: [AGENTS.md](AGENTS.md). Read that file before editing.**
This alias is for agents that look for the lowercase agent.md filename.

## Workflow for any autonomous AI agent

1. Inspect the actual source using python -m src.agent_cli analyze.
2. Read the generated analysis_report.json including transcript timestamps,
   candidate highlights and low-confidence caption flags.
3. Identify the content as podcast, gaming, talking_head, tutorial or general.
4. Choose a self-contained story, then create/edit edit_plan.json with
   source_start/source_end for every selected shot and the intended shot order.
5. When the source is long, create separate numbered episodes with titles
   PART 1, PART 2 and so on. Preserve chronological story progression.
6. Choose framing based on what is visible. Use fit_pad for screen tutorials
   or gameplay HUD; use blur_fill for landscape podcasts where full width matters.
7. Create a corrections.json dictionary of verified spoken name/term corrections.
   Preserve real speech and word-level timings. Do not invent caption text.
8. Validate: python -m src.agent_cli validate --plan edit_plan.json
9. Render: python -m src.agent_cli render --plan edit_plan.json --corrections corrections.json
10. Inspect output MP4 and SRT, compare text to audio, fix errors and rerender.

The automatic selector is an offline transcript-based heuristic, not a full
multimodal reasoning model. External agents should make visual and narrative
decisions only from actual source evidence.

**For full schema, tool endpoints, quality requirements, constraints and
content-specific editing decisions, use AGENTS.md.**
