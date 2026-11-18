"""Instant metadata, YouTube caption/heatmap extraction, and accurate VOD/Live clip downloading.

Fixes the YouTube `/live/` & DVR stream timestamp drift bug:
- On `/live/` or `was_live` stream URLs, `yt-dlp --download-sections` can grab segments from the
  wrong DVR offset (e.g., grabbing a random highway bike ride instead of the detected moment).
- `section()` now passes `--force-keyframes-at-cuts` and provides `section_direct_ffmpeg()`, which
  resolves the underlying video+audio stream URLs via `yt-dlp -g` and seeks with `ffmpeg -ss` before `-i`
  so the extracted clip is 100% locked to the exact timestamp of the moment!
"""

import glob
import json
import shutil
from pathlib import Path

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


def youtube_subs(url, args, workdir, lo=0.0, hi=None, stream_info=None):
    """Fetch word-timed transcript directly from YouTube captions (--skip-download) in ~2s
    without downloading any video or audio!
    NOTE: If the stream is a Hindi stream (`is_hindi_stream`), we prefer Hindi (`hi`) captions first
    and never use auto-translated English captions!
    """
    if is_local_file(url):
        return None
    is_hi = hinglish.is_hindi_stream(stream_info or {})
    cache = workdir / "yt_fast_scan.json"
    if cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if is_hi and data.get("language") == "en":
            cache.unlink(missing_ok=True)
        else:
            words = hinglish.romanize_word_list([w for w in data["words"] if w["e"] > lo and (hi is None or w["s"] < hi)])
            if len(words) >= 20:
                log(f"reusing instant YouTube transcript ({len(words)} words, 0 MB media downloaded)", "ok")
                return {"words": words, "language": data.get("language", "hi" if is_hi else "en")}

    log("fetching instant transcript from YouTube (--skip-download, no full stream download)...", "step")
    for old in workdir.glob("yt_subs*"):
        old.unlink(missing_ok=True)
    sub_langs = "hi.*,hi,en.*,en" if is_hi else "en.*,en,hi.*,hi,es.*,pt.*,fr.*,de.*,ja.*"
    try:
        run([
            "yt-dlp", "--skip-download", "--no-playlist",
            "--write-subs", "--write-auto-subs",
            "--sub-langs", sub_langs,
            "--sub-format", "json3",
            "-o", str(workdir / "yt_subs"),
            *args, url,
        ], timeout=90)
    except Exception as exc:
        log(f"instant YouTube captions unavailable ({str(exc).splitlines()[0][:80]}) -> will use audio fallback", "warn")
        return None

    if is_hi:
        sub_files = sorted(workdir.glob("yt_subs*.json3"), key=lambda p: (0 if ".hi" in p.name else 1, p.name))
    else:
        sub_files = sorted(workdir.glob("yt_subs*.json3"), key=lambda p: (0 if ".en" in p.name else 1, p.name))
    if not sub_files:
        return None

    chosen = sub_files[0]
    lang = "hi" if is_hi else "en"
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

        raw_tokens = []
        for s in segs:
            txt = (s.get("utf8") or "").replace("\n", " ").strip()
            if not txt or (txt.startswith("[") and txt.endswith("]")):
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
    full_data = {"words": words, "language": lang}
    cache.write_text(json.dumps(full_data), encoding="utf-8")
    filtered = [w for w in words if w["e"] > lo and (hi is None or w["s"] < hi)]
    if len(filtered) < 20:
        return None
    log(f"instant YouTube transcript ready ({len(filtered):,} words fetched in seconds, 0 MB stream download!)", "ok")
    return {"words": filtered, "language": lang}


def heatmap_curve(stream_info, total_seconds):
    """Convert YouTube's 'Most Replayed' heatmap into a dB-equivalent excitement curve."""
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
    """Download lightweight audio track for vocal spike detection and exact frame alignment."""
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


def section_direct_ffmpeg(url, args, start, end, dest, cfg):
    """Fallback exact timestamp slicer for `/live/` DVR streams when `yt-dlp --download-sections`
    grabs the wrong offset: resolves direct stream URLs via `yt-dlp -g` and seeks with `ffmpeg -ss`!
    """
    start = max(0.0, start)
    dur = max(2.0, end - start)
    h = cfg["max_height"]
    for leftover in glob.glob(str(dest) + "*"):
        Path(leftover).unlink(missing_ok=True)
    raw_urls = run([
        "yt-dlp", "--no-playlist", "-g",
        "-f", f"bv*[height<={h}][protocol^=http]+ba[protocol^=http]/b[height<={h}]/bv*+ba/b",
        *args, url,
    ], timeout=120).strip().splitlines()
    raw_urls = [u.strip() for u in raw_urls if u.strip()]
    if not raw_urls:
        raise RuntimeError("could not resolve direct stream URLs via yt-dlp -g")
    if len(raw_urls) >= 2:
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-nostdin",
            "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", raw_urls[0],
            "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", raw_urls[1],
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", str(dest),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-nostdin",
            "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", raw_urls[0],
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
            "-c:a", "aac", str(dest),
        ]
    run(cmd, timeout=900)
    if not dest.exists():
        raise RuntimeError(f"direct ffmpeg seek failed for {start:.0f}-{end:.0f}s")
    return dest


def section(url, args, start, end, dest, cfg, local_source=None, force_direct=False):
    """Download ONLY the specific viral clip segment [start, end]."""
    start = max(0.0, start)
    if not force_direct and dest.exists() and dest.stat().st_size > 10000:
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

    if force_direct:
        return section_direct_ffmpeg(url, args, start, end, dest, cfg)

    h = cfg["max_height"]
    for leftover in glob.glob(str(dest) + "*"):
        Path(leftover).unlink(missing_ok=True)
    try:
        run([
            "yt-dlp", "--no-playlist",
            "-f", f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b",
            "--merge-output-format", "mp4",
            "--download-sections", f"*{start:.2f}-{end:.2f}",
            "--force-keyframes-at-cuts",
            "-o", str(dest), *args, url,
        ], timeout=1800)
    except Exception:
        return section_direct_ffmpeg(url, args, start, end, dest, cfg)
    if not dest.exists():
        return section_direct_ffmpeg(url, args, start, end, dest, cfg)
    return dest
