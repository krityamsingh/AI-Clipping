#!/usr/bin/env bash
# Execute Full Test Suite
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

echo "=========================================================="
echo " Running AI Video Clipping Engine Verification Test Suite"
echo "=========================================================="

"$DIR/.venv/bin/python3" -m unittest discover -s tests -p "test_regressions.py" -v

echo ""
"$DIR/.venv/bin/python3" "$DIR/tests/test_environment.py"
echo ""
"$DIR/.venv/bin/python3" "$DIR/tests/test_tts.py"
echo ""
"$DIR/.venv/bin/python3" "$DIR/tests/test_whisper.py"
echo ""
"$DIR/.venv/bin/python3" "$DIR/tests/test_scenedetect.py"
echo ""
"$DIR/.venv/bin/python3" "$DIR/tests/test_web.py"
echo ""
"$DIR/.venv/bin/python3" "$DIR/tests/test_end_to_end.py"
echo ""
echo "=========================================================="
echo " ✅ ALL SYSTEM TESTS PASSED SUCCESSFULLY!"
echo "=========================================================="
