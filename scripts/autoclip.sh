#!/bin/bash
# Cross-platform launcher for autoclip / gta6clip.
# Uses ~/.viral-clipper/venv (or ~/.gta6-clipper/venv) if set up, else falls back to system python3.
HERE="$(cd "$(dirname "$0")" && pwd)"
for VENV_PY in "$HOME/.viral-clipper/venv/bin/python" "$HOME/.viral-clipper/venv/Scripts/python.exe" "$HOME/.gta6-clipper/venv/bin/python"; do
  if [ -x "$VENV_PY" ]; then
    export PATH="$(dirname "$VENV_PY"):$PATH"
    exec "$VENV_PY" "$HERE/run.py" "$@"
  fi
done
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$HERE/run.py" "$@"
else
  exec python "$HERE/run.py" "$@"
fi
