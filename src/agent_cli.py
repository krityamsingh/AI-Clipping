"""Model-neutral command line interface for autonomous video-editing agents.

python -m src.agent_cli --help
python -m src.agent_cli analyze --source raw/video.mp4 --output analysis.json
python -m src.agent_cli plan --analysis analysis.json --output edit_plan.json
python -m src.agent_cli render --plan edit_plan.json
python -m src.agent_cli auto --source raw/video.mp4 --parts 2
"""
import argparse
import json
import sys
from pathlib import Path

from src.agent_workflow import (analyze_source, build_auto_plan, read_json,
                                validate_plan, write_json)
from src.render_plan import render_plan


def make_parser():
    parser = argparse.ArgumentParser(
        description="AI-Clipping agent CLI: analyze, edit-plan, and render source video")
    cmds = parser.add_subparsers(dest="command", required=True)
    analyze = cmds.add_parser("analyze", help="Inspect original media and save a JSON report")
    analyze.add_argument("--source", required=True)
    analyze.add_argument("--output", default="analysis_report.json")
    analyze.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium"])
    analyze.add_argument("--duration", type=float, default=45)
    analyze.add_argument("--candidates", type=int, default=10)
    analyze.add_argument("--vocabulary", nargs="*", default=[])
    analyze.add_argument("--force", action="store_true")

    plan = cmds.add_parser("plan", help="Convert an analysis report into editable EDL JSON")
    plan.add_argument("--analysis", required=True)
    plan.add_argument("--output", default="edit_plan.json")
    plan.add_argument("--profile", default="general",
                      choices=["general", "podcast", "gaming", "talking_head", "tutorial"])
    plan.add_argument("--duration", type=float, default=45)
    plan.add_argument("--parts", type=int)
    plan.add_argument("--aspect", default="9:16", choices=["9:16", "16:9", "1:1"])
    plan.add_argument("--quality", default="final", choices=["final", "preview"])

    render = cmds.add_parser("render", help="Render exactly the shots in an agent edit plan")
    render.add_argument("--plan", required=True)
    render.add_argument("--output-dir")
    render.add_argument("--corrections", help="JSON dict mapping observed errors to corrected phrases")

    auto = cmds.add_parser("auto", help="Analyze, plan and render in one command")
    auto.add_argument("--source", required=True)
    auto.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium"])
    auto.add_argument("--profile", default="general",
                      choices=["general", "podcast", "gaming", "talking_head", "tutorial"])
    auto.add_argument("--duration", type=float, default=45)
    auto.add_argument("--parts", type=int)
    auto.add_argument("--aspect", default="9:16", choices=["9:16", "16:9", "1:1"])
    auto.add_argument("--quality", default="final", choices=["final", "preview"])
    auto.add_argument("--output-dir")
    auto.add_argument("--vocabulary", nargs="*", default=[])
    auto.add_argument("--corrections", help="Explicit phrase corrections JSON file")

    frames = cmds.add_parser("frames", help="Extract real video frames for vision agents")
    frames.add_argument("--analysis", required=True)
    frames.add_argument("--output-dir", default="previews/agent_frames")
    frames.add_argument("--max-frames", type=int, default=24)
    frames.add_argument("--width", type=int, default=480)

    verify = cmds.add_parser("validate", help="Validate an agent-created plan without rendering")
    verify.add_argument("--plan", required=True)
    return parser


def _corrections(path):
    if not path:
        return {}
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("Corrections file must contain an object")
    return payload


def run(argv=None):
    args = make_parser().parse_args(argv)
    if args.command == "analyze":
        report = analyze_source(args.source, args.model, args.duration,
                                args.candidates, args.vocabulary, args.force)
        write_json(args.output, report)
        result = {"status": "analyzed", "output": str(Path(args.output).resolve()),
                  "candidates": len(report["candidate_highlights"]),
                  "caption_review_flags": len(report["caption_review_flags"])}
    elif args.command == "plan":
        plan = build_auto_plan(read_json(args.analysis), profile=args.profile,
                               target_duration=args.duration, max_parts=args.parts,
                               aspect_ratio=args.aspect, quality=args.quality)
        write_json(args.output, plan)
        result = {"status": "planned", "output": str(Path(args.output).resolve()),
                  "parts": len(plan["parts"])}
    elif args.command == "render":
        plan = read_json(args.plan)
        plan.setdefault("caption_corrections", {}).update(_corrections(args.corrections))
        result = render_plan(plan, args.output_dir)
    elif args.command == "frames":
        from src.visual_sampler import sample_frames
        result = sample_frames(read_json(args.analysis), args.output_dir,
                               max_frames=args.max_frames, width=args.width)
    elif args.command == "validate":
        plan = validate_plan(read_json(args.plan))
        result = {"status": "valid", "parts": len(plan["parts"])}
    else:
        report = analyze_source(args.source, args.model, args.duration,
                                max(10, args.parts or 4), args.vocabulary)
        plan = build_auto_plan(report, profile=args.profile,
                               target_duration=args.duration, max_parts=args.parts,
                               aspect_ratio=args.aspect, quality=args.quality)
        plan["caption_corrections"] = _corrections(args.corrections)
        output = Path(args.output_dir or "export")
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "analysis_report.json", report)
        write_json(output / "edit_plan.json", plan)
        result = render_plan(plan, output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    try:
        run()
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}), file=sys.stderr)
        sys.exit(1)
