---
name: viral-clipper
description: Automated zero-cost viral video and stream clipper for Antigravity. Takes any YouTube, Twitch, or Kick link (or local video file), downloads audio first, transcribes locally with faster-whisper, detects audio loudness spikes and live chat velocity, picks the highest-retention viral moments using 100% free AI models (OpenRouter free Nemotron 3 Ultra/Lightning, Google Gemini Free Tier, Groq, NVIDIA NIM, local Ollama, or built-in acoustic ranker), and renders ready-to-post 9:16 vertical clips (1080x1920) with smart facecam/face-tracking/blurred-fit framing, rounded hook title bars, word-by-word pop captions, and a POST.md sheet. Use whenever the user drops a YouTube or stream link and asks to clip it, find viral moments, generate Shorts/Reels/TikToks, or automate video clipping.
---

# Viral Clipper

Drop a YouTube, Twitch, or Kick link (or a local video path) and get ready-to-post 9:16 vertical Shorts, Reels, and TikToks at $0 cost.

## Summary

This skill runs a complete, zero-cost automated clipping pipeline (`scripts/autoclip` or `python3 scripts/run.py`) inspired by OpenShorts, AutoShorts, and gta6-clipper, with all paid API locks and OS-specific bugs removed. Everything runs locally via `yt-dlp`, `ffmpeg`, `faster-whisper`, OpenCV YuNet face detection, and free LLM APIs (or zero-key offline heuristics).

## When to Use

- The user drops one or more YouTube, Twitch, or Kick URLs and wants viral vertical clips generated automatically.
- The user asks to extract Shorts, TikToks, or Reels from a long-form video, podcast, tutorial, or livestream.
- The user wants to discover and clip today's top trending streams for a game or topic (`--find`).
- The user provides a local `.mp4` or `.mkv` recording and wants automated 9:16 reframing, hook title overlays, and animated word-by-word captions.

## Steps

### 1. First-Time Setup Check

Before running the clipper on a new machine, check if `~/.viral-clipper/venv` exists. If not, run the cross-platform setup script once:

```bash
python3 SKILL/scripts/setup.py
```

This verifies `ffmpeg` and `ffprobe`, creates an isolated virtual environment in `~/.viral-clipper/venv`, installs `faster-whisper`, `opencv-python-headless`, `pillow`, `numpy`, and `yt-dlp`, pre-downloads the `tiny` and `base` Whisper models plus the OpenCV YuNet face detector (`0.2 MB`), and creates `~/viral-clips/.env`.

### 2. Configure a Free AI Provider (Optional, Zero-Key Mode Built In)

The moment selector supports multiple 100% free providers and automatically picks the first available key in `.env` (or `~/viral-clips/.env`):

- **Experiential Labs (`EXPLABS_API_KEY`)**: Uses `https://api.experientiallabs.ai/v1/chat/completions` with 100%-off ($0) models (`qwen3.8-27b`, `deepseek-v4-flash`, `claude-haiku-5.5`, `gpt-6-luna`) plus the $4 free launch grant.
- **CodeCraft API (`CODECRAFT_API_KEY`)**: Uses `https://codecraftapi.com/v1/chat/completions` (`deepseek-v4-flash-0731`, `qwen3.8-27b`, `gpt-5.6-luna`, `gemini-3.7-flash`).
- **OpenRouter Free Tier (`OPENROUTER_API_KEY`)**: Uses verified `$0/token` `:free` models with automatic fallback across `nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `cohere/north-mini-code:free`, and `openrouter/free`.
- **Google Gemini Free Tier (`GEMINI_API_KEY`)**: Uses Google AI Studio's free tier (`gemini-2.5-flash` and `gemini-2.0-flash`).
- **Groq Free Tier (`GROQ_API_KEY`)**: Uses `llama-3.3-70b-versatile`.
- **NVIDIA NIM Free API (`NVIDIA_API_KEY`)**: Uses `nvidia/llama-3.3-nemotron-super-49b-v1`.
- **Local Ollama (`http://localhost:11434`)**: Uses local `qwen2.5:7b` or `llama3.2` when Ollama is running.
- **Built-in Zero-API Heuristic (`--provider heuristic`)**: If no API key is set or all free endpoints hit rate limits, the clipper automatically falls back to acoustic loudness spikes (`[LOUD +NdB]`), chat velocity (`[CHAT xN]`), and hook-phrase density so clip generation never fails.

### 3. Run the Automated Clipper Pipeline

When the user drops a link, execute the clipper directly:

```bash
# Clip a single YouTube video or stream (generates 3 vertical clips by default)
bash SKILL/scripts/autoclip.sh "https://www.youtube.com/watch?v=VIDEO_ID"

# On Windows PowerShell / CMD:
SKILL\scripts\autoclip.bat "https://www.youtube.com/watch?v=VIDEO_ID"

# Clip multiple links in parallel with 4 clips per video and GPU hardware encoding
bash SKILL/scripts/autoclip.sh URL1 URL2 --clips 4 --fast

# Force a specific free provider or model
bash SKILL/scripts/autoclip.sh URL --provider openrouter --model "nvidia/nemotron-3-ultra-550b-a55b:free"
bash SKILL/scripts/autoclip.sh URL --provider gemini

# Clip a LIVE stream right now (captures a bounded 10-min live window instead of waiting for stream to end)
bash SKILL/scripts/autoclip.sh LIVE_URL --live-minutes 10 --fast

# Continuously watch a LIVE stream in rolling 5-min windows and generate clips in real time
bash SKILL/scripts/autoclip.sh LIVE_URL --watch-live --live-minutes 5 --live-rounds 12 --fast

# Clip only a specific time range of a long VOD (downloads ONLY that audio section)
bash SKILL/scripts/autoclip.sh URL --section "0:30:00-0:50:00" --fast

# Find and clip today's top streams for a topic
bash SKILL/scripts/autoclip.sh --find --topic "GTA 6" --streams 5

# Initialize the Faceless Clipping Page workspace (playbook.md, facts.md, idea-bank.md, scoreboard.csv, media/edits/)
bash SKILL/scripts/autoclip.sh --init-page

# Generate today's 6-Slot Daily Content Queue (News, HOW TO tip, Nostalgia, Spotlight, Countdown, Question)
bash SKILL/scripts/autoclip.sh --daily-pack

# Clip with tight 7-30s Reels/TikTok trim + auto-log to scoreboard.csv and page/media/edits/
bash SKILL/scripts/autoclip.sh URL --tight --fast

# Run the Learning Loop review on scoreboard.csv to update learning.md
bash SKILL/scripts/autoclip.sh --review

```

### 4. How the Pipeline Processes Each Video

1. **Zero-Download Instant Transcript & Heatmap (`fetch.py`)**: For YouTube videos and replays, fetches YouTube's word-timed `json3` transcript (`yt-dlp --skip-download --sub-format json3`) and Most Replayed `heatmap` spikes in ~2 seconds with **0 MB of full stream audio/video downloaded**. (Falls back to audio download + local `faster-whisper` `tiny` only if a video has no captions or `--full-audio` is passed.)
3. **Viral Moment Selection (`moments.py`)**: Splits the annotated transcript into 12-minute windows and queries the free AI router (with automatic failover to the acoustic ranker) to pick standalone 15-60s viral clips, snapping timestamps to exact spoken word edges.
4. **Targeted Video Slice & Frame Alignment (`render.py`)**: Downloads only the 15-60s video segments for the chosen clips (`yt-dlp --download-sections`), aligns audio to the exact frame via cross-correlation, and runs `faster-whisper` (`base`) for exact word-level timestamps.
5. **Smart 9:16 Auto-Layout (`layout.py`)**: Samples frames with OpenCV YuNet face detection and chooses the optimal vertical look per scene:
   - `stream`: Small corner facecam detected -> crops facecam into top panel (`1080x760`) and gameplay/content into bottom panel (`1080x1160`).
   - `face`: Large talking face detected (podcasts, interviews, vlogs) -> smooth dynamic 9:16 crop tracking the speaker.
   - `fit`: No face or multi-face wide shot -> full 16:9 frame centered over a darkened, Gaussian-blurred 9:16 background.
6. **Hook Bar, Word-by-Word Pop Captions & Mastering (`hook.py`, `captions.py`)**: Renders a rounded white hook banner at the top seam, burns animated word-by-word `.ass` captions (`#FFE13B` active word pop highlight), normalizes loudness to `-14 LUFS`, and writes `POST.md` (ready-to-paste captions and hashtags) plus `clips.json` in `~/viral-clips/<date>/<creator>__<title>/`.

### 5. Verify and Present Output

After the command finishes:

- Check `~/viral-clips/<date>/<creator>__<title>/` for the generated `.mp4` clips and `POST.md`.
- Present the output file paths, virality scores, hook titles, and ready-to-paste captions from `POST.md` to the user.

## Gotchas

- **Age-restricted YouTube videos or Kick streams**: Pass `--cookies chrome` (or `edge`, `brave`, `firefox`) so `yt-dlp` uses the browser's signed-in session.
- **OpenRouter free tier rate limits**: OpenRouter caps `:free` models at 20 requests per minute and 50 requests per day on accounts with $0 credit history. Keep `llm_parallel` at `2` (the default), and let `moments.py` auto-rotate across its 6 verified `:free` model IDs or fall back to `GEMINI_API_KEY`.
- **Hardware encoding (`--fast`)**: Automatically detects `h264_nvenc` on NVIDIA GPUs (Windows/Linux), `h264_videotoolbox` on Apple Silicon Macs, or `h264_qsv` / `h264_amf`, falling back cleanly to `libx264` if no GPU encoder is present.
