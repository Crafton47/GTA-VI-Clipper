# Antigravity Viral Clipper (`viral-clipper`)

A 100% free, zero-cost automated short-form video clipper built for **Google Antigravity IDE** (and CLI). Drop a YouTube, Twitch, or Kick link (or local video file), and it automatically finds the most viral moments, crops to 9:16 portrait (`stream` facecam+gameplay split, `face` smooth speaker tracking, or `fit` blurred background), adds a rounded Hook Title Bar, burns word-by-word animated TikTok/Shorts captions, normalizes audio to `-14 LUFS`, and writes ready-to-paste titles/hashtags in `POST.md`.

## What Was Upgraded & Fixed vs. Reference Repos

1. **100% Free AI Router (Zero Paid Locks)**:
   - Replaces `gta6-clipper`'s paid `claude -p` requirement, `openshorts`'s paid RapidAPI/fal.ai/ElevenLabs stack, and `autoshorts`'s paid Deepgram/DeepSeek defaults.
   - Built-in auto-failover across **OpenRouter Free Tier** (`nvidia/nemotron-3-ultra-550b-a55b:free`, `nvidia/nemotron-3.5-lightning:free`, `nvidia/nemotron-3.5-super-vl:free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `cohere/north-mini-code:free`, `openrouter/free`), **Google Gemini Free Tier** (`gemini-2.5-flash`, `gemini-2.0-flash`), **Groq Free Tier** (`llama-3.3-70b-versatile`), **NVIDIA NIM**, **Local Ollama**, and a **Zero-Key Acoustic + Hook-Phrase Ranker** fallback.
2. **Cross-Platform Windows, Linux & macOS Support**:
   - Fixes macOS-only font paths (`/System/Library/Fonts/...`) and BSD `df -g` checks so it runs natively on Windows (including Lenovo LOQ / NVIDIA GPUs via `h264_nvenc`), Linux, and macOS.
3. **Universal Niche Support**:
   - Works on **any** YouTube video or livestream (podcasts, tech/coding tutorials, commentary, gaming, or GTA 6 streams) plus local `.mp4`/`.mkv` files.

## Quick Start in Antigravity IDE

1. **Install the Skill into Antigravity**:
   - **Workspace scope**: Unzip or copy the `viral-clipper` folder into `<your-workspace>/.agents/skills/viral-clipper/`
   - **Global scope**: Copy into `~/.gemini/config/skills/viral-clipper/` (or `~/.agents/skills/viral-clipper/`)
2. **Run One-Time Setup**:
   ```bash
   python3 .agents/skills/viral-clipper/scripts/setup.py
   ```
3. **Add One Free API Key (Optional)**:
   Open `~/viral-clips/.env` and paste either a free [OpenRouter API key](https://openrouter.ai/settings/keys) (`OPENROUTER_API_KEY=...`) or a free [Google AI Studio Gemini key](https://aistudio.google.com/apikey) (`GEMINI_API_KEY=...`). Even without a key, the built-in acoustic + hook ranker works out of the box!
4. **Drop a Link in Antigravity**:
   Just tell Antigravity:
   > *"Clip this YouTube video for me: https://www.youtube.com/watch?v=..."*
   Or run directly from terminal:
   ```bash
   bash .agents/skills/viral-clipper/scripts/autoclip.sh "https://www.youtube.com/watch?v=..." --fast
   ```
