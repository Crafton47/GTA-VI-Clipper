"""Make each clip: fetch only its video, verify audio alignment against the stream
(re-fetching via direct ffmpeg seek if YouTube `/live/` DVR drifted!), frame it 9:16
with the FING Plays GTA 6 Sunset-Gradient Seam Banner, and encode."""

import json
from pathlib import Path

import numpy as np

from . import captions, fetch, hinglish, hook, layout, scan, visuals
from .util import log, pcm, probe, run, slugify

PAD = 4.0   # extra seconds fetched on each side, trimmed off after alignment


def _envelope(x, rate=8000, hop=80):
    n = len(x) // hop
    return np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-9)


def locate(clip_file, audio_file, guess, audio_offset=0.0, search=45.0):
    """Where clip_file's first frame sits in the stream (seconds), found by matching
    its sound against the stream audio. Returns (seconds, confidence 0-1)."""
    a = _envelope(pcm(clip_file, 8000, 0, 20)).astype(np.float32)
    b_start = max(0.0, guess - audio_offset - search)
    b = _envelope(pcm(audio_file, 8000, b_start, 20 + 2 * search)).astype(np.float32)
    if len(a) < 200 or len(b) <= len(a):
        return guess, 0.0
    a = (a - a.mean()) / (a.std() + 1e-9)
    win = np.lib.stride_tricks.sliding_window_view(b, len(a))
    mu, sd = win.mean(axis=1), win.std(axis=1) + 1e-9
    corr = ((win - mu[:, None]) @ a) / (len(a) * sd)
    k = int(np.argmax(corr))
    return audio_offset + b_start + k / 100.0, float(corr[k])


def detect_fast_encoder():
    """Detect best available hardware H.264 encoder across NVIDIA (NVENC), Apple, Intel, AMD, or fast CPU."""
    try:
        out = run(["ffmpeg", "-hide_banner", "-encoders"], timeout=10)
        for enc in ("h264_nvenc", "h264_videotoolbox", "h264_qsv", "h264_amf"):
            if enc in out:
                return enc
    except Exception:
        pass
    return "libx264"


def _video_args(cfg):
    enc = cfg["encoder"]
    if enc == "fast_auto":
        enc = detect_fast_encoder()
    if "videotoolbox" in enc:
        return ["-c:v", enc, "-b:v", "10M", "-profile:v", "high"]
    if "nvenc" in enc:
        return ["-c:v", enc, "-preset", "p4", "-cq", str(cfg["crf"]), "-b:v", "0"]
    if enc in ("h264_qsv", "h264_amf"):
        return ["-c:v", enc, "-b:v", "8M"]
    return ["-c:v", "libx264", "-crf", str(cfg["crf"]), "-preset", cfg["preset"]]


def _esc(path):
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def prepare(url, args, audio_file, moment, index, workdir, cfg, language, local_video=None):
    """Fetch one clip's video, verify its audio matches the exact stream timestamp (fixing
    YouTube `/live/` DVR drift automatically), trim dead air, and analyze frames."""
    start, end = moment["start"], moment["end"]
    dur = end - start
    name = f"{index:02d}_{slugify(moment.get('title') or moment.get('hook_text'))}"
    log(f"[clip {index}] {moment.get('hook_text', '')}  ({dur:.0f} s)", "step")
    part_path = workdir / f"part_{index:02d}.mp4"
    part = fetch.section(url, args, start - PAD, end + PAD, part_path, cfg, local_source=local_video)
    info = probe(part)
    if not info["width"]:
        raise RuntimeError("the downloaded part has no picture")

    if audio_file is not None and Path(audio_file).exists():
        at, conf = locate(part, audio_file, start - PAD, search=45.0)
        if conf < 0.45 and not local_video and not fetch.is_local_file(url):
            # CRITICAL FIX FOR YOUTUBE `/live/` STREAMS:
            # `yt-dlp --download-sections` returned the wrong DVR timestamp! Re-fetch using direct ffmpeg seek!
            log(f"  yt-dlp section drifted on live/DVR manifest (conf={conf:.2f}) -> re-fetching exact timestamp via direct stream seek...", "warn")
            try:
                part = fetch.section(url, args, start - PAD, end + PAD, part_path, cfg, force_direct=True)
                info = probe(part)
                at, conf = locate(part, audio_file, start - PAD, search=45.0)
            except Exception as exc:
                log(f"  direct stream seek note: {str(exc)[:100]}", "warn")
        offset = start - at if conf >= 0.45 else PAD
    else:
        offset = min(PAD, max(0.0, info["duration"] - dur))

    offset = min(max(offset, 0.0), max(0.0, info["duration"] - dur))
    clip_pcm = pcm(part, 16000, offset, dur)
    if len(clip_pcm) > 16000 * 5:
        env = _envelope(clip_pcm, rate=16000, hop=1600)
        active = np.where(env > 0.004)[0]
        if len(active) > 0:
            last_active_sec = (active[-1] + 1) * 0.1 + 0.6
            if 5.0 <= last_active_sec < dur - 0.8:
                log(f"  trimmed {dur - last_active_sec:.1f}s of trailing dead silence at end of clip", "info")
                dur = round(last_active_sec, 2)
                clip_pcm = clip_pcm[: int(dur * 16000)]

    if not language and hinglish.is_hindi_stream(info):
        language = "hi"
    words, _ = scan.words_from(cfg["caption_model"], clip_pcm, language)
    stream_meta = {"name": info.get("name", ""), "title": info.get("title", "")}
    if cfg.get("burn_captions"):
        words = hinglish.ai_polish_captions(words, stream_meta, cfg)
    else:
        words = hinglish.strip_hallucinations(hinglish.romanize_word_list(words))

    # Trim dead-air radio gaps (>6.5s) and streamer housekeeping ('humare kitne likes ho gaye')
    cut_s, cut_e, words = hinglish.trim_housekeeping_and_dead_air(words, dur, min_keep=15.0)
    if cut_s > 0.0 or cut_e < dur:
        log(f"  tightened clip window by removing dead air / housekeeping: {cut_s:.1f}s..{cut_e:.1f}s (new dur {cut_e - cut_s:.1f}s)", "info")
        offset = round(offset + cut_s, 2)
        dur = round(max(12.0, cut_e - cut_s), 2)

    # Verify Hook Banner against the actual words spoken in this clip
    moment = hinglish.verify_hook_against_clip(moment, words, stream_meta, cfg)
    analysis = layout.analyze(part, offset, offset + dur, info)
    vis = visuals.evaluate_clip_visuals(part, offset, offset + dur, info, analysis=analysis)
    log(f"  visual check: action={vis['action_score']:.0f} graphics={vis['graphics_score']:.0f} cam_alive={vis['cam_alive']}", "info")
    moment["visual_score"] = vis["visual_score"]
    moment["cam_alive"] = vis["cam_alive"]
    return {"index": index, "name": name, "moment": moment, "part": part, "info": info,
            "offset": offset, "dur": dur, "words": words, "analysis": analysis, "visuals": vis}


def learn(p, cfg, known):
    """Quiet pass: let every clip teach `known` where this stream's facecam sits."""
    layout.graph(p["part"], p["offset"], p["offset"] + p["dur"], cfg, p["info"],
                 known=known, analysis=p["analysis"], quiet=True)


def finish(p, outdir, workdir, cfg, known):
    """Frame 9:16, place the GTA 6 sunset-gradient seam banner (and optional captions), and encode."""
    m, dur, part, name = p["moment"], p["dur"], p["part"], p["name"]
    dest = outdir / f"{name}.mp4"
    log(f"[clip {p['index']}] framing + encoding", "step")
    chain, look, cam_h = layout.graph(part, p["offset"], p["offset"] + dur, cfg, p["info"],
                                      known=known, analysis=p["analysis"])

    # Clean unobstructed gameplay by default (like FING Plays Shorts hwyOH_kqBX8 & YD4xQw0QtHk);
    # only burn word-by-word ASS captions if `--captions` (`burn_captions: True`) is enabled!
    if cfg.get("burn_captions"):
        ass = captions.build(p["words"], 0.0, dur, workdir / f"{name}.ass", cfg, cam_h=cam_h)
        chain += f";[vout]ass=f='{_esc(ass)}'[v]"
    else:
        chain += ";[vout]null[v]"

    cmd = ["ffmpeg", "-y", "-v", "-error".lstrip("-"), "-nostdin", "-ss", f"{p['offset']:.3f}", "-t", f"{dur:.3f}",
           "-i", str(part)]
    if m.get("hook_text"):
        try:
            png, _, hh = hook.render(m["hook_text"], cfg, workdir / f"{name}_hook.png")
            top = int(cam_h - hh / 2) if cam_h else int(cfg["output_height"] * cfg["hook_y"])
            cmd += ["-i", str(png)]
            chain = chain.replace("[v]", "[vh]") + f";[vh][1:v]overlay=(W-w)/2:{top}[v]"
        except (OSError, ValueError) as exc:
            log(f"  title bar skipped ({exc})", "warn")
    speech = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]" if cfg["loudnorm"] else "[0:a]anull[a]"
    cmd += ["-filter_complex", f"{chain};{speech}", "-map", "[v]", "-map", "[a]",
            "-c:a", "aac", "-b:a", cfg["audio_bitrate"], "-ar", "48000",
            *_video_args(cfg), "-movflags", "+faststart", str(dest)]
    run(cmd, timeout=1800)
    part.unlink(missing_ok=True)
    log(f"  -> {dest.name} ({look} layout)", "ok")
    return {
        "file": dest.name, "kind": m.get("kind"), "hook_text": m.get("hook_text"),
        "caption": m.get("caption"), "hashtags": m.get("hashtags", []),
        "score": m.get("score"), "reason": m.get("reason"), "layout": look,
        "stream_start": round(m["start"], 1), "stream_end": round(m["end"], 1), "duration": round(dur, 1),
    }


def combine_showcase(made_clips, outdir, workdir, cfg):
    """Combine 2-3 segments (Environment/Graphics + Action + Reaction) from the rendered clips
    into a single 45-58s Combined Stream Showcase video (`00_game_aspects_showcase.mp4`).
    """
    valid = [c for c in made_clips if (outdir / c["file"]).exists()]
    if len(valid) < 2:
        return None
    picks = valid[:4]
    seg_dur = round(min(18.0, 55.0 / len(picks)), 2)
    slice_files = []
    for idx, c in enumerate(picks):
        src = outdir / c["file"]
        sl = workdir / f"showcase_seg_{idx:02d}.mp4"
        total_d = float(c.get("duration", seg_dur))
        s_off = max(0.0, (total_d - seg_dur) * 0.55) if total_d > seg_dur else 0.0
        run([
            "ffmpeg", "-y", "-v", "error", "-nostdin",
            "-ss", f"{s_off:.2f}", "-t", f"{min(seg_dur, total_d):.2f}",
            "-i", str(src), "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-ar", "48000", str(sl),
        ], timeout=600)
        if sl.exists():
            slice_files.append(sl)

    if len(slice_files) < 2:
        return None

    concat_list = workdir / "showcase_concat.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve()}'" for p in slice_files) + "\n", encoding="utf-8")
    dest = outdir / "00_game_aspects_showcase.mp4"
    run([
        "ffmpeg", "-y", "-v", "error", "-nostdin",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-c", "copy", "-movflags", "+faststart", str(dest),
    ], timeout=600)
    for sl in slice_files:
        sl.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)
    if dest.exists():
        total_showcase_dur = round(sum(min(seg_dur, float(c.get("duration", seg_dur))) for c in picks), 1)
        log(f"  -> {dest.name} (combined {len(picks)} moments: Environment + Graphics + Action, {total_showcase_dur:.0f}s)", "ok")
        return {
            "file": dest.name,
            "kind": "showcase",
            "hook_text": picks[0].get("hook_text", "Stream highlights 🔥"),
            "caption": "Best milestones, story reactions, and gameplay moments combined 🔥",
            "hashtags": ["#shorts", "#gaming", "#highlights"],
            "score": max(int(c.get("score", 85)) for c in picks),
            "reason": "Combined multi-beat showcase.",
            "layout": picks[0].get("layout", "stream"),
            "stream_start": picks[0].get("stream_start", 0.0),
            "stream_end": picks[-1].get("stream_end", 0.0),
            "duration": total_showcase_dur,
        }
    return None


def post_sheet(outdir, stream, clips, summary):
    """POST.md: Ready-to-paste per-platform copy (X, Instagram Reels, TikTok/Shorts) with 🎥 @creator credit."""
    from . import page_os
    lines = [f"# {stream['name']}: {stream['title']}", "", f"Stream: {stream['url']}", "",
             summary, ""]
    for c in clips:
        m, s = divmod(int(c["stream_start"]), 60)
        h, m = divmod(m, 60)
        copy_blocks = c.get("platform_copy") or page_os.format_platform_captions(c, stream)
        c["platform_copy"] = copy_blocks
        lines += [
            f"## {c['file']}",
            f"**{c['hook_text']}** · {c['duration']:.0f}s · score {c['score']} · {copy_blocks['credit']}",
            "",
            f"{c.get('caption') or ''}",
            f"{copy_blocks['credit']}",
            " ".join((c.get("hashtags") or ["#shorts", "#gaming", "#viral"])[:4]),
            "",
            f"_From stream at {h}:{m:02d}:{s:02d}_",
            "",
            "---",
            "",
        ]
    (outdir / "POST.md").write_text("\n".join(lines), encoding="utf-8")
    (outdir / "clips.json").write_text(json.dumps({"stream": stream, "clips": clips}, indent=2), encoding="utf-8")
