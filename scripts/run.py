#!/usr/bin/env python3
"""autoclip / gta6clip: Drop any YouTube/Twitch/Kick link (or local video) -> ready-to-post 9:16 viral clips out.

ZERO-FULL-DOWNLOAD MODE (Default for YouTube Videos & VODs):
  1. Grabs YouTube's word-timed transcript (`--skip-download --sub-format json3`) + "Most Replayed" heatmap in ~2 seconds
     WITHOUT downloading the full stream or full audio!
  2. Free AI (`EXPLABS_API_KEY` -> `OPENROUTER_API_KEY` -> `GEMINI_API_KEY` -> `CODECRAFT_API_KEY` -> `NVIDIA_API_KEY`)
     ranks the viral moments in ~3 seconds.
  3. Downloads ONLY the winning 15-60s video clips (`yt-dlp --download-sections`), runs local Whisper `base` on those
     short clips for exact pop captions, frames them 9:16, and outputs ready-to-post `.mp4` files!
  (Falls back to full/section audio download only if a video has no captions or `--full-audio` is passed.)
"""

import argparse
import datetime
import json
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from clipper import config, fetch, find, moments, page_os, render, scan  # noqa: E402
from clipper.util import Timer, die, hhmmss, log, minutes, probe, require, set_tag, slugify  # noqa: E402


def parse(argv):
    p = argparse.ArgumentParser(prog="autoclip", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("urls", nargs="*", help="YouTube / Twitch / Kick links or local video paths")
    p.add_argument("--find", action="store_true", help="find today's biggest streams for --topic / search")
    p.add_argument("--list", action="store_true", help="with --find: only list them")
    p.add_argument("--streams", type=int, default=5, help="with --find: how many streams (default 5)")
    p.add_argument("--clips", type=int, help="clips per video/stream (default 3)")
    p.add_argument("--parallel", type=int, default=2, help="streams processed at once (default 2)")
    p.add_argument("--section", metavar="RANGE",
                   help="only analyze & clip this part of a video/stream, e.g. \"0:10:00-0:30:00\"")
    p.add_argument("--full-audio", action="store_true",
                   help="force downloading full audio for local Whisper scan instead of instant YouTube captions")
    p.add_argument("--live-minutes", type=int, default=10,
                   help="when clipping a currently LIVE stream: minutes to capture per pass (default 10)")
    p.add_argument("--watch-live", action="store_true",
                   help="continuously watch a LIVE stream in rolling chunks and output clips in real time")
    p.add_argument("--live-rounds", type=int, default=6,
                   help="with --watch-live: number of rolling live windows to capture (default 6)")
    p.add_argument("--cookies", choices=["chrome", "safari", "firefox", "brave", "edge"],
                   help="use browser login (for age-restricted YouTube or Kick)")
    p.add_argument("--caption-style", choices=["classic", "box", "karaoke", "minimal", "bold", "comic"],
                   help="ClipKaro caption look (default: classic)")
    p.add_argument("--layout", choices=["auto", "stream", "face", "fit"],
                   help="9:16 framing mode (default: auto)")
    p.add_argument("--provider", dest="llm_provider",
                   choices=["auto", "experiential", "openrouter", "gemini", "codecraft", "groq", "nvidia", "ollama", "claude", "heuristic"],
                   help="free AI provider for viral moment selection (default: auto)")
    p.add_argument("--model", dest="llm_model",
                   help="specific free model ID")
    p.add_argument("--topic", help="video topic or niche hint (default: auto)")
    p.add_argument("--lang", dest="language", help="audio language code, e.g. hi for Hindi/Hinglish or en (default: auto)")
    p.add_argument("--outdir", help="custom output directory for finished clips")
    p.add_argument("--min", dest="min_duration", type=int, help="shortest clip in seconds (default 15)")
    p.add_argument("--max", dest="max_duration", type=int, help="longest clip in seconds (default 60)")
    p.add_argument("--fast", action="store_true", help="hardware GPU encoding (NVENC / VideoToolbox / QSV)")
    p.add_argument("--keep-audio", action="store_true", help="keep the full audio file after clipping")
    p.add_argument("--redo", action="store_true", help="re-pick moments (keeps cached transcript)")
    p.add_argument("--tight", action="store_true", help="enforce tight 7-30s trim for Reels/TikTok (Section 6 rule)")
    p.add_argument("--init-page", action="store_true", help="initialize full Faceless Clipping Page folder & file structure (Section 15)")
    p.add_argument("--daily-pack", action="store_true", help="generate today's 6-slot daily content queue (News, HOW TO, Nostalgia, Spotlight, Countdown, Question)")
    p.add_argument("--review", action="store_true", help="analyze scoreboard.csv and update learning.md (Section 13 learning loop)")
    p.add_argument("--page-dir", help="custom directory for the Faceless Page OS files (default: ~/viral-clips/page)")
    return p.parse_args(argv)


def seconds(stamp):
    total = 0.0
    for part in stamp.strip().split(":"):
        total = total * 60 + float(part)
    return total


def one_stream(url, cfg, opts, live_round=None):
    """Run the complete end-to-end pipeline for one URL or local video."""
    timer = Timer()
    args = fetch.base_args(url, opts.cookies)
    key = re.sub(r"[^A-Za-z0-9_-]", "_", str(url).split("://")[-1])[-80:]
    if live_round is not None:
        key = f"{key}_live_r{live_round:02d}_{int(time.time())}"
    work = config.HOME / "work" / key
    work.mkdir(parents=True, exist_ok=True)

    with timer.stage("look up"):
        info = fetch.info(url, args, work)
    set_tag(info["name"][:18])
    if page_os.is_creator_blocked(info["name"], opts.page_dir):
        raise RuntimeError(f"Creator '{info['name']}' is on the takedowns.md do-not-clip list! Skipping.")
    is_live = (info.get("live_status") == "is_live") or bool(info.get("is_live")) or opts.watch_live

    sec_range = None
    if opts.section and not is_live:
        a, _, b = opts.section.lstrip("*").partition("-")
        sec_lo = seconds(a)
        sec_hi = seconds(b) if b else (info.get("duration") or (sec_lo + 1800))
        sec_range = (sec_lo, sec_hi)

    pick_dir = work if not sec_range else work / f"part_{int(sec_range[0])}_{int(sec_range[1])}"
    pick_dir.mkdir(exist_ok=True)
    if opts.redo:
        for f in ("moments.json", "candidates.json"):
            (pick_dir / f).unlink(missing_ok=True)

    # STEP 1: Try Instant Zero-Download Transcript + Heatmap first (for YouTube VODs/videos)!
    heard = None
    audio = None
    live_video_path = None
    base_offset = 0.0

    if not is_live and not opts.full_audio and not fetch.is_local_file(url):
        with timer.stage("instant transcript"):
            lo_q = sec_range[0] if sec_range else 0.0
            hi_q = sec_range[1] if sec_range else info.get("duration")
            heard = fetch.youtube_subs(url, args, work, lo=lo_q, hi=hi_q)

    if heard is not None:
        length = float(info.get("duration") or heard["words"][-1]["e"])
        lo = sec_range[0] if sec_range else 0.0
        hi = sec_range[1] if sec_range else length
        loud = fetch.heatmap_curve(info, length)
        if not loud:
            # No YouTube heatmap on this video -> fetch lightweight low-bitrate audio so we never miss screams/soundboards!
            log("no YouTube replay heatmap found -> fetching fast low-bitrate audio for exact scream/soundboard dB detection...", "step")
            audio_res = fetch.audio(url, args, work, section_range=sec_range, is_live=False, cfg=cfg)
            audio = audio_res[0]
            loud = scan.relative(scan.loudness(audio, work))
        chat = scan.chat_rate(url, args, work, cfg, info)
        log(f"{info['title'][:70]}  ·  {minutes(length)} (Instant Transcript + Scream/Spike Detection ready)", "ok")
    else:
        # Fallback: download audio (bounded if live, section-only if --section, or full audio if uncaptioned VOD)
        if is_live:
            log(f"STREAM IS LIVE! Capturing a {opts.live_minutes}-minute live window directly...", "step")
        with timer.stage("download audio"):
            audio_res = fetch.audio(
                url, args, work,
                section_range=sec_range,
                is_live=is_live,
                live_minutes=opts.live_minutes,
                cfg=cfg,
            )
            if is_live and isinstance(audio_res[1], Path):
                audio, live_video_path = audio_res[0], audio_res[1]
                is_pre_sliced = False
            else:
                audio, is_pre_sliced = audio_res[0], bool(audio_res[1])
                live_video_path = None

        length = probe(audio)["duration"]
        if sec_range and not is_pre_sliced:
            lo, hi = sec_range[0], min(sec_range[1], length)
        else:
            lo, hi = 0.0, length
        base_offset = sec_range[0] if (sec_range and is_pre_sliced) else 0.0
        log(f"{info['title'][:70]}  ·  {minutes(length)}", "ok")

        with timer.stage("listen"):
            heard = scan.transcript(audio, lo, hi, pick_dir, cfg)
            loud = scan.relative(scan.loudness(audio, work))
            chat = scan.chat_rate(url, args, work, cfg, info) if not is_live else None

    stream = {"name": info["name"], "title": info["title"], "url": url}
    with timer.stage("pick"):
        raw_picked = moments.find(heard, loud, chat, pick_dir, cfg, stream)
        picked = []
        for mp in raw_picked:
            clean_m = page_os.sanitize_hook_and_safety(mp, stream)
            if clean_m:
                picked.append(clean_m)

    if base_offset > 0:
        for m in picked:
            m["start"] = round(m["start"] + base_offset, 2)
            m["end"] = round(m["end"] + base_offset, 2)

    day = datetime.date.today().isoformat()
    if opts.outdir:
        outdir = Path(opts.outdir).expanduser().resolve()
    else:
        suffix = f"__live_r{live_round:02d}" if live_round is not None else ""
        outdir = config.HOME / day / f"{slugify(info['name'], 24)}__{slugify(info['title'], 40)}{suffix}"
    outdir.mkdir(parents=True, exist_ok=True)

    made, ready, known = [], [], {}
    with timer.stage("make clips"):
        for i, m in enumerate(picked, 1):
            try:
                ready.append(render.prepare(url, args, audio, m, i, pick_dir, cfg,
                                            heard.get("language"), local_video=live_video_path))
            except Exception as exc:
                log(f"[clip {i}] prepare failed: {str(exc)[:300]}", "err")
        for p in ready:
            render.learn(p, cfg, known)
        for p in ready:
            try:
                made.append(render.finish(p, outdir, pick_dir, cfg, known))
            except Exception as exc:
                log(f"[clip {p['index']}] render failed: {str(exc)[:300]}", "err")

    summary = (f"{minutes(hi - lo)} source -> {len(made)} clip(s) in {minutes(timer.total())} "
               f"(" + ", ".join(f"{k} {minutes(v)}" for k, v in timer.stages.items()) + ")")
    page_os.record_clips_to_page_os(outdir, stream, made, opts.page_dir)
    render.post_sheet(outdir, stream, made, summary)
    (outdir / "report.json").write_text(json.dumps({
        "stream": stream, "stream_seconds": round(hi - lo), "clips": len(made),
        "total_seconds": round(timer.total()),
        "stages_seconds": {k: round(v) for k, v in timer.stages.items()},
        "llm_provider": moments.resolve_provider(cfg),
        "zero_full_download": audio is None}, indent=2), encoding="utf-8")
    if not opts.keep_audio and made and not fetch.is_local_file(url):
        if audio:
            audio.unlink(missing_ok=True)
        if live_video_path:
            live_video_path.unlink(missing_ok=True)
    log(summary, "ok")
    set_tag("")
    return {"name": info["name"], "title": info["title"], "outdir": outdir, "clips": made,
            "summary": summary}


def main(argv=None):
    opts = parse(argv if argv is not None else sys.argv[1:])
    require("ffmpeg", "install ffmpeg")
    if any(not fetch.is_local_file(u) for u in opts.urls) or opts.find:
        require("yt-dlp", "run python3 scripts/setup.py")

    cfg = config.load({
        "clips_per_stream": opts.clips,
        "layout": opts.layout,
        "caption_style": opts.caption_style,
        "llm_provider": opts.llm_provider,
        "llm_model": opts.llm_model,
        "topic": opts.topic,
        "language": opts.language,
        "min_duration": opts.min_duration,
        "max_duration": opts.max_duration,
        "encoder": "fast_auto" if opts.fast else None,
        "search": opts.topic if (opts.topic and opts.topic != "auto") else None,
    })
    config.HOME.mkdir(parents=True, exist_ok=True)

    if opts.tight:
        cfg["min_duration"] = 7
        cfg["max_duration"] = 30
    page_root = page_os.init_page_workspace(opts.page_dir)
    if opts.init_page and not opts.urls and not opts.find and not opts.daily_pack and not opts.review:
        log(f"Faceless Clipping Page workspace initialized at: {page_root}", "ok")
        return
    if opts.daily_pack:
        q_file = page_os.generate_daily_pack(cfg, opts.page_dir)
        print(q_file.read_text(encoding="utf-8"))
        if not opts.urls and not opts.find:
            return
    if opts.review:
        rep = page_os.review_scoreboard(opts.page_dir)
        print(rep)
        if not opts.urls and not opts.find:
            return

    urls = list(opts.urls)
    if opts.find:
        log(f"finding today's biggest streams for '{cfg['search']}'...", "step")
        found = find.find(cfg, limit=opts.streams)
        if not found:
            die("no matching streams found right now. Paste a YouTube/Twitch link directly.")
        for i, s in enumerate(found, 1):
            live = "LIVE " if s["live"] else ""
            print(f"  {i}. {s['name'][:22]:22} {s['views']:>10,} {live}· {s['title'][:60]}  ({s['source']})")
            print(f"     {s['url']}")
        if opts.list:
            return
        urls += [s["url"] for s in found]
    if not urls:
        die("drop one or more YouTube / Twitch / Kick links (or local video files), or use --find")

    results = []
    if opts.watch_live:
        for r_idx in range(1, opts.live_rounds + 1):
            log(f"=== LIVE WATCHER ROUND {r_idx}/{opts.live_rounds} ({opts.live_minutes}m window) ===", "step")
            for u in urls:
                try:
                    results.append(one_stream(u, cfg, opts, live_round=r_idx))
                except Exception as exc:
                    log(f"{u} (round {r_idx}): {str(exc)[:300]}", "err")
    else:
        with ThreadPoolExecutor(max_workers=max(1, opts.parallel)) as pool:
            futures = {pool.submit(one_stream, u, cfg, opts): u for u in urls}
            for fut, url in futures.items():
                try:
                    results.append(fut.result())
                except Exception as exc:
                    msg = str(exc)
                    if "confirm your age" in msg or "Sign in to confirm" in msg:
                        msg = "YouTube requires login for this age-restricted video. Re-run with --cookies chrome."
                    elif "403" in msg and "kick" in str(url):
                        msg = "Kick blocked the download. Re-run with --cookies chrome."
                    log(f"{url}: {msg[:400]}", "err")

    total = sum(len(r["clips"]) for r in results)
    log(f"done: {total} ready-to-post vertical clip(s) from {len(results)} run(s)", "ok")
    for r in results:
        print(f"\n  {r['name']} · {r['title'][:60]}\n  {r['summary']}\n  Output folder: {r['outdir']}")
        for c in r["clips"]:
            print(f"    [{c['score']}] {c['duration']:>3.0f}s @{hhmmss(c['stream_start'])}  {c['hook_text']} -> {c['file']}")


if __name__ == "__main__":
    main()
