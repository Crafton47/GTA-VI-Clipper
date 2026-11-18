"""Pick the moments worth clipping using 100% FREE AI providers.

Fixes the 3 classic clipping flaws:
1. Non-Verbal Action & Scream Visibility: `_lines()` emits `[LOUD +NdB] [SCREAM / INTENSE REACTION / NON-VERBAL ACTION]`
   even during seconds where Whisper/YouTube captions have zero spoken words (e.g., falling in Only Up, screaming,
   soundboard noises, or speechless shock).
2. Setup -> Climax -> Hard Cut Timing: Prompts the AI to start 6-12s BEFORE the reaction so the viewer sees what caused it,
   and cut immediately (1-2s) after the payoff instead of trailing into unrelated chat filler.
3. Smart Boundary Snapping (`_snap()`): Never deletes pre-speech build-up/screams at the start of a clip, and if a clip
   is shorter than `min_duration`, expands BACKWARD into the setup rather than forward into dead post-payoff chatter.
"""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from .util import clean_env, log

UNIVERSAL_PROMPT = """You are an elite viral short-form video editor for YouTube Shorts, TikTok, and Instagram Reels.
This is an excerpt from a stream or video by "{streamer}", titled "{title}".{topic_hint}

Below is a timestamped timeline (seconds). It includes spoken words AND acoustic/audience markers:
- [LOUD +NdB] audio jumped N dB above the surrounding 2-minute baseline (screaming, raging, laughing, soundboard, explosion)
- [NON-VERBAL SCREAM / ACTION SPIKE] loud audio or intense game moment where the streamer is screaming, speechless, or reacting without words
- [DRAMATIC SILENCE / SHOCK] quiet build-up or speechless shock right before/after a huge moment
- [CHAT xN] live chat moved N times faster than normal

Find the {want} STRONGEST standalone viral clips in this excerpt.

HINDI / HINGLISH & DESI STREAMER INTELLIGENCE (CarryisLive, Mortal, Samay Raina, GamerFleet, Triggered Insaan, etc.):
- Many transcripts are in Romanized Hindi (Hinglish), e.g., "lady ko dekhne jaata hoon", "gussa shaant ho jaata hai", "ek do teen... दस", "abey kya hai!", "arey bhai!", "gaya bhai gaya!".
- In Hindi streams, the essence of a viral clip is the FULL COMEDIC ARC:
  1. THE DESI STORY / SARCASTIC SETUP: Start where the streamer begins explaining the funny story, trick, or confident claim (e.g., "woh kehti hai gusse mein 1 se 10 tak gina karo...").
  2. THE ESCALATION: Keep the tension where they try it in-game (e.g., counting "1 2 3 4 5 6 7 8 9 10" faster and faster as everything goes wrong).
  3. THE RAGE / PUNCHLINE EXPLOSION: Capture the full scream/rage ("ABEY KYA HAI! KYA HAI!") and cut 1.5s right after the explosion ends!
- Write `hook_text` so it specifically names the funny setup/joke from the clip (e.g., "Carry's 1-to-10 Gussa Trick FAILS Instantly 😭" or "Carry Tries to Control His ANGER in Getting Over It 💀") — NEVER use a generic hook like "Loses It at This Moment"!

CRITICAL VIRAL EDITING RULES (DO NOT VIOLATE):
1. CAPTURE THE CAUSE + THE REACTION (NEVER START LATE):
   - Never start a clip on the apology or aftermath (e.g., NEVER start on "I thought that was a soundboard" AFTER the soundboard already happened!).
   - Always set `start` 6 to 12 seconds BEFORE the `[LOUD +NdB]` scream, soundboard, fail, or realization so the viewer sees the build-up and the exact moment it happens!
2. HARD CUT RIGHT AFTER THE PAYOFF (NO BORING TAIL FILLER):
   - End the clip 1 to 2 seconds after the peak scream, laugh, or punchline finishes.
   - NEVER include boring post-moment filler where the streamer moves on (e.g., reading random game chat, "somebody just texted me...", menus, or changing the subject).
3. NON-VERBAL MOMENTS ARE GOLD:
   - A streamer falling in a game in stunned silence and then screaming (`[LOUD +15dB] [NON-VERBAL SCREAM / ACTION SPIKE]`) is a 95+ score viral clip even if they barely speak words!

Rules:
- `start` and `end` must be seconds inside {lo:.0f}-{hi:.0f}, between {min_d} and {max_d} seconds long, with no overlaps.
- Return ONLY a valid JSON array (no markdown prose outside JSON):
[{{"start": 120.0, "end": 146.5, "kind": "reaction",
  "title": "short_slug_name",
  "hook_text": "{streamer} Loses Everything in ONE Second 😭",
  "caption": "Engaging post caption that drives comments (under 150 chars)",
  "hashtags": ["#shorts", "#viral", "#fyp"],
  "score": 93,
  "reason": "Starts on the tense jump build-up, captures the full fall and +16dB scream, and cuts right after the reaction."}}]

TRANSCRIPT & AUDIO TIMELINE:
{transcript}
"""


def _lines(words, loud, chat, cfg, line_seconds=5):
    """Build a continuous ~5s timeline that includes BOTH spoken words AND non-verbal
    scream/action spikes or speechless tension gaps so the AI never misses non-spoken moments!
    """
    chat_base = float(np.median([c for c in chat if c > 0])) if chat and any(chat) else 0
    max_t_words = words[-1]["e"] if words else 0.0
    max_t_loud = float(len(loud)) if loud is not None and len(loud) else 0.0
    total_t = max(max_t_words, max_t_loud)
    if total_t <= 0:
        return []

    first_t = min(words[0]["s"], 0.0) if words else 0.0
    lines = []
    # Index words into 5-second buckets
    t_cursor = first_t
    w_idx = 0
    n_words = len(words)

    while t_cursor < total_t:
        t0 = t_cursor
        t1 = min(total_t, t0 + line_seconds)
        t_cursor = t1

        bucket_words = []
        while w_idx < n_words and words[w_idx]["s"] < t1:
            if words[w_idx]["e"] >= t0:
                bucket_words.append(words[w_idx]["w"])
            w_idx += 1

        tags = []
        peak_db = 0.0
        min_db = 0.0
        if loud is not None and len(loud):
            a, b = int(max(0, t0)), max(int(t0) + 1, int(min(len(loud), np.ceil(t1))))
            if b > a:
                seg_loud = loud[a:b]
                peak_db = float(np.max(seg_loud))
                min_db = float(np.min(seg_loud))
                if peak_db >= cfg["loud_db"]:
                    tags.append(f"[LOUD +{peak_db:.0f}dB]")

        if chat_base > 0 and chat:
            ca, cb = int(t0 // 5), int(t1 // 5) + 2
            seg_chat = chat[ca:cb]
            if seg_chat:
                ratio = max(seg_chat) / chat_base
                if ratio >= 2.2:
                    tags.append(f"[CHAT x{ratio:.1f}]")

        text = " ".join(bucket_words).strip()
        if not text:
            # Non-verbal window! Expose screams, action spikes, or tense silences explicitly
            if peak_db >= cfg["loud_db"] + 2.0:
                text = "[NON-VERBAL SCREAM / INTENSE AUDIO REACTION / GAMEPLAY CLIMAX]"
            elif peak_db >= cfg["loud_db"]:
                text = "[LOUD GAMEPLAY / LAUGHTER / SOUNDBOARD / REACTION]"
            elif tags:
                text = "[AUDIENCE / CHAT REACTION SPIKE]"
            else:
                # Skip unremarkable empty silence buckets to save tokens, unless adjacent to a spike
                near_spike = False
                if loud is not None and len(loud):
                    na = int(max(0, t0 - 10))
                    nb = int(min(len(loud), t1 + 10))
                    if nb > na and float(np.max(loud[na:nb])) >= cfg["loud_db"] + 1.5:
                        near_spike = True
                if near_spike:
                    text = "[TENSE BUILD-UP / SPEECHLESS SHOCK]"
                else:
                    continue

        prefix = (" ".join(tags) + " ") if tags else ""
        lines.append((round(t0, 1), prefix + text))

    return lines


def _http_json(url, payload, headers, timeout=90):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Antigravity-ViralClipper/3.0", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ask_openai_models(url, key, models, prompt):
    headers = {"Authorization": f"Bearer {key}"}
    last_err = None
    for model in models:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return ONLY a valid JSON array of clip objects. No markdown prose."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.25,
            "max_tokens": 8192,
        }
        try:
            data = _http_json(url, payload, headers, timeout=90)
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or msg.get("reasoning") or ""
                if content.strip():
                    return content
        except Exception as exc:
            last_err = f"{model} -> {exc}"
            continue
    raise RuntimeError(f"Endpoint {url} failed ({last_err})")


def _ask_openrouter(prompt, cfg):
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    models = [cfg["llm_model"]] if cfg.get("llm_model") else list(cfg["openrouter_models"])
    headers = {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://antigravity.google",
        "X-Title": "Antigravity Viral Clipper",
    }
    last_err = None
    for idx, model in enumerate(models):
        fallbacks = [m for m in models[idx:] if m][:3]
        payload = {
            "model": model,
            "models": fallbacks,
            "messages": [
                {"role": "system", "content": "Return ONLY a valid JSON array of clip objects. No markdown prose."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.25,
            "max_tokens": 8192,
        }
        try:
            data = _http_json("https://openrouter.ai/api/v1/chat/completions", payload, headers, timeout=90)
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or msg.get("reasoning") or ""
                if content.strip():
                    return content
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")[:200]
            last_err = f"{model} -> HTTP {exc.code}: {body}"
            if exc.code in (429, 502, 503):
                time.sleep(1.2)
            continue
        except Exception as exc:
            last_err = f"{model} -> {exc}"
            continue
    raise RuntimeError(f"OpenRouter free models exhausted ({last_err})")


def _ask_gemini(prompt, cfg):
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    models = [cfg["llm_model"]] if cfg.get("llm_model") and "gemini" in cfg["llm_model"] else list(cfg["gemini_models"])
    last_err = None
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.25,
                "responseMimeType": "application/json",
            },
        }
        try:
            data = _http_json(url, payload, {}, timeout=90)
            cands = data.get("candidates") or []
            if cands:
                parts = (cands[0].get("content") or {}).get("parts") or []
                if parts and parts[0].get("text"):
                    return parts[0]["text"]
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")[:200]
            last_err = f"{model} -> HTTP {exc.code}: {body}"
            if exc.code == 429:
                time.sleep(2.0)
            continue
        except Exception as exc:
            last_err = f"{model} -> {exc}"
            continue
    raise RuntimeError(f"Gemini free API failed ({last_err})")


def _ask_openai_compat(url, key, model, prompt):
    return _ask_openai_models(url, key, [model], prompt)


def _ask_ollama(prompt, cfg):
    model = cfg.get("llm_model") or cfg.get("ollama_model") or "qwen2.5:7b"
    base = (cfg.get("ollama_url") or "http://localhost:11434").rstrip("/")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.25},
    }
    data = _http_json(f"{base}/api/generate", payload, {}, timeout=180)
    return data.get("response", "")


def _ask_claude_cli(prompt, cfg):
    if not shutil.which("claude"):
        raise RuntimeError("claude CLI not installed")
    cmd = ["claude", "-p"]
    if cfg.get("llm_model") and "claude" in str(cfg.get("llm_model")):
        cmd += ["--model", cfg["llm_model"]]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=300, env=clean_env())
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p failed: {(proc.stderr or proc.stdout or '').strip()[:200]}")
    return proc.stdout


def resolve_provider(cfg):
    pref = (cfg.get("llm_provider") or "auto").lower()
    if pref != "auto":
        return pref
    if os.environ.get("EXPLABS_API_KEY") or os.environ.get("EXPERIENTIAL_API_KEY"):
        return "experiential"
    if os.environ.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("CODECRAFT_API_KEY"):
        return "codecraft"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("NVIDIA_API_KEY"):
        return "nvidia"
    try:
        base = (cfg.get("ollama_url") or "http://localhost:11434").rstrip("/")
        with urllib.request.urlopen(f"{base}/api/tags", timeout=1.5) as resp:
            if resp.status == 200:
                return "ollama"
    except Exception:
        pass
    if shutil.which("claude"):
        return "claude"
    return "heuristic"


def _ask(prompt, cfg):
    primary = resolve_provider(cfg)
    chain = [primary]
    for backup in ("experiential", "openrouter", "gemini", "codecraft", "groq", "nvidia", "ollama"):
        if backup not in chain:
            if backup == "experiential" and (os.environ.get("EXPLABS_API_KEY") or os.environ.get("EXPERIENTIAL_API_KEY")):
                chain.append(backup)
            elif backup == "openrouter" and os.environ.get("OPENROUTER_API_KEY"):
                chain.append(backup)
            elif backup == "gemini" and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
                chain.append(backup)
            elif backup == "codecraft" and os.environ.get("CODECRAFT_API_KEY"):
                chain.append(backup)
            elif backup == "groq" and os.environ.get("GROQ_API_KEY"):
                chain.append(backup)
            elif backup == "nvidia" and os.environ.get("NVIDIA_API_KEY"):
                chain.append(backup)

    errors = []
    for prov in chain:
        try:
            if prov == "experiential":
                exp_key = (os.environ.get("EXPLABS_API_KEY") or os.environ.get("EXPERIENTIAL_API_KEY") or "").strip()
                exp_models = [cfg["llm_model"]] if cfg.get("llm_model") else list(cfg["experiential_models"])
                return _ask_openai_models("https://api.experientiallabs.ai/v1/chat/completions", exp_key, exp_models, prompt)
            if prov == "codecraft":
                cc_key = os.environ.get("CODECRAFT_API_KEY", "").strip()
                cc_models = [cfg["llm_model"]] if cfg.get("llm_model") else list(cfg["codecraft_models"])
                return _ask_openai_models("https://codecraftapi.com/v1/chat/completions", cc_key, cc_models, prompt)
            if prov == "openrouter":
                return _ask_openrouter(prompt, cfg)
            if prov == "gemini":
                return _ask_gemini(prompt, cfg)
            if prov == "groq":
                return _ask_openai_compat(
                    "https://api.groq.com/openai/v1/chat/completions",
                    os.environ["GROQ_API_KEY"],
                    cfg.get("llm_model") or cfg["groq_model"],
                    prompt,
                )
            if prov == "nvidia":
                return _ask_openai_compat(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    os.environ["NVIDIA_API_KEY"],
                    cfg.get("llm_model") or cfg["nvidia_model"],
                    prompt,
                )
            if prov == "ollama":
                return _ask_ollama(prompt, cfg)
            if prov == "claude":
                return _ask_claude_cli(prompt, cfg)
        except Exception as exc:
            errors.append(f"{prov}: {exc}")
            continue
    raise RuntimeError("; ".join(errors) if errors else "No LLM provider available")


def _to_sec(val):
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if ":" in s:
        parts = s.split(":")
        total = 0.0
        for p in parts:
            total = total * 60.0 + float(p)
        return total
    return float(s)


def _parse(raw):
    text = (raw or "").strip()
    # Strip <think>...</think> reasoning blocks from DeepSeek / Qwen / Nemotron responses
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("["):
        m = re.search(r"\[\s*\{.*\}\s*\]", text, re.S)
        if m:
            text = m.group(0)
        else:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    for v in obj.values():
                        if isinstance(v, list):
                            return v
                    return [obj]
            except Exception:
                return []
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        return []
    return out if isinstance(out, list) else []


def _heuristic_pick(words, loud_rel, chat, cfg, stream, want):
    """Zero-API viral moment detector anchored on peak acoustic/scream spikes + build-up lead-in."""
    max_t_words = words[-1]["e"] if words else 0.0
    max_t_loud = float(len(loud_rel)) if loud_rel is not None and len(loud_rel) else 0.0
    total_dur = max(max_t_words, max_t_loud)
    if total_dur <= 0:
        return []

    min_d, max_d = cfg["min_duration"], cfg["max_duration"]
    target_d = min(max_d, max(min_d, min(28.0, total_dur * 0.5)))

    # If we have a loudness curve, anchor windows so the PEAK scream/reaction sits at ~65% into the clip
    # (giving 65% setup/build-up BEFORE the scream and 35% reaction/payoff, cutting before boring aftermath!)
    candidates = []
    if loud_rel is not None and len(loud_rel) >= 5:
        arr = np.asarray(loud_rel, dtype=np.float32)
        order = np.argsort(-arr)
        used_peaks = []
        for idx in order[:40]:
            peak_t = float(idx)
            if any(abs(peak_t - u) < target_d * 0.6 for u in used_peaks):
                continue
            used_peaks.append(peak_t)
            # Place peak at 65% of clip duration so we capture the build-up BEFORE the scream!
            s0 = max(0.0, peak_t - target_d * 0.65)
            e0 = min(total_dur, s0 + target_d)
            if e0 - s0 < min(min_d, total_dur):
                s0 = max(0.0, e0 - min(min_d, total_dur))
            peak_val = float(arr[idx])
            seg_words = [w for w in words if s0 <= w["s"] <= e0]
            snippet = " ".join(w["w"] for w in seg_words[:16]).strip() or f"Watch {stream['name']}'s insane reaction!"
            score = int(round(min(98.0, max(72.0, 70.0 + peak_val * 1.8))))
            candidates.append({
                "start": round(s0, 2),
                "end": round(e0, 2),
                "kind": "reaction",
                "title": f"viral_reaction_{int(peak_t)}s",
                "hook_text": (
                f"{stream['name'][:14]}: '{' '.join(w['w'] for w in seg_words[:5]).upper()}' Goes WRONG 😭"
                if len(seg_words) >= 5 else f"{stream['name'][:15]} Instant KARMA Moment 😭"
            ),
                "caption": f"{snippet[:110]}... Wait for the reaction 😭👇",
                "hashtags": ["#shorts", "#viral", "#clips"],
                "score": score,
                "reason": f"Anchored on +{peak_val:.1f}dB peak reaction at {int(peak_t)}s with build-up lead-in.",
            })
            if len(candidates) >= want * 2:
                break

    if not candidates and words:
        s0 = words[0]["s"]
        e0 = min(words[-1]["e"], s0 + target_d)
        candidates.append({
            "start": round(s0, 2),
            "end": round(e0, 2),
            "kind": "reaction",
            "title": "viral_clip",
            "hook_text": f"{stream['name'][:16]} DROPS A WILD MOMENT 🔥",
            "caption": "Watch till the end 🔥👇",
            "hashtags": ["#shorts", "#viral"],
            "score": 82,
            "reason": "Top speech energy segment.",
        })

    return _dedupe(candidates)[:want]


def _snap(m, words, loud_rel, cfg):
    """Refine LLM timestamps WITHOUT deleting pre-speech screams/action build-up,
    and NEVER pad the end of a clip forward into boring aftermath dialogue!
    """
    start, end = _to_sec(m["start"]), _to_sec(m["end"])
    if end <= start:
        return None
    max_t = max(words[-1]["e"] if words else 0.0, float(len(loud_rel)) if loud_rel is not None else 0.0, end)
    lo = min(cfg["min_duration"], max(5.0, max_t * 0.8))
    hi = cfg["max_duration"]

    # 1. If there is a loud spike (scream/soundboard/explosion) inside [start-8, end],
    #    ensure `start` begins at least 6-8 seconds BEFORE the spike so the cause/build-up is never cut off!
    if loud_rel is not None and len(loud_rel) > 5:
        a = int(max(0, start - 6))
        b = int(min(len(loud_rel), end + 2))
        if b > a:
            seg = np.asarray(loud_rel[a:b], dtype=np.float32)
            peak_off = int(np.argmax(seg))
            peak_val = float(seg[peak_off])
            peak_time = float(a + peak_off)
            if peak_val >= cfg["loud_db"]:
                # Ensure at least 7 seconds of build-up before the first big scream/soundboard spike
                start = min(start, max(0.0, peak_time - 7.5))
                # Find the LAST loud spike in the window so we cut 2.5s after the climax instead of dragging on
                loud_indices = [i for i, v in enumerate(seg) if v >= cfg["loud_db"] * 0.85]
                if loud_indices:
                    last_spike_t = float(a + loud_indices[-1])
                    # If the clip currently trails >6s past the last spike into quiet filler chatter, trim the tail!
                    if end - last_spike_t > 6.5 and (last_spike_t + 3.5 - start) >= lo:
                        end = last_spike_t + 3.5

    # 2. Gentle word-edge alignment ONLY if a word is within 1.2s of `start` or `end`
    #    (NEVER jump `start` forward by 5-10s over non-verbal gameplay/screams!)
    if words:
        near_start = [w for w in words if abs(w["s"] - start) <= 1.2]
        if near_start:
            first_w = min(near_start, key=lambda w: abs(w["s"] - start))
            start = max(0.0, first_w["s"] - 0.4)

        near_end = [w for w in words if abs(w["e"] - end) <= 1.5]
        if near_end:
            last_w = min(near_end, key=lambda w: abs(w["e"] - end))
            end = min(max_t, last_w["e"] + 0.5)

    # 3. Enforce [lo, hi] duration by expanding BACKWARD into the setup (never forward into boring aftermath!)
    dur = end - start
    if dur > hi:
        end = start + hi
    elif dur < lo:
        needed = lo - dur
        # Take 75% of needed time from BEFORE `start` (the setup/build-up) and at most 25% after `end`
        pre_add = min(start, needed * 0.75)
        start -= pre_add
        rem = lo - (end - start)
        if rem > 0:
            end = min(max_t, end + rem)
        if end - start < lo and start > 0:
            start = max(0.0, end - lo)

    m["start"] = round(max(0.0, start), 2)
    m["end"] = round(min(max_t, end), 2)
    return m if (m["end"] - m["start"]) >= min(4.0, lo) else None


def _dedupe(cands):
    kept = []
    for m in sorted(cands, key=lambda m: -float(m.get("score", 0))):
        span = max(0.1, m["end"] - m["start"])
        if all(min(m["end"], k["end"]) - max(m["start"], k["start"])
               <= 0.3 * min(span, max(0.1, k["end"] - k["start"])) for k in kept):
            kept.append(m)
    return kept


def find(scan, loud_rel, chat, workdir, cfg, stream):
    cache = workdir / "moments.json"
    if cache.exists():
        found = json.loads(cache.read_text(encoding="utf-8"))
        log(f"reusing {len(found)} picked moment(s)", "ok")
        return found

    words = scan["words"]
    lines = _lines(words, loud_rel, chat or [], cfg)
    if not lines:
        raise RuntimeError("not enough audio/speech timeline in this stream to clip")

    first, total = lines[0][0], lines[-1][0] + 5.0
    window = cfg["chunk_minutes"] * 60
    chunks = []
    for i in range(int(np.ceil(max(1.0, total - first) / window))):
        lo, hi = first + i * window, min(first + (i + 1) * window, total)
        body = [f"[{t:.1f}] {text}" for t, text in lines if lo <= t <= hi]
        if len(body) >= 3:
            chunks.append((lo, hi, "\n".join(body)))
    if not chunks:
        raise RuntimeError("not enough content in this stream to clip")

    provider = resolve_provider(cfg)
    want = max(2, min(5, round(cfg["clips_per_stream"] / len(chunks)) + 2))

    topic = cfg.get("topic") or "auto"
    if topic == "auto":
        if "gta" in stream["title"].lower():
            topic_hint = " The game is GTA 6, so first reactions, crazy discoveries, and loud chaos perform best."
        else:
            topic_hint = ""
    else:
        topic_hint = f" Focus especially on moments related to: {topic}."

    cands = []
    if provider != "heuristic":
        log(f"AI ({provider}) is analyzing {len(chunks)} timeline window(s) (with scream/build-up awareness)...", "step")

        def work(chunk):
            lo, hi, body = chunk
            eff_min = min(cfg["min_duration"], max(5, int((hi - lo) * 0.5)))
            prompt = UNIVERSAL_PROMPT.format(
                streamer=stream["name"], title=stream["title"], topic_hint=topic_hint,
                want=want, lo=lo, hi=hi, min_d=eff_min, max_d=cfg["max_duration"],
                transcript=body,
            )
            try:
                got = _parse(_ask(prompt, cfg))
            except Exception as exc:
                log(f"  window {lo / 60:.0f}-{hi / 60:.0f}m LLM note: {str(exc)[:140]}", "warn")
                return []
            ok = []
            for m in got:
                try:
                    if lo - 10 <= _to_sec(m["start"]) < hi + 30:
                        s = _snap(m, words, loud_rel, cfg)
                        if s:
                            ok.append(s)
                except (KeyError, TypeError, ValueError):
                    continue
            return ok

        with ThreadPoolExecutor(max_workers=max(1, int(cfg.get("llm_parallel", 2)))) as pool:
            for got in pool.map(work, chunks):
                cands += got

    if not cands:
        log("using built-in acoustic spike + pre-roll build-up ranker...", "step")
        cands = _heuristic_pick(words, loud_rel, chat, cfg, stream, cfg["clips_per_stream"])

    if not cands:
        raise RuntimeError("could not find any moments to clip in this video")

    chosen = _dedupe(cands)[: cfg["clips_per_stream"]]
    log(f"picked {len(chosen)} of {len(cands)} viral moment candidate(s)", "ok")
    cache.write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    (workdir / "candidates.json").write_text(json.dumps(cands, indent=2), encoding="utf-8")
    return chosen
