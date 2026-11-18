#!/usr/bin/env python3
"""Cross-platform one-time setup for Antigravity Viral Clipper (Windows, Linux, macOS).
Creates a private Python environment in ~/.viral-clipper/venv, installs free open-source
packages (faster-whisper, opencv-python-headless, pillow, numpy, yt-dlp), downloads
Whisper tiny+base models and the OpenCV YuNet facecam detector, and creates ~/viral-clips/.env.
"""

import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ENV_DIR = Path.home() / ".viral-clipper"
VENV_DIR = ENV_DIR / "venv"
CLIPS_HOME = Path.home() / "viral-clips"
HERE = Path(__file__).resolve().parent

IS_WIN = platform.system().lower() == "windows"
VENV_PY = VENV_DIR / ("Scripts/python.exe" if IS_WIN else "bin/python")

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


def ok(msg):
    print(f"  [OK] {msg}")


def warn(msg):
    print(f"  [!]  {msg}")


def fail(msg):
    print(f"  [X]  {msg}")


def main():
    print("=== Antigravity Viral Clipper: Zero-Cost Setup ===")
    missing = False

    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        ok("ffmpeg & ffprobe found on PATH")
    else:
        fail("ffmpeg/ffprobe missing! Install via: winget install Gyan.FFmpeg (Windows) | sudo apt install ffmpeg (Linux) | brew install ffmpeg (macOS)")
        missing = True

    if any(shutil.which(js) for js in ("node", "deno", "bun")):
        ok("JavaScript runtime found (node/deno/bun for yt-dlp YouTube extraction)")
    else:
        warn("No node/deno/bun found; installing node or deno is recommended for YouTube extraction")

    ENV_DIR.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(ENV_DIR).free / 1e9
    if free_gb >= 2.0:
        ok(f"Disk space: {free_gb:.1f} GB free")
    else:
        fail(f"Only {free_gb:.1f} GB free; at least 2 GB required")
        missing = True

    if missing:
        sys.exit(1)

    if not VENV_PY.exists():
        print("Creating isolated Python virtual environment in ~/.viral-clipper/venv ...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    pkgs = ["faster-whisper", "opencv-python-headless<5", "pillow", "numpy", "yt-dlp"]
    print("Installing Python packages (faster-whisper, opencv-python-headless, pillow, numpy, yt-dlp)...")
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "-U", "pip"], check=True)
    subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "-U", *pkgs], check=True)
    ok("Python dependencies installed in ~/.viral-clipper/venv")

    print("Pre-downloading local Whisper models (tiny for fast scanning, base for word-by-word captions)...")
    whisper_check = (
        "from faster_whisper import WhisperModel\n"
        "for m in ('tiny', 'base'): WhisperModel(m, device='cpu', compute_type='int8')\n"
    )
    subprocess.run([str(VENV_PY), "-c", whisper_check], check=True)
    ok("Local Whisper models ('tiny' & 'base') ready")

    models_dir = ENV_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    yunet_path = models_dir / "yunet.onnx"
    if not yunet_path.exists() or yunet_path.stat().st_size < 10000:
        try:
            urllib.request.urlretrieve(YUNET_URL, str(yunet_path))
            ok("OpenCV YuNet facecam detector (0.2 MB) downloaded")
        except Exception as exc:
            warn(f"YuNet download skipped ({exc}); OpenCV Haar fallback will be used")
    else:
        ok("OpenCV YuNet facecam detector ready")

    CLIPS_HOME.mkdir(parents=True, exist_ok=True)
    streamers_dst = CLIPS_HOME / "streamers.txt"
    streamers_src = HERE.parent / "streamers.txt"
    if not streamers_dst.exists() and streamers_src.exists():
        shutil.copy(streamers_src, streamers_dst)
    ok(f"Watchlist ready at {streamers_dst}")

    env_dst = CLIPS_HOME / ".env"
    env_example = HERE.parent / ".env.example"
    if not env_dst.exists() and env_example.exists():
        shutil.copy(env_example, env_dst)
        ok(f"Created free API config template at {env_dst}")

    print("\nAll set! Drop any YouTube link to generate 9:16 viral clips:")
    print(f'  python "{HERE / "run.py"}" <YOUTUBE_URL>')


if __name__ == "__main__":
    main()
