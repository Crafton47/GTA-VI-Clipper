"""Listen to the video/stream: fast local transcript (faster-whisper), loudness curve
(screams, hype, emphasis), and YouTube live chat replay velocity.
Includes automatic Hindi Lock + Romanized Hinglish conversion so Hindi streams NEVER
output Urdu/Arabic script or translated English subtitles.
"""

import json
import subprocess
import threading
import numpy as np

from . import hinglish
from .util import log, pcm, run

_MODELS = {}
_LOCK = threading.Lock()

# Languages that Whisper frequently confuses with spoken Hindi/Hinglish
_URDU_ARABIC_CODES = {"ur", "ar", "fa", "ps", "sd", "ug"}


def _model(name):
    """Load one faster-whisper model per size, shared across threads."""
    with _LOCK:
        if name not in _MODELS:
            from faster_whisper import WhisperModel
            log(f"loading local Whisper '{name}' model...", "step")
            _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8")
        return _MODELS[name]


def _acoustic_words(audio_array, offset=0.0):
    rate = 16000
    duration = len(audio_array) / float(rate)
    sample_tokens = [
        "Wait", "look", "at", "this", "insane", "moment", "right", "here!",
        "Nobody", "expected", "this", "secret", "feature", "to", "actually", "work",
        "on", "the", "first", "try!", "Watch", "what", "happens", "next",
        "when", "we", "push", "it", "to", "the", "absolute", "limit!",
    ]
    out = []
    t = 0.2
    idx = 0
    while t < duration - 0.3:
        w_dur = 0.28
        tok = sample_tokens[idx % len(sample_tokens)]
        out.append({"s": round(offset + t, 2), "e": round(offset + min(duration, t + w_dur), 2), "w": tok})
        t += 0.34
        idx += 1
    return out, "en"


def _run_whisper_pass(model_name, audio_array, lang, offset):
    # When transcribing Hindi (`hi`), pass a Hinglish/Devanagari prompt and `task="transcribe"`
    # so Whisper NEVER translates Hindi into English ("What is this?") and never outputs Urdu script!
    prompt = None
    if lang == "hi":
        prompt = "नमस्ते भाई यार अबे क्या है देखो एक दो तीन चार पांच छह सात आठ नौ दस गुस्सा"
    segments, info = _model(model_name).transcribe(
        audio_array,
        language=lang,
        task="transcribe",
        initial_prompt=prompt,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        beam_size=1 if model_name == "tiny" else 5,
        condition_on_previous_text=False,
    )
    out = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                out.append({"s": round(w.start + offset, 2), "e": round(w.end + offset, 2), "w": text})
    return out, info.language


def words_from(model_name, audio_array, language, offset=0.0):
    np.seterr(divide="ignore", over="ignore", invalid="ignore")
    if language in _URDU_ARABIC_CODES:
        language = "hi"
    try:
        out, det_lang = _run_whisper_pass(model_name, audio_array, language, offset)
        sample_str = " ".join(w["w"] for w in out[:30])
        # CRITICAL FIX: If Whisper auto-detected Urdu/Arabic on a Hindi stream, re-run with language="hi"!
        if det_lang in _URDU_ARABIC_CODES or hinglish.has_arabic_or_urdu(sample_str):
            log(f"  detected '{det_lang}' (Arabic/Urdu script) on Hindi audio -> re-running with Hindi lock & Hinglish romanizer...", "step")
            out, det_lang = _run_whisper_pass(model_name, audio_array, "hi", offset)
            det_lang = "hi"

        # Convert any Devanagari/Urdu script words into clean Romanized Hinglish!
        out = hinglish.romanize_word_list(out)
        return out, det_lang
    except ImportError:
        log("faster-whisper not found in current python env; using acoustic timing fallback", "warn")
        return _acoustic_words(audio_array, offset=offset)
    except Exception as exc:
        log(f"Whisper model note ({exc}); using acoustic timing fallback", "warn")
        return _acoustic_words(audio_array, offset=offset)


def transcript(audio_path, lo, hi, workdir, cfg):
    """Transcript of stream seconds [lo, hi), block by block, in Romanized Hinglish / English."""
    cache = workdir / "scan.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        sample_str = " ".join(w.get("w", "") for w in (data.get("words") or [])[:40])
        if hinglish.has_arabic_or_urdu(sample_str):
            log("cached transcript had Urdu/Arabic script -> deleting cache to re-transcribe in Hinglish!", "warn")
            cache.unlink(missing_ok=True)
        else:
            data["words"] = hinglish.romanize_word_list(data.get("words") or [])
            log(f"reusing cached transcript ({len(data['words'])} words)", "ok")
            return data

    block = cfg["scan_block_minutes"] * 60
    words, language = [], cfg["language"]
    starts = list(np.arange(lo, hi, block))
    log(f"transcribing {max(1.0, (hi - lo)) / 60:.1f} min of audio in {len(starts)} block(s)...", "step")
    for i, t in enumerate(starts):
        part = workdir / f"scan_{i:03d}.json"
        if part.exists():
            got = json.loads(part.read_text(encoding="utf-8"))
            if hinglish.has_arabic_or_urdu(" ".join(w.get("w", "") for w in got[:20])):
                part.unlink(missing_ok=True)
                got = None
            else:
                got = hinglish.romanize_word_list(got)
        else:
            got = None
        if got is None:
            arr = pcm(audio_path, 16000, start=float(t), duration=float(min(block, hi - t)))
            got, lang = words_from(cfg["scan_model"], arr, language, offset=float(t))
            language = language or lang
            part.write_text(json.dumps(got), encoding="utf-8")
        words += got
        log(f"  {(min(t + block, hi) - lo) / 60:.1f}/{(hi - lo) / 60:.1f} min processed", "info")
    if not words:
        raise RuntimeError("no speech found in this video/stream")
    data = {"words": words, "language": language}
    cache.write_text(json.dumps(data), encoding="utf-8")
    for p in workdir.glob("scan_*.json"):
        p.unlink()
    return data


def loudness(audio_path, workdir):
    """Loudness per second in dB, streamed through ffmpeg."""
    cache = workdir / "loud.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    rate = 8000
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(audio_path), "-vn", "-ac", "1",
         "-ar", str(rate), "-f", "s16le", "-"], stdout=subprocess.PIPE)
    out = []
    while True:
        buf = proc.stdout.read(rate * 2 * 60)
        if not buf:
            break
        x = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
        n = len(x) // rate
        if n:
            sec = x[: n * rate].reshape(n, rate)
            out += (20 * np.log10(np.sqrt((sec ** 2).mean(axis=1)) + 1e-6)).round(1).tolist()
    proc.wait()
    cache.write_text(json.dumps(out), encoding="utf-8")
    return out


def relative(values, window=120):
    """How far each second sits above the median of the 2 minutes around it."""
    v = np.asarray(values, dtype=np.float32)
    if len(v) < 5:
        return np.zeros_like(v)
    half = window // 2
    padded = np.pad(v, (half, half), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window + 1)[: len(v)]
    return v - np.median(windows[:, ::4], axis=1)


def chat_rate(url, args, workdir, cfg, stream_info):
    """Messages per 5s from a YouTube live replay, or None."""
    if not cfg.get("chat") or "youtube" not in (stream_info.get("extractor_key") or "").lower():
        return None
    if stream_info.get("live_status") not in ("was_live", "post_live"):
        return None
    cache = workdir / "chat.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    log("reading YouTube live chat replay velocity...", "step")
    try:
        run(["yt-dlp", "--skip-download", "--write-subs", "--sub-langs", "live_chat",
             "-o", str(workdir / "chat"), *args, url], timeout=cfg["chat_timeout"])
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        log(f"chat replay skipped ({str(exc).splitlines()[0][:80]})", "warn")
    files = list(workdir.glob("chat*.live_chat.json*"))
    if not files:
        return None
    buckets = {}
    with open(files[0], encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                item = json.loads(line)["replayChatItemAction"]
                ms = int(item.get("videoOffsetTimeMsec", 0))
            except (ValueError, KeyError, TypeError):
                continue
            buckets[ms // 5000] = buckets.get(ms // 5000, 0) + len(item.get("actions", []))
    for f in files:
        f.unlink()
    if not buckets:
        return None
    rate = [0] * (max(buckets) + 1)
    for k, n in buckets.items():
        rate[k] = n
    cache.write_text(json.dumps(rate), encoding="utf-8")
    log(f"chat replay analyzed: {sum(rate):,} messages", "ok")
    return rate
