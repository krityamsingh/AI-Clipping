#!/usr/bin/env bash
# Launch AI Video Clipping Engine Web Interface
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "=========================================================="
echo " Starting AI Video Clipping Engine Web Interface"
echo " Workspace: $DIR"
echo " Local UI:  http://127.0.0.1:8000"
echo "=========================================================="

"$DIR/.venv/bin/python3" "$DIR/main.py" --web --host 127.0.0.1 --port 8000
