"""Render the Hook Banner pinned on the facecam/gameplay seam (or top of clip).

Supports two styles (`--hook-style`):
1. `gta6_seam` (Default — matches FING Plays reference Shorts `hwyOH_kqBX8` & `YD4xQw0QtHk`):
   - Vibrant GTA 6 sunset-gradient banner (`#FF6B4A` coral-orange -> `#E93E8F` neon pink -> `#8A3FFC` purple)
     that sits directly on the horizontal seam between the streamer's facecam and gameplay.
   - Bold white text with a dark drop-shadow/stroke so it pops cleanly without blocking the gameplay.
2. `classic_white`:
   - Rounded white pill box with bold black text.

Works across Windows, Linux, and macOS by automatically discovering installed bold and emoji fonts.
"""

from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

EMOJI_FONT_CANDIDATES = (
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "C:/Windows/Fonts/seguiemj.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
)

TEXT_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/calibrib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)

_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),   # pictographs, emoticons, symbols
    (0x2600, 0x27BF),     # misc symbols and dingbats
    (0x1F000, 0x1F2FF),   # tiles, enclosed characters
    (0xFE00, 0xFE0F),     # variation selectors
    (0x2B00, 0x2BFF),
)


def _is_emoji(ch):
    point = ord(ch)
    return any(lo <= point <= hi for lo, hi in _EMOJI_RANGES)


def _runs(word):
    """Split a word into consecutive (is_emoji, text) runs."""
    out = []
    for ch in word:
        kind = _is_emoji(ch)
        if out and out[-1][0] == kind:
            out[-1][1] += ch
        else:
            out.append([kind, ch])
    return [(kind, text) for kind, text in out]


def _load_text_font(preferred, size):
    for candidate in (preferred, *TEXT_FONT_CANDIDATES):
        if candidate and Path(candidate).exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _emoji_image(ch, size):
    """Render one emoji glyph using the first available system emoji font, or return None."""
    for path in EMOJI_FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        for strike in (160, 109, size, 64):
            try:
                font = ImageFont.truetype(path, strike)
                tile = Image.new("RGBA", (strike + 40, strike + 40), (0, 0, 0, 0))
                ImageDraw.Draw(tile).text((0, 0), ch, font=font, embedded_color=True)
                bbox = tile.getbbox()
                if bbox:
                    return tile.crop(bbox).resize((size, size), Image.LANCZOS)
            except (OSError, ValueError):
                continue
    return None


def _measure(word, font, em, has_emoji_font):
    width = 0.0
    for is_emoji, text in _runs(word):
        if is_emoji:
            if has_emoji_font:
                width += len(text) * em
        else:
            width += font.getlength(text)
    return width


def clean_hook_phrase(text):
    """Keep the Hook Bar crisp (2 to 7 words max, like 'Flying our first plane in GTA 6' or 'Holy sh#t')."""
    if not text:
        return "Watch this moment"
    emojis = [ch for ch in text if _is_emoji(ch)]
    if ":" in text:
        left, _, right = text.partition(":")
        left_clean = left.strip(" \"'‘’“”")
        if len(left_clean.split()) >= 2:
            text = left_clean + (" " + emojis[0] if emojis else "")
    for q in ('"', "'", "‘", "’", "“", "”"):
        text = text.replace(q, "")
    words = text.split()
    non_emoji = [w for w in words if not any(_is_emoji(ch) for ch in w)]
    if len(non_emoji) > 7:
        kept = non_emoji[:7]
        if emojis:
            kept.append(emojis[0])
        text = " ".join(kept)
    return text.strip()


def _make_gta6_gradient_banner(box_w, box_h, radius):
    """Create the FING Plays GTA 6 Sunset Gradient pill/banner:
    Horizontal gradient from warm Vice City Sunset Orange (#FF6B4A) -> Neon Pink (#E93E8F) -> Purple (#8A3FFC).
    """
    x = np.linspace(0.0, 1.0, box_w, dtype=np.float32)
    # Two-segment interpolation: 0.0 -> 0.55 (Orange to Pink), 0.55 -> 1.0 (Pink to Purple)
    c0 = np.array([255, 107, 74], dtype=np.float32)    # #FF6B4A
    c1 = np.array([233, 62, 143], dtype=np.float32)    # #E93E8F
    c2 = np.array([138, 63, 252], dtype=np.float32)    # #8A3FFC

    rgb = np.zeros((box_h, box_w, 4), dtype=np.uint8)
    for i, t in enumerate(x):
        if t <= 0.55:
            u = t / 0.55
            col = (1.0 - u) * c0 + u * c1
        else:
            u = (t - 0.55) / 0.45
            col = (1.0 - u) * c1 + u * c2
        rgb[:, i, 0] = int(col[0])
        rgb[:, i, 1] = int(col[1])
        rgb[:, i, 2] = int(col[2])
        rgb[:, i, 3] = 242

    grad_img = Image.fromarray(rgb, mode="RGBA")
    mask = Image.new("L", (box_w, box_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=radius, fill=255)
    out = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    out.paste(grad_img, (0, 0), mask)
    return out


def render(text, cfg, path):
    """Draw the Hook Banner to `path`. Returns (path, width, height)."""
    text = clean_hook_phrase(text)
    style = (cfg.get("hook_style") or "gta6_seam").lower()
    size = cfg["hook_font_size"]
    font = _load_text_font(cfg.get("hook_font_file"), size)
    has_emoji_font = any(Path(p).exists() for p in EMOJI_FONT_CANDIDATES)
    em = int(size * 1.05)
    pad_x, pad_y = int(size * 0.65), int(size * 0.30)
    line_h = int(size * 1.26)
    space = font.getlength(" ")
    max_text = cfg["output_width"] - 2 * cfg["hook_margin_x"] - 2 * pad_x

    cleaned_words = []
    for w in text.split():
        if not has_emoji_font:
            w = "".join(ch for ch in w if not _is_emoji(ch))
        if w.strip():
            cleaned_words.append(w.strip())
    if not cleaned_words:
        cleaned_words = ["Watch", "this"]

    lines, current = [], []
    for word in cleaned_words:
        trial = current + [word]
        width = sum(_measure(w, font, em, has_emoji_font) for w in trial) + space * (len(trial) - 1)
        if current and width > max_text:
            lines.append(current)
            current = [word]
        else:
            current = trial
    if current:
        lines.append(current)

    widths = [
        sum(_measure(w, font, em, has_emoji_font) for w in ln) + space * (len(ln) - 1)
        for ln in lines
    ]
    if style == "gta6_seam":
        # Full-seam or wide sleek gradient banner (like FING Plays Shorts hwyOH_kqBX8 & YD4xQw0QtHk)
        box_w = max(int(cfg["output_width"] * 0.92), min(cfg["output_width"], int(max(widths) + 2 * pad_x + 40)))
        box_h = max(76, int(len(lines) * line_h + 2 * pad_y))
        radius = int(size * 0.22)
        img = _make_gta6_gradient_banner(box_w, box_h, radius)
        draw = ImageDraw.Draw(img)
        text_fill = (255, 255, 255, 255)
        shadow_fill = (20, 10, 35, 220)
    else:
        box_w = max(200, int(max(widths) + 2 * pad_x))
        box_h = max(80, int(len(lines) * line_h + 2 * pad_y))
        img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            (0, 0, box_w - 1, box_h - 1),
            radius=int(size * 0.30),
            fill=(255, 255, 255, 255),
        )
        text_fill = (0, 0, 0, 255)
        shadow_fill = None

    for row, (line, width) in enumerate(zip(lines, widths)):
        x = (box_w - width) / 2
        y = pad_y + row * line_h
        for word in line:
            for is_emoji, chunk in _runs(word):
                if is_emoji:
                    if not has_emoji_font:
                        continue
                    for ch in chunk:
                        glyph = _emoji_image(ch, em)
                        if glyph is not None:
                            img.alpha_composite(
                                glyph, (int(x), int(y + (line_h - em) / 2))
                            )
                            x += em
                else:
                    if shadow_fill is not None:
                        for dx, dy in ((-2, 2), (2, 2), (0, 3), (-2, -1), (2, -1)):
                            draw.text((x + dx, y + dy), chunk, font=font, fill=shadow_fill)
                    draw.text((x, y), chunk, font=font, fill=text_fill)
                    x += font.getlength(chunk)
            x += space

    img.save(path)
    return path, box_w, box_h
