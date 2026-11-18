"""Stage 5 — Build word-by-word animated captions as an ASS subtitle file.

Includes ClipKaro enhancements:
- 6 Caption Styles (`--caption-style classic|box|karaoke|minimal|bold|comic`)
- Safe-Zone & Seam Positioning (moves captions onto the facecam/gameplay seam in `stream` layout
  and stays clear of TikTok/Reels right-side Like/Share buttons and bottom UI text)
- Automatic Hinglish romanization & Whisper hallucination filtering
"""

from . import hinglish

HOLD_THROUGH_PAUSE = 1.2

# ClipKaro 6 caption style presets:
# BorderStyle=1 (outline + shadow), BorderStyle=3 (opaque background box)
STYLE_PRESETS = {
    "classic": {"border_style": 1, "outline": 6, "shadow": 3, "back": "&H96000000", "scale": 112},
    "box":     {"border_style": 3, "outline": 14, "shadow": 0, "back": "&HC8000000", "scale": 106},
    "karaoke": {"border_style": 1, "outline": 7, "shadow": 4, "back": "&H96000000", "scale": 118},
    "minimal": {"border_style": 1, "outline": 3, "shadow": 1, "back": "&H64000000", "scale": 100},
    "bold":    {"border_style": 1, "outline": 9, "shadow": 5, "back": "&HB4000000", "scale": 116},
    "comic":   {"border_style": 1, "outline": 8, "shadow": 6, "back": "&HFF000000", "scale": 120},
}

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Pop,{font},{size},{primary},{primary},&H00000000,{back},-1,0,0,0,100,100,0,0,\
{border_style},{outline},{shadow},2,{margin_l},{margin_r},{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_color(rrggbb):
    value = rrggbb.lstrip("#")
    return f"&H00{value[4:6]}{value[2:4]}{value[0:2]}"


def _timestamp(seconds):
    seconds = max(0.0, seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{int(hours):d}:{int(minutes):02d}:{secs:05.2f}"


def _escape(text):
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def _group(words, cfg):
    """Chunk words into tight 2-3 word pop phrases (max 18 chars) so captions are never long or goofy."""
    groups, current = [], []
    max_w = min(3, int(cfg.get("words_per_group", 3)))
    for index, word in enumerate(words):
        w_text = word["w"].strip()
        if not w_text:
            continue
        cur_chars = sum(len(x["w"]) for x in current) + len(current)
        if current and (cur_chars + len(w_text) > 18 or len(current) >= max_w):
            groups.append(current)
            current = []
        current.append(word)
        gap_next = (words[index + 1]["s"] - word["e"]) if index + 1 < len(words) else 99
        if (
            len(current) >= max_w
            or w_text.endswith((".", "!", "?"))
            or (w_text.endswith(",") and len(current) >= 2)
            or gap_next > 0.45
        ):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def build(words, start, end, path, cfg, cam_h=None):
    """Write an ASS file covering [start, end); positions captions in the safe zone."""
    words = hinglish.strip_hallucinations(hinglish.romanize_word_list(words))
    style_name = (cfg.get("caption_style") or "classic").lower()
    preset = STYLE_PRESETS.get(style_name, STYLE_PRESETS["classic"])

    primary = _ass_color(cfg["text_color"])
    highlight = _ass_color(cfg["highlight_color"])

    # ClipKaro Safe-Zone Positioning:
    # - If `cam_h` is present (`stream` layout with facecam & gameplay), place captions near the seam
    #   or safe lower-middle zone (`caption_y = 0.68`) so they never cover the facecam OR bottom app UI buttons!
    # - MarginR = 135 keeps captions clear of TikTok/Reels/Shorts right-side Like/Comment/Share buttons!
    eff_y = 0.66 if cam_h else cfg.get("caption_y", 0.70)
    marginv = int(cfg["output_height"] * (1.0 - eff_y))
    margin_l = 85
    margin_r = 135

    lines = [HEADER.format(
        w=cfg["output_width"], h=cfg["output_height"],
        font=cfg["font"], size=cfg["font_size"],
        primary=primary, back=preset["back"],
        border_style=preset["border_style"],
        outline=preset["outline"], shadow=preset["shadow"],
        margin_l=margin_l, margin_r=margin_r, marginv=marginv,
    )]

    inside = [w for w in words if w["e"] > start and w["s"] < end]
    groups = _group(inside, cfg)
    sc = preset["scale"]

    for gi, group in enumerate(groups):
        texts = [_escape(w["w"].strip()) for w in group]
        if cfg["uppercase"]:
            texts = [t.upper() for t in texts]

        next_start = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end
        tail_limit = min(next_start, end)

        for index, word in enumerate(group):
            ev_start = max(word["s"], start) - start
            if index + 1 < len(group):
                ev_end = max(group[index + 1]["s"], word["e"]) - start
            elif tail_limit - word["e"] <= HOLD_THROUGH_PAUSE:
                ev_end = tail_limit - start
            else:
                ev_end = min(word["e"] + 0.3, tail_limit) - start
            if ev_end <= ev_start:
                ev_end = ev_start + 0.08

            pop = f"\\fscx{sc}\\fscy{sc}" if cfg["word_pop"] and sc > 100 else ""
            unpop = r"\fscx100\fscy100" if pop else ""

            rendered = []
            for j, text in enumerate(texts):
                if j == index:
                    rendered.append(f"{{\\c{highlight}&{pop}}}{text}{{\\c{primary}&{unpop}}}")
                else:
                    rendered.append(text)

            lines.append(
                f"Dialogue: 0,{_timestamp(ev_start)},{_timestamp(ev_end)},Pop,,0,0,0,,"
                + " ".join(rendered)
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
