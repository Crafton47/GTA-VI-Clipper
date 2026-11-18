"""Render the static hook bar — the rounded title card pinned over the top of the clip.

Works across Windows, Linux, and macOS by automatically discovering installed bold
and emoji fonts, with safe fallbacks so rendering never fails on non-Apple systems.
"""

from pathlib import Path
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


def render(text, cfg, path):
    """Draw the rounded white hook bar to `path`. Returns (path, width, height)."""
    size = cfg["hook_font_size"]
    font = _load_text_font(cfg.get("hook_font_file"), size)
    has_emoji_font = any(Path(p).exists() for p in EMOJI_FONT_CANDIDATES)
    em = int(size * 1.05)
    pad_x, pad_y = int(size * 0.55), int(size * 0.34)
    line_h = int(size * 1.30)
    space = font.getlength(" ")
    max_text = cfg["output_width"] - 2 * cfg["hook_margin_x"] - 2 * pad_x

    # Strip unsupported emojis gracefully if no emoji font exists on this OS
    cleaned_words = []
    for w in text.split():
        if not has_emoji_font:
            w = "".join(ch for ch in w if not _is_emoji(ch))
        if w.strip():
            cleaned_words.append(w.strip())
    if not cleaned_words:
        cleaned_words = ["WATCH", "THIS"]

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
    box_w = max(200, int(max(widths) + 2 * pad_x))
    box_h = max(80, int(len(lines) * line_h + 2 * pad_y))

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, box_w - 1, box_h - 1),
        radius=int(size * 0.30),
        fill=(255, 255, 255, 255),
    )

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
                    draw.text((x, y), chunk, font=font, fill=(0, 0, 0, 255))
                    x += font.getlength(chunk)
            x += space

    img.save(path)
    return path, box_w, box_h
