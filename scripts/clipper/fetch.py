"""Instant metadata, YouTube caption/heatmap extraction, and targeted clip-only downloading.

By default, for YouTube links, the full video/audio is NEVER downloaded:
1. `info()` grabs stream metadata + YouTube's "Most Replayed" `heatmap` in ~1 second.
2. `youtube_subs()` grabs YouTube's word-timed `json3` captions in ~2 seconds (`--skip-download`).
3. Only after AI picks the winning 15-60s viral timestamps does `section()` download those specific clips!
Full audio download (`audio()`) is used only as a fallback if a stream has no captions or `--full-audio` is set.
"""

import glob
import json
import shutil
from pathlib import Path

from . import hinglish
from . import hinglish
from . import hinglish
from .util import log, probe, run


def is_local_file(url_or_path):
    p = Path(str(url_or_path)).expanduser()
    return p.exists() and p.is_file()


def base_args(url, cookies=None):
    """JS runtime for YouTube + optional browser cookies."""
    if is_local_file(url):
        return []
    args = []
    if "youtu" in str(url) and not shutil.which("deno"):
        for runtime in ("node", "bun"):
            path = shutil.which(runtime)
            if path:
                args += ["--js-runtimes", f"{runtime}:{path}"]
                break
    # ClipKaro Windows fix: auto-detect cookies.txt first (since Windows Chrome locks its cookie DB while open)
    skill_root = Path(__file__).resolve().parent.parent.parent
    for ck in (Path.cwd() / "cookies.txt", skill_root / "cookies.txt", Path.home() / "viral-clips" / "cookies.txt"):
        if ck.exists() and ck.stat().st_size > 50:
            args += ["--cookies", str(ck)]
            return args
    if cookies:
        args += ["--cookies-from-browser", cookies]
    return args


def info(url, args, workdir):
    """Video/stream metadata (title, channel, length, live status, Most Replayed heatmap). Cached."""
    cache = workdir / "info.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("live_status") != "is_live":
            return data
    if is_local_file(url):
        p = Path(url).expanduser().resolve()
        meta = probe(p)
        keep = {
            "id": p.stem,
            "title": p.stem.replace("_", " ").replace("-", " "),
            "channel": "Creator",
            "uploader": "Creator",
            "name": "Creator",
            "duration": meta["duration"],
            "view_count": 0,
            "live_status": "not_live",
            "was_live": False,
            "is_live": False,
            "webpage_url": str(p),
            "extractor_key": "local",
            "local_path": str(p),
            "heatmap": None,
        }
        cache.write_text(json.dumps(keep, indent=2), encoding="utf-8")
        return keep

    raw = run(["yt-dlp", "-J", "--no-playlist", *args, url], timeout=180)
    full = json.loads(raw)
    keep = {k: full.get(k) for k in (
        "id", "title", "channel", "uploader", "duration", "view_count", "live_status",
        "was_live", "is_live", "webpage_url", "extractor_key", "timestamp", "release_timestamp",
        "heatmap",
    )}
    keep["name"] = keep.get("channel") or keep.get("uploader") or "Creator"
    cache.write_text(json.dumps(keep, indent=2), encoding="utf-8")
    return keep


def youtube_subs(url, args, workdir, lo=0.0, hi=None):
    """Fetch word-timed transcript directly from YouTube captions (--skip-download) in ~2s
    without downloading any video or audio! Returns {"words": [...], "language": ...} or None.
    """
    if is_local_file(url):
        return None
    cache = workdir / "yt_fast_scan.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        words = hinglish.romanize_word_list([w for w in data["words"] if w["e"] > lo and (hi is None or w["s"] < hi)])
        if len(words) >= 20:
            log(f"reusing instant YouTube transcript ({len(words)} words, 0 MB media downloaded)", "ok")
            return {"words": words, "language": data.get("language", "en")}

    log("fetching instant transcript from YouTube (--skip-download, no full stream download)...", "step")
    for old in workdir.glob("yt_subs*"):
        old.unlink(missing_ok=True)
    try:
        run([
            "yt-dlp", "--skip-download", "--no-playlist",
            "--write-subs", "--write-auto-subs",
            "--sub-langs", "en.*,en,hi.*,es.*,pt.*,fr.*,de.*,ja.*",
            "--sub-format", "json3",
            "-o", str(workdir / "yt_subs"),
            *args, url,
        ], timeout=90)
    except Exception as exc:
        log(f"instant YouTube captions unavailable ({str(exc).splitlines()[0][:80]}) -> will use audio fallback", "warn")
        return None

    sub_files = sorted(workdir.glob("yt_subs*.json3"), key=lambda p: (0 if ".en" in p.name else 1, p.name))
    if not sub_files:
        return None

    chosen = sub_files[0]
    lang = "en"
    parts = chosen.name.split(".")
    if len(parts) >= 3:
        lang = parts[-2].split("-")[0]

    try:
        raw = json.loads(chosen.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None

    words = []
    for ev in raw.get("events") or []:
        segs = ev.get("segs")
        if not segs:
            continue
        t_start = float(ev.get("tStartMs", 0)) / 1000.0
        d_dur = float(ev.get("dDurationMs", 1500)) / 1000.0
        ev_end = t_start + max(0.2, d_dur)

        # Extract word tokens with exact or interpolated timestamps
        raw_tokens = []
        for s in segs:
            txt = (s.get("utf8") or "").replace("\n", " ").strip()
            if not txt or txt.startswith("[") and txt.endswith("]"):
                continue
            off = float(s.get("tOffsetMs", 0)) / 1000.0
            for piece in txt.split():
                if piece:
                    raw_tokens.append((t_start + off, piece))

        for i, (w_start, piece) in enumerate(raw_tokens):
            if i + 1 < len(raw_tokens) and raw_tokens[i + 1][0] > w_start:
                w_end = min(ev_end, raw_tokens[i + 1][0])
            else:
                step = max(0.12, (ev_end - w_start) / max(1, len(raw_tokens) - i))
                w_end = min(ev_end, w_start + step)
            words.append({"s": round(w_start, 2), "e": round(max(w_start + 0.08, w_end), 2), "w": piece})

    for f in sub_files:
        f.unlink(missing_ok=True)

    if len(words) < 20:
        return None

    words = hinglish.romanize_word_list(words)
    words = hinglish.romanize_word_list(words)
    words = hinglish.romanize_word_list(words)
    full_data = {"words": words, "language": lang}
    cache.write_text(json.dumps(full_data), encoding="utf-8")
    filtered = [w for w in words if w["e"] > lo and (hi is None or w["s"] < hi)]
    if len(filtered) < 20:
        return None
    log(f"instant YouTube transcript ready ({len(filtered):,} words fetched in seconds, 0 MB stream download!)", "ok")
    return {"words": filtered, "language": lang}


def heatmap_curve(stream_info, total_seconds):
    """Convert YouTube's 'Most Replayed' heatmap into a dB-equivalent excitement curve
    so [LOUD +NdB] spike detection works even with 0 MB of audio downloaded!
    """
    hm = stream_info.get("heatmap")
    if not hm or not isinstance(hm, list):
        return []
    n_sec = max(1, int(total_seconds) + 1)
    out = [0.0] * n_sec
    for item in hm:
        try:
            s0 = int(max(0, float(item.get("start_time", 0))))
            e0 = int(min(n_sec, float(item.get("end_time", s0 + 1)) + 1))
            val = float(item.get("value", 0.0))
            # Scale 0..1 heatmap intensity into 0..14 dB excitement boost
            boost = round(val * 14.0, 1)
            for idx in range(s0, e0):
                if boost > out[idx]:
                    out[idx] = boost
        except Exception:
            continue
    return out


def live_chunk(url, args, duration_sec, dest_mp4, cfg):
    """Capture a bounded live stream window (video + audio together) for `duration_sec` seconds."""
    h = cfg.get("max_height", 1080)
    log(f"capturing {duration_sec / 60:.1f} min directly from LIVE stream (bounded capture)...", "step")
    cmd = [
        "yt-dlp", "--no-playlist", "--no-part",
        "-f", f"bv*[height<={h}]+ba/b[height<={h}]/b",
        "--merge-output-format", "mp4",
        "--downloader", "ffmpeg",
        "--downloader-args", f"ffmpeg_i:-t {int(duration_sec)}",
        "-o", str(dest_mp4),
        *args, url,
    ]
    run(cmd, timeout=int(duration_sec) + 300)
    if not dest_mp4.exists():
        matches = list(dest_mp4.parent.glob(dest_mp4.stem + ".*"))
        if matches:
            return matches[0]
        raise RuntimeError("live stream capture finished but no video file was written")
    log(f"captured live chunk: {dest_mp4.name} ({dest_mp4.stat().st_size / 1e6:.1f} MB)", "ok")
    return dest_mp4


def audio(url, args, workdir, section_range=None, is_live=False, live_minutes=10, cfg=None):
    """Fallback audio download (only used when instant YouTube captions are unavailable or for live streams)."""
    if is_local_file(url):
        src = Path(url).expanduser().resolve()
        dest = workdir / "audio.wav"
        if dest.exists() and dest.stat().st_size > 1000:
            return dest, False
        log("extracting audio from local video...", "step")
        run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dest)])
        return dest, False

    if is_live:
        live_mp4 = workdir / f"live_buffer_{int(live_minutes)}m.mp4"
        live_wav = workdir / f"live_buffer_{int(live_minutes)}m.wav"
        if not live_mp4.exists() or live_mp4.stat().st_size < 10000:
            live_chunk(url, args, int(live_minutes * 60), live_mp4, cfg or {"max_height": 1080})
        if not live_wav.exists():
            run(["ffmpeg", "-y", "-v", "error", "-nostdin", "-i", str(live_mp4), "-vn", "-ac", "1", "-ar", "16000", str(live_wav)])
        return live_wav, live_mp4

    if section_range is not None:
        lo, hi = section_range
        sec_tag = f"audio_{int(lo)}_{int(hi)}"
        done_sec = [p for p in workdir.glob(f"{sec_tag}.*") if not p.name.endswith((".part", ".ytdl"))]
        if done_sec:
            log(f"reusing section audio ({done_sec[0].stat().st_size / 1e6:.1f} MB)", "ok")
            return done_sec[0], True
        log(f"downloading audio ONLY for section {int(lo)}s-{int(hi)}s...", "step")
        run([
            "yt-dlp", "--no-playlist", "-f", "wa/ba[abr<=96]/ba/w",
            "--download-sections", f"*{lo:.2f}-{hi:.2f}",
            "-o", str(workdir / f"{sec_tag}.%(ext)s"),
            "--newline", "-N", "4", *args, url,
        ], timeout=3600)
        done_sec = [p for p in workdir.glob(f"{sec_tag}.*") if not p.name.endswith((".part", ".ytdl"))]
        if done_sec:
            return done_sec[0], True

    done = [p for p in workdir.glob("audio.*") if not p.name.endswith((".part", ".ytdl"))]
    if done:
        log(f"reusing audio ({done[0].stat().st_size / 1e6:.1f} MB)", "ok")
        return done[0], False

    log("downloading audio track (video slices come later, only for the winning clips)...", "step")
    run(["yt-dlp", "--no-playlist", "-f", "wa/ba[abr<=96]/ba/w", "-o", str(workdir / "audio.%(ext)s"),
         "--newline", "-N", "4", *args, url], timeout=7200)
    done = [p for p in workdir.glob("audio.*") if not p.name.endswith((".part", ".ytdl"))]
    if not done:
        raise RuntimeError("yt-dlp finished but no audio file appeared")
    log(f"audio downloaded: {done[0].stat().st_size / 1e6:.1f} MB", "ok")
    return done[0], False


def section(url, args, start, end, dest, cfg, local_source=None):
    """Download ONLY the specific 15-60s viral clip segment [start, end]."""
    start = max(0.0, start)
    if dest.exists() and dest.stat().st_size > 10000:
        return dest
    src_file = local_source if local_source else (Path(url).expanduser().resolve() if is_local_file(url) else None)
    if src_file:
        dur = max(1.0, end - start)
        run([
            "ffmpeg", "-y", "-v", "error", "-nostdin",
            "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
            "-i", str(src_file), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", str(dest),
        ], timeout=600)
        return dest

    h = cfg["max_height"]
    for leftover in glob.glob(str(dest) + "*"):
        Path(leftover).unlink(missing_ok=True)
    run([
        "yt-dlp", "--no-playlist",
        "-f", f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
        "--merge-output-format", "mp4",
        "--download-sections", f"*{start:.2f}-{end:.2f}",
        "-o", str(dest), *args, url,
    ], timeout=1800)
    if not dest.exists():
        raise RuntimeError(f"no video came back for {start:.0f}-{end:.0f}s")
    return dest
