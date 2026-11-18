#!/bin/bash
# Cross-platform setup wrapper for Antigravity Viral Clipper (Linux, macOS, Windows Git Bash / WSL)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$HERE/setup.py" "$@"
else
  exec python "$HERE/setup.py" "$@"
fi
