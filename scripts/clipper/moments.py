"""Pick the moments worth clipping using 100% FREE AI providers.

100% ADAPTIVE SCENE DURATION (Never Fixed, Never Cut Short):
- Each clip's length adjusts automatically to the natural start-to-finish arc of that specific moment
  (up to {max_d}s for YouTube Shorts / Reels):
  * If a complete cutscene reveal + streamer reaction takes 22s, it stays 22s.
  * If an intense plane escape, police shootout, or world/graphics/dialogue showcase takes 38s, 45s, or 56s
    to cover all the important parts, it keeps the entire 38-56s sequence without cutting off early!
- `_snap()` automatically extends the start backward to capture the full setup/context and extends the end
  forward until the active reaction/dialogue finishes so important parts are NEVER chopped off.
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

UNIVERSAL_PROMPT = """You are an elite viral gaming & stream editor for YouTube Shorts, Instagram Reels, and TikTok.
This is an excerpt from a stream by "{streamer}", titled "{title}".{topic_hint}

Below is a timestamped timeline (seconds) in English or Romanized Hindi (Hinglish), with audio/chat markers:
- [SHOUTING / SCREAM +NdB] or [VOICE RAISED +NdB]: streamer got excited, shocked, or loud
- [CHAT xN]: live chat reacted N times faster than normal

YOUR OBJECTIVE — EXTRACT THE {want} BEST VIRAL MOMENTS WITH DYNAMIC, SCENE-DRIVEN DURATION (UP TO {max_d} SECONDS):
Look for moments that match these proven viral Shorts styles:
1. `first_milestone` (First-Time Action / Vehicle / Escape / Mission Milestone):
   - {streamer} experiences a major gameplay moment for the first time: flying their first plane/seaplane/helicopter, stealing a boat/supercar, surviving an intense shootout, or entering a new area.
   - Example: Running onto the dock under gunfire yelling "Chal chal baith jaldi Donnie aage baith! Oh let's go! Oh let's gooo!" all the way through the plane lifting off into the sky (`hook_text`: "Flying our first plane in GTA 6").
2. `story_twist` (Major Cutscene Plot Twist / NPC Dialogue + Shock Reaction):
   - An in-game character/NPC reveals a shocking plot twist or wild dialogue line, and {streamer} reacts in real time ("Tomas iska beta hai?! Holy shit! Oh my god!", "Kya?!", "Bhai yeh kya bola!").
   - Include the FULL setup dialogue from the NPC before the twist AND {streamer}'s complete reaction after (`hook_text`: "Holy sh#t" or "This GTA 6 story twist is wild 🤯").
3. `world_discovery` (Environment, Graphics, Character Style & Gameplay Showcase):
   - {streamer} showcases and reacts to the open-world environment, Vice City atmosphere, next-gen graphics, water/lighting physics, character animations, or realistic car mechanics.

CRITICAL RULES (DO NOT VIOLATE):
1. ADJUSTABLE, SCENE-DRIVEN DURATION (NEVER CUT IMPORTANT PARTS SHORT!):
   - Do NOT force a fixed length! Adjust `start` and `end` dynamically to cover the ENTIRE moment from setup to full payoff (anywhere from ~20s up to {max_d}s).
   - NEVER make a clip so short that it cuts off the setup, the action, the graphics/environment showcase, or {streamer}'s reaction! If a sequence needs 35s, 45s, or 55s to cover all the important parts, make it 35-55s!
2. SLEEK SEAM HOOK BANNER (`hook_text`):
   - `hook_text` sits on the GTA 6 sunset-gradient seam banner between facecam and gameplay.
   - Keep `hook_text` to 2 to 6 words MAX, natural Sentence case or punchy reaction (e.g., "Flying our first plane in GTA 6", "Holy sh#t", "GTA 6 graphics are unreal 🔥", "First shootout in Vice City"). NO quotes, NO colons!
3. NO BORING MENUS OR HOUSEKEEPING:
   - Never pick "Starting soon" screens or "like/subscribe/superchat" housekeeping.

Return ONLY a valid JSON array:
[{{"start": 420.0, "end": 462.0, "kind": "first_milestone",
  "title": "flying_first_plane_in_gta6",
  "hook_text": "Flying our first plane in GTA 6",
  "caption": "{streamer} flying the seaplane for the first time under heavy fire in Vice City! 🔥",
  "hashtags": ["#gta6", "#shorts", "#gaming"],
  "score": 96,
  "reason": "Complete start-to-finish sequence covering the dock shootout, boarding the plane, takeoff, and full reaction."}}]

TRANSCRIPT & AUDIO TIMELINE:
{transcript}
"""


def _is_brb_or_intro_screen(text):
    low = (text or "").lower()
    bad = ("starting soon", "stream starting", "be right back", "brb screen", "thanks for watching the stream")
    return any(b in low for b in bad)


def _lines(words, loud, chat, cfg, line_seconds=5):
    """Build a continuous ~5s timeline that includes BOTH spoken words AND non-verbal
    scream/action spikes or cutscene dialogue gaps so the AI never misses non-spoken moments!
    """
    chat_base = float(np.median([c for c in chat if c > 0])) if chat and any(chat) else 0
    max_t_words = words[-1]["e"] if words else 0.0
    max_t_loud = float(len(loud)) if loud is not None and len(loud) else 0.0
    total_t = max(max_t_words, max_t_loud)
    if total_t <= 0:
        return []

    first_t = min(words[0]["s"], 0.0) if words else 0.0
    lines = []
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
        if loud is not None and len(loud):
            a, b = int(max(0, t0)), max(int(t0) + 1, int(min(len(loud), np.ceil(t1))))
            if b > a:
                seg_loud = loud[a:b]
                peak_db = float(np.max(seg_loud))
                if peak_db >= cfg["loud_db"] + 5.0:
                    tags.append(f"[SHOUTING / SCREAM +{peak_db:.0f}dB]")
                elif peak_db >= cfg["loud_db"]:
                    tags.append(f"[VOICE RAISED +{peak_db:.0f}dB]")

        if chat_base > 0 and chat:
            ca, cb = int(t0 // 5), int(t1 // 5) + 2
            seg_chat = chat[ca:cb]
            if seg_chat:
                ratio = max(seg_chat) / chat_base
                if ratio >= 2.2:
                    tags.append(f"[CHAT x{ratio:.1f}]")

        text = " ".join(bucket_words).strip()
        if not text:
            if peak_db >= cfg["loud_db"] + 2.0:
                text = "[NON-VERBAL SCREAM / INTENSE AUDIO REACTION / GAMEPLAY CLIMAX]"
            elif peak_db >= cfg["loud_db"]:
                text = "[LOUD GAMEPLAY / CUTSCENE / REACTION]"
            elif tags:
                text = "[AUDIENCE / CHAT REACTION SPIKE]"
            else:
                near_spike = False
                if loud is not None and len(loud):
                    na = int(max(0, t0 - 10))
                    nb = int(min(len(loud), t1 + 10))
                    if nb > na and float(np.max(loud[na:nb])) >= cfg["loud_db"] + 1.5:
                        near_spike = True
                if near_spike:
                    text = "[CUTSCENE DIALOGUE / TENSE BUILD-UP]"
                else:
                    continue

        prefix = (" ".join(tags) + " ") if tags else ""
        lines.append((round(t0, 1), prefix + text))

    return lines


def _http_json(url, payload, headers, timeout=90):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Antigravity-ViralClipper/3.6", **headers},
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


def _score_viral_archetypes(seg_words):
    """Score a transcript segment on the 3 FING Plays / CarryisLive Viral Archetypes:
    1. `first_milestone`: First plane/car/boat, high-urgency action ("chal chal baith jaldi", "oh let's go")
    2. `story_twist`: Shocking story reveal ("iska beta hai", "holy shit", "oh my god", "wtf")
    3. `world_discovery`: Graphics, environment, realistic details ("graphics dekho", "kitna real")
    """
    tokens = [re.sub(r"[^a-z0-9]", "", w["w"].lower()) for w in seg_words]
    joined = " ".join(tokens)

    milestone_words = {
        "plane", "fly", "flying", "helicopter", "boat", "jet", "car", "gaadi", "baith", "jaldi",
        "chal", "bhag", "bhaag", "escape", "police", "cops", "shoot", "maar", "first", "pehli",
    }
    twist_words = {
        "holy", "shit", "god", "wtf", "beta", "mother", "son", "kya", "sach", "seriously",
        "wait", "what", "bro", "bhai", "arey", "abey", "pagal", "crazy", "insane",
    }
    discovery_words = {
        "graphics", "real", "realistic", "water", "paani", "city", "sheher", "view", "look",
        "dekho", "jagah", "mahaul", "detail", "lighting", "weather", "npc", "style",
    }

    s_mile = sum(2 for t in tokens if t in milestone_words) + (5 if "lets go" in joined or "baith jaldi" in joined else 0)
    s_twist = sum(2 for t in tokens if t in twist_words) + (6 if "holy shit" in joined or "oh my god" in joined or "beta hai" in joined else 0)
    s_disc = sum(2 for t in tokens if t in discovery_words)

    scores = {"first_milestone": s_mile, "story_twist": s_twist, "world_discovery": s_disc}
    best_kind = max(scores, key=scores.get)
    return best_kind, sum(scores.values())


def _expand_natural_cluster(peak_t, words, loud_rel, total_dur, hi_cap=58.0):
    """Given an excitement peak at `peak_t`, expand backward to the start of the active
    scene/setup and forward to the end of the active payoff/reaction, so the clip duration
    adjusts dynamically to cover the entire moment without cutting off early!
    """
    s0 = max(0.0, peak_t - 12.0)
    e0 = min(total_dur, peak_t + 14.0)

    # Walk backward through continuous speech/loudness (gaps <= 3.5s) up to ~25s before peak
    if words:
        before = [w for w in words if s0 - 15.0 <= w["s"] <= peak_t]
        for i in range(len(before) - 1, 0, -1):
            gap = before[i]["s"] - before[i - 1]["e"]
            if gap <= 3.5 and (e0 - before[i - 1]["s"]) <= hi_cap * 0.85:
                s0 = min(s0, max(0.0, before[i - 1]["s"] - 0.5))
            elif gap > 5.0:
                break

        # Walk forward through continuous speech/reaction (gaps <= 3.5s) up to hi_cap
        after = [w for w in words if peak_t <= w["e"] <= e0 + 25.0]
        for i in range(len(after) - 1):
            gap = after[i + 1]["s"] - after[i]["e"]
            if gap <= 3.5 and (after[i + 1]["e"] - s0) <= hi_cap:
                e0 = max(e0, min(total_dur, after[i + 1]["e"] + 0.8))
            elif gap > 5.0:
                break

    if e0 - s0 > hi_cap:
        e0 = s0 + hi_cap
    return round(s0, 2), round(e0, 2)


def _heuristic_pick(words, loud_rel, chat, cfg, stream, want):
    """Zero-API viral moment detector with dynamic, scene-driven duration."""
    max_t_words = words[-1]["e"] if words else 0.0
    max_t_loud = float(len(loud_rel)) if loud_rel is not None and len(loud_rel) else 0.0
    total_dur = max(max_t_words, max_t_loud)
    if total_dur <= 0:
        return []

    hi_cap = float(cfg.get("max_duration") or 59.0)
    candidates = []
    if loud_rel is not None and len(loud_rel) >= 5:
        arr = np.asarray(loud_rel, dtype=np.float32)
        order = np.argsort(-arr)
        used_peaks = []
        for idx in order[:45]:
            peak_t = float(idx)
            if any(abs(peak_t - u) < 22.0 for u in used_peaks):
                continue
            used_peaks.append(peak_t)
            s0, e0 = _expand_natural_cluster(peak_t, words, loud_rel, total_dur, hi_cap=hi_cap)
            peak_val = float(arr[idx])
            seg_words = [w for w in words if s0 <= w["s"] <= e0]
            kind, arch_bonus = _score_viral_archetypes(seg_words)
            snippet = " ".join(w["w"] for w in seg_words[:16]).strip() or f"Watch {stream['name']}'s reaction!"
            score = int(round(min(98.0, max(72.0, 68.0 + peak_val * 1.6 + min(14.0, arch_bonus * 0.6)))))
            hook_default = (
                "Flying through Vice City in GTA 6"
                if kind == "first_milestone"
                else "Holy sh#t"
                if kind == "story_twist"
                else "GTA 6 details are unreal 🔥"
            )
            candidates.append({
                "start": s0,
                "end": e0,
                "kind": kind,
                "title": f"{kind}_{int(peak_t)}s",
                "hook_text": hook_default,
                "caption": f"{snippet[:110]} 🔥",
                "hashtags": ["#gta6", "#shorts", "#gaming"],
                "score": score,
                "reason": f"Dynamic {e0 - s0:.0f}s scene anchored on +{peak_val:.1f}dB reaction peak at {int(peak_t)}s ({kind}).",
            })
            if len(candidates) >= want * 2:
                break

    if not candidates and words:
        s0 = words[0]["s"]
        e0 = min(words[-1]["e"], s0 + min(40.0, hi_cap))
        candidates.append({
            "start": round(s0, 2),
            "end": round(e0, 2),
            "kind": "first_milestone",
            "title": "viral_clip",
            "hook_text": "First time in Vice City 🔥",
            "caption": "Watch till the end 🔥",
            "hashtags": ["#gta6", "#shorts"],
            "score": 82,
            "reason": "Complete speech segment.",
        })

    return _dedupe(candidates)[:want]


def _snap(m, words, loud_rel, cfg):
    """100% Adjustable, Scene-Driven Boundary Alignment:
    - NEVER forces a fixed minimum length and NEVER shrinks a clip below what the scene needs!
    - If a clip starts right on a scream or mid-sentence without the setup, extends `start` backward
      so the viewer sees what caused the reaction.
    - If `end` cuts off while the streamer or NPC is still speaking/reacting (words continuing within 2.5s),
      extends `end` forward up to `max_duration` (59s) so the important part is NEVER cut off early!
    """
    start, end = _to_sec(m["start"]), _to_sec(m["end"])
    if end <= start:
        return None
    max_t = max(
        words[-1]["e"] if words else 0.0,
        float(len(loud_rel)) if loud_rel is not None else 0.0,
        end,
    )
    hi = float(cfg.get("max_duration") or 59.0)
    user_min = cfg.get("min_duration")  # None by default (only set if user explicitly passes --min or --tight)

    # 1. Make sure we never start right on a loud scream without 6s of setup before it
    if loud_rel is not None and len(loud_rel) > 5:
        a = int(max(0, start - 2))
        b = int(min(len(loud_rel), start + 5))
        if b > a:
            seg = np.asarray(loud_rel[a:b], dtype=np.float32)
            peak_off = int(np.argmax(seg))
            if float(seg[peak_off]) >= cfg["loud_db"]:
                start = min(start, max(0.0, float(a + peak_off) - 6.5))

    # 2. If `start` lands mid-sentence, walk back to the start of that spoken thought (up to 5s back)
    if words:
        near_start = [w for w in words if start - 5.0 <= w["s"] <= start + 1.0]
        if near_start:
            # Find where the current continuous phrase started (gap > 1.2s)
            idx0 = len(near_start) - 1
            while idx0 > 0 and (near_start[idx0]["s"] - near_start[idx0 - 1]["e"]) <= 1.2:
                idx0 -= 1
            start = min(start, max(0.0, near_start[idx0]["s"] - 0.4))

        # 3. NEVER cut off the end if the streamer/NPC is still in the middle of reacting or talking!
        # Walk forward through continuous speech/reaction (gap <= 2.2s) up to the 59s Shorts ceiling
        after_end = [w for w in words if end - 0.8 <= w["s"] <= end + 14.0]
        cur_end = end
        for w in after_end:
            if w["s"] - cur_end <= 2.2 and (w["e"] - start) <= hi - 0.5:
                cur_end = max(cur_end, w["e"] + 0.5)
                # Stop once we hit a natural sentence-ending punctuation mark after extending at least 2s
                if w["w"].strip().endswith((".", "!", "?")) and (cur_end - end) >= 2.0:
                    break
            elif w["s"] - cur_end > 2.2:
                break
        end = min(max_t, cur_end)

    # 4. Only apply `user_min` if the user explicitly passed `--min` on the CLI
    if user_min is not None:
        lo = min(float(user_min), max(8.0, max_t * 0.8))
        if (end - start) < lo:
            needed = lo - (end - start)
            pre_add = min(start, needed * 0.45)
            start -= pre_add
            rem = lo - (end - start)
            if rem > 0:
                end = min(max_t, end + rem)

    # 5. Respect the platform ceiling (`max_duration`, default 59s for YouTube Shorts)
    if (end - start) > hi:
        end = start + hi

    m["start"] = round(max(0.0, start), 2)
    m["end"] = round(min(max_t, end), 2)
    return m if (m["end"] - m["start"]) >= 8.0 else None


def _speech_coverage_and_max_gap(words, s0, e0):
    """Return `(coverage_ratio 0..1, max_silent_gap_sec, words_per_sec)` inside [s0, e0]."""
    dur = max(1.0, e0 - s0)
    seg = [w for w in words if w["e"] > s0 and w["s"] < e0]
    if not seg:
        return 0.0, dur, 0.0
    n_buckets = max(1, int(np.ceil(dur / 3.0)))
    active_buckets = 0
    for b in range(n_buckets):
        b0, b1 = s0 + b * 3.0, min(e0, s0 + (b + 1) * 3.0)
        if any(w["e"] > b0 and w["s"] < b1 for w in seg):
            active_buckets += 1
    coverage = active_buckets / float(n_buckets)

    gaps = [max(0.0, seg[0]["s"] - s0), max(0.0, e0 - seg[-1]["e"])]
    for i in range(len(seg) - 1):
        gaps.append(max(0.0, seg[i + 1]["s"] - seg[i]["e"]))
    max_gap = max(gaps) if gaps else dur
    wps = len(seg) / dur
    return coverage, max_gap, wps


def _blind_critic_repair(candidates, words, loud_rel, cfg, stream):
    """Quality Gate:
    1. Rejects 'Starting soon' / 'Be right back' screens.
    2. Penalizes windows with >12s of dead radio silence (`max_gap > 12s`) without chopping active gameplay/cutscenes.
    3. Boosts segments that match `first_milestone`, `story_twist`, or `world_discovery`.
    """
    if not candidates:
        return candidates
    repaired = []
    for m in candidates:
        s0, e0 = float(m["start"]), float(m["end"])
        seg_words = [w for w in words if s0 <= w["s"] <= e0]
        seg_text = " ".join(w["w"] for w in seg_words)
        if _is_brb_or_intro_screen(seg_text):
            continue

        cov, max_gap, wps = _speech_coverage_and_max_gap(words, s0, e0)
        best_kind, arch_score = _score_viral_archetypes(seg_words)
        if not m.get("kind") or m.get("kind") == "reaction":
            m["kind"] = best_kind

        base_score = float(m.get("score", 80)) + min(10.0, arch_score * 0.45)
        if max_gap > 12.0:
            base_score -= min(25.0, (max_gap - 10.0) * 2.0)
        if cov < 0.40:
            base_score -= 12.0
        elif cov >= 0.70 and wps >= 1.6:
            base_score += 8.0

        m["score"] = int(round(max(40.0, min(99.0, base_score))))
        m["start"] = round(s0, 2)
        m["end"] = round(e0, 2)
        repaired.append(m)
    return repaired


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
        if any("Loses It at This MOMENT" in (m.get("hook_text") or "") for m in found):
            cache.unlink(missing_ok=True)
        else:
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
            topic_hint = " The game is GTA 6 — prioritize first-time milestones (flying first plane, first police chase), shocking story cutscene reveals + reactions, and insane Vice City world/graphics details."
        else:
            topic_hint = ""
    else:
        topic_hint = f" Focus especially on moments related to: {topic}."

    cands = []
    if provider != "heuristic":
        log(f"AI ({provider}) is analyzing {len(chunks)} timeline window(s) with dynamic scene-driven duration...", "step")

        def work(chunk):
            lo, hi, body = chunk
            prompt = UNIVERSAL_PROMPT.format(
                streamer=stream["name"], title=stream["title"], topic_hint=topic_hint,
                want=want, lo=lo, hi=hi, max_d=cfg["max_duration"],
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
        log("using built-in acoustic spike + natural scene-boundary ranker...", "step")
        cands = _heuristic_pick(words, loud_rel, chat, cfg, stream, cfg["clips_per_stream"])

    if not cands:
        raise RuntimeError("could not find any moments to clip in this video")

    cands = _blind_critic_repair(cands, words, loud_rel, cfg, stream)
    chosen = _dedupe(cands)[: max(cfg["clips_per_stream"] + 2, int(cfg["clips_per_stream"] * 1.5))]
    log(f"picked {len(chosen)} of {len(cands)} viral moment candidate(s)", "ok")
    cache.write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    (workdir / "candidates.json").write_text(json.dumps(cands, indent=2), encoding="utf-8")
    return chosen
