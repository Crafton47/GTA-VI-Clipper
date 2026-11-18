"""Settings and environment loader for viral-clipper.
Defaults below; override any setting in ~/viral-clips/config.json or via CLI flags.
API keys can be placed in .env (current folder, skill folder, or ~/viral-clips/.env).
"""

import json
import os
import platform
from pathlib import Path

HOME = Path.home() / "viral-clips"
LEGACY_HOME = Path.home() / "gta6-clips"


def _find_hook_font():
    """Find a bold sans-serif TTF font across Windows, macOS, and Linux."""
    candidates = [
        # Windows (Lenovo LOQ / standard Windows 10/11)
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        # macOS
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        # Linux (Ubuntu / Debian / Arch / Fedora)
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSans-Bold.ttc",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return candidates[0]


def _find_ass_font_name():
    """Choose a clean bold font family name that libass resolves on each OS."""
    sys_name = platform.system().lower()
    if sys_name == "windows" or sys_name == "darwin":
        return "Arial Black"
    return "DejaVu Sans"


DEFAULTS = {
    # --- finding streams / videos ---
    "game": "Grand Theft Auto VI",   # Twitch category name (optional official API)
    "search": "GTA 6",               # Default search query for --find
    "title_words": [],               # Optional filter keywords for --find (empty = allow any topic)
    "max_age_hours": 48,             # Ignore watchlist VODs older than this
    "topic": "auto",                 # "auto" adapts to any YouTube video/stream topic, or set e.g. "GTA 6"

    # --- download ---
    "max_height": 1080,

    # --- listening to the video/stream (100% local & free via faster-whisper) ---
    "scan_model": "tiny",            # Fast pass over the full audio
    "caption_model": "base",         # High-accuracy pass over each chosen clip for word verification & captions
    "language": None,                # None = auto-detect language (auto-locks "hi" for Hindi streamers)
    "scan_block_minutes": 20,        # Decode audio in 20-min blocks so multi-hour videos use minimal RAM
    "loud_db": 5.0,                  # Audio spike threshold in dB above 2-min rolling median
    "chat": True,                    # YouTube replays: count chat messages per 5s
    "chat_timeout": 420,

    # --- picking viral moments (100% FREE AI Providers + Adaptive Scene Duration) ---
    "clips_per_stream": 4,
    "min_duration": None,            # None = 100% adaptive to each moment's full natural arc (never forces a fixed min!)
    "max_duration": 59,              # Standard 60s YouTube Shorts / Reels vertical ceiling
    "chunk_minutes": 12,             # Transcript window per LLM call
    "llm_parallel": 2,               # Parallel calls (kept at 2 to respect free-tier 15-20 RPM limits)
    "llm_provider": "auto",          # auto | experiential | openrouter | gemini | codecraft | groq | nvidia | ollama | claude | heuristic
    "llm_model": None,               # Optional override for specific model ID
    "experiential_models": [
        "qwen3.8-27b",
        "deepseek-v4-flash",
        "claude-haiku-5.5",
        "gpt-6-luna",
    ],
    "codecraft_models": [
        "deepseek-v4-flash-0731",
        "qwen3.8-27b",
        "gpt-5.6-luna",
        "gemini-3.7-flash",
    ],
    "openrouter_models": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3.5-lightning:free",
        "nvidia/nemotron-3.5-super-vl:free",
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "cohere/north-mini-code:free",
        "openrouter/free",
    ],
    "gemini_models": [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ],
    "groq_model": "llama-3.3-70b-versatile",
    "nvidia_model": "nvidia/llama-3.3-nemotron-super-49b-v1",
    "ollama_model": "qwen2.5:7b",
    "ollama_url": "http://localhost:11434",

    # --- framing (9:16 portrait — FING Plays / Streamer Split Default) ---
    "layout": "auto",                # auto | stream | face | fit
    "output_width": 1080,
    "output_height": 1920,
    "cam_height": 800,               # Top ~42% facecam panel (800px), bottom ~58% gameplay (1120px) like FING Plays Shorts
    "fit_aspect": 1.7778,            # fit layout: aspect ratio over blurred background
    "track_smoothing": 5,

    # --- hook bar (FING Plays GTA 6 Sunset-Gradient Seam Banner default) ---
    "hook_style": "gta6_seam",       # gta6_seam (vibrant orange->pink->purple seam banner) | classic_white
    "hook_font_file": _find_hook_font(),
    "hook_font_size": 52,
    "hook_y": 0.09,
    "hook_margin_x": 70,

    # --- captions (Clean unobstructed gameplay by default like FING Plays reference Shorts; enable with --captions) ---
    "burn_captions": False,          # False = clean gameplay + native game subtitles (like hwyOH_kqBX8 & YD4xQw0QtHk); True = burn word-by-word pop captions
    "font": _find_ass_font_name(),
    "font_size": 76,
    "words_per_group": 3,
    "uppercase": True,
    "text_color": "FFFFFF",
    "highlight_color": "FFE13B",
    "outline_width": 6,
    "caption_y": 0.72,
    "word_pop": True,
    "caption_style": "classic",      # classic | box | karaoke | minimal | bold | comic
    "ai_caption_check": False,

    # --- encoding ---
    "encoder": "libx264",            # auto-switches to h264_nvenc / h264_videotoolbox with --fast
    "crf": 20,
    "preset": "medium",
    "audio_bitrate": "192k",
    "loudnorm": True,
}


def load_env():
    """Load environment variables from .env files without requiring python-dotenv."""
    vals = dict(os.environ)
    skill_root = Path(__file__).resolve().parent.parent.parent
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        skill_root / ".env",
        skill_root / "env.example.txt",
        skill_root.parent / ".env",
        skill_root.parent.parent / ".env",
        skill_root.parent.parent.parent / ".env",
        HOME / ".env",
        LEGACY_HOME / ".env",
        Path.home() / ".viral-clipper" / ".env",
    ]
    for env_file in candidates:
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and v:
                        vals.setdefault(k, v)
                        os.environ.setdefault(k, v)
            except OSError:
                pass
    return vals


def load(overrides=None):
    load_env()
    cfg = dict(DEFAULTS)
    for cfg_dir in (HOME, LEGACY_HOME):
        path = cfg_dir / "config.json"
        if path.exists():
            try:
                cfg.update(json.loads(path.read_text(encoding="utf-8")))
                break
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path} is not valid JSON: {exc}")
    for key, value in (overrides or {}).items():
        if value is not None:
            cfg[key] = value
    return cfg
