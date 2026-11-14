#!/usr/bin/env bash
# Run locally: ./scripts/create_gta6_short.sh [optional-source.mp4]
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python3"
[[ -x "$PYTHON" ]] || { echo 'Missing project .venv' >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo 'Missing FFmpeg' >&2; exit 1; }
command -v ffprobe >/dev/null || { echo 'Missing FFprobe' >&2; exit 1; }
mkdir -p raw previews export

INPUT="${1:-https://www.youtube.com/watch?v=EDaMIIk8oGk}"
if [[ -f "$INPUT" ]]; then
  SOURCE="$(realpath "$INPUT")"
else
  "$PYTHON" -c 'import yt_dlp' || { echo 'Install yt-dlp into the project .venv first.' >&2; exit 1; }
  RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
  TEMPLATE="$ROOT/raw/gta6_${RUN_ID}.%(ext)s"
  OPTIONS=(--no-playlist --merge-output-format mp4 --format 'bv*[height<=720]+ba/b[height<=720]/b')
  if [[ -n "${YT_BROWSER:-}" ]]; then
    OPTIONS+=(--cookies-from-browser "$YT_BROWSER")
  fi
  if ! "$PYTHON" -m yt_dlp "${OPTIONS[@]}" -o "$TEMPLATE" "$INPUT"; then
    echo 'YouTube blocked the download. Try locally with:' >&2
    echo 'YT_BROWSER=chrome bash scripts/create_gta6_short.sh' >&2
    echo 'Or download the MP4 yourself and supply its path.' >&2
    exit 1
  fi
  SOURCE=""
  for candidate in "$ROOT"/raw/gta6_"${RUN_ID}".*; do
    if [[ -f "$candidate" ]]; then SOURCE="$candidate"; break; fi
  done
  [[ -n "$SOURCE" ]] || { echo 'yt-dlp produced no file.' >&2; exit 1; }
fi

ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$SOURCE" | grep -q . || {
  echo 'No valid video stream in source file.' >&2; exit 1;
}

MARKER="$(mktemp -p "$ROOT/previews" .clip-start-XXXXXXXX)"
trap 'rm -f "$MARKER"' EXIT
"$PYTHON" main.py "$SOURCE" --num-clips 1 --duration 30 --aspect 9:16 --layout blur_fill --quality preview --model tiny
CLIP="$(find "$ROOT/previews" -maxdepth 1 -type f -name '*.mp4' -newer "$MARKER" -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
[[ -n "$CLIP" && -s "$CLIP" ]] || { echo 'No newly rendered clip.' >&2; exit 1; }
DEST="$ROOT/export/GTA6_AI_Clipper_Short_$(date +%Y%m%d_%H%M%S).mp4"
cp -- "$CLIP" "$DEST"
ffmpeg -v error -i "$DEST" -f null - || { rm -f "$DEST"; echo 'Export validation failed.' >&2; exit 1; }
printf '\nVerified MP4: %s\n' "$DEST"
ffprobe -v error -show_entries format=duration -show_entries stream=width,height,codec_name -of json "$DEST"
