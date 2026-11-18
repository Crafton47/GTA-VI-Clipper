import json
"""Hinglish (Romanized Hindi) converter and script detector.

Ensures Hindi/Desi streams (e.g. CarryisLive, Mortal, Samay Raina, Scout, Triggered Insaan)
ALWAYS render subtitles in clean Romanized Hinglish (Latin alphabet: "LADY KO DEKHNE JAATA HOON",
"ABEY KYA HAI!") — NEVER in Urdu/Arabic script and NEVER in unreadable Devanagari boxes.
"""

import re

# Common high-frequency Hindi/Hinglish words for natural spelling
WORD_OVERRIDES = {
    "में": "mein", "मैं": "main", "हूँ": "hoon", "हूं": "hoon", "है": "hai", "हैं": "hain",
    "था": "tha", "थी": "thi", "थे": "the", "का": "ka", "की": "ki", "के": "ke", "को": "ko",
    "से": "se", "पर": "par", "पे": "pe", "ने": "ne", "तो": "toh", "भी": "bhi", "ही": "hi",
    "ना": "na", "नहीं": "nahi", "क्या": "kya", "क्यों": "kyun", "कैसे": "kaise", "कहाँ": "kahan",
    "अबे": "abey", "अरे": "arey", "भाई": "bhai", "यार": "yaar", "ब्रो": "bro", "गया": "gaya",
    "गई": "gayi", "गए": "gaye", "रहा": "raha", "रही": "rahi", "रहे": "rahe", "कर": "kar",
    "करो": "karo", "करता": "karta", "करती": "karti", "कहती": "kehti", "कहता": "kehta",
    "बोला": "bola", "बोली": "boli", "देखा": "dekha", "देखने": "dekhne", "देखो": "dekho",
    "जाता": "jaata", "जाती": "jaati", "आता": "aata", "हो": "ho", "होता": "hota", "जाता": "jaata",
    "गुस्सा": "gussa", "गुस्से": "gusse", "शांत": "shaant", "एक": "1", "दो": "2", "तीन": "3",
    "चार": "4", "पांच": "5", "पाँच": "5", "छह": "6", "सात": "7", "आठ": "8", "नौ": "9", "दस": "10",
    "लेके": "leke", "तक": "tak", "गिना": "gina", "गिर": "gir", "तुझे": "tujhe", "मुझे": "mujhe",
    "उसने": "usne", "ऐसे": "aise", "वो": "woh", "ये": "yeh", "वह": "woh", "यह": "yeh",
    "लेडी": "lady", "सॉरी": "sorry", "बहन": "behen", "माँ": "maa", "कसम": "kasam",
}

VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "अं": "an", "अः": "ah",
}

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h",
    "क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
    "क्ष": "ksh", "त्र": "tr", "ज्ञ": "gy",
}

MATRAS = {
    "ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
    "ं": "n", "ँ": "n", "ः": "h", "्": "", "़": "",
}

DEVANAGARI_DIGITS = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

# Urdu / Perso-Arabic character phonetic fallback map (in case cached captions contain Urdu script)
URDU_MAP = {
    "ا": "a", "آ": "aa", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s",
    "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d", "ڈ": "d", "ذ": "z",
    "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh", "س": "s", "ش": "sh", "ص": "s",
    "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q",
    "ک": "k", "ك": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "ں": "n",
    "و": "o", "ہ": "h", "ھ": "h", "ه": "h", "ء": "", "ی": "i", "ي": "i",
    "ے": "e", "ئ": "y", "ؤ": "o", "ۃ": "h", "ة": "h",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
}


def has_arabic_or_urdu(text):
    """Return True if `text` contains any Arabic/Urdu Unicode characters."""
    return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]", text or ""))


def has_devanagari(text):
    """Return True if `text` contains any Devanagari (Hindi) Unicode characters."""
    return bool(re.search(r"[\u0900-\u097F]", text or ""))


def _romanize_devanagari_word(word):
    clean = word.strip(".,!?;:\"'()-")
    prefix = word[:len(word) - len(word.lstrip(".,!?;:\"'()-"))]
    suffix = word[len(word.rstrip(".,!?;:\"'()-")):]
    if clean in WORD_OVERRIDES:
        return prefix + WORD_OVERRIDES[clean] + suffix

    # Normalize nukta combinations first
    norm = (
        clean.replace("क\u093c", "क़").replace("ख\u093c", "ख़").replace("ग\u093c", "ग़")
        .replace("ज\u093c", "ज़").replace("ड\u093c", "ड़").replace("ढ\u093c", "ढ़").replace("फ\u093c", "फ़")
    )
    if norm in WORD_OVERRIDES:
        return prefix + WORD_OVERRIDES[norm] + suffix

    out = []
    n = len(norm)
    i = 0
    while i < n:
        ch = norm[i]
        if ch in DEVANAGARI_DIGITS:
            out.append(DEVANAGARI_DIGITS[ch])
            i += 1
        elif ch in VOWELS:
            out.append(VOWELS[ch])
            i += 1
        elif ch in CONSONANTS:
            base = CONSONANTS[ch]
            next_ch = norm[i + 1] if i + 1 < n else ""
            if next_ch == "्":
                out.append(base)
                i += 2
            elif next_ch in MATRAS:
                out.append(base + MATRAS[next_ch])
                i += 2
            else:
                # Add inherent schwa 'a' except at the very end of a multi-letter word
                if i < n - 1:
                    out.append(base + "a")
                else:
                    out.append(base)
                i += 1
        elif ch in MATRAS:
            out.append(MATRAS[ch])
            i += 1
        else:
            out.append(ch)
            i += 1
    res = "".join(out)
    return prefix + (res or clean) + suffix


def _romanize_urdu_word(word):
    out = []
    for ch in word:
        if ch in URDU_MAP:
            out.append(URDU_MAP[ch])
        elif "\u0600" <= ch <= "\u06FF":
            continue
        else:
            out.append(ch)
    return "".join(out)


def to_hinglish(text):
    """Convert any Devanagari (Hindi) or Urdu/Arabic tokens in `text` into clean Roman Hinglish."""
    if not text:
        return text
    if not has_devanagari(text) and not has_arabic_or_urdu(text):
        return text
    tokens = text.split()
    converted = []
    for tok in tokens:
        if has_devanagari(tok):
            converted.append(_romanize_devanagari_word(tok))
        elif has_arabic_or_urdu(tok):
            converted.append(_romanize_urdu_word(tok))
        else:
            converted.append(tok)
    return " ".join(w for w in converted if w.strip())


def romanize_word_list(words):
    """Ensure every word dict `{"s", "e", "w"}` in `words` is in Romanized Hinglish / Latin script."""
    out = []
    for w in words:
        rom = to_hinglish(w.get("w", "")).strip()
        if rom:
            out.append({"s": w["s"], "e": w["e"], "w": rom})
    return out


# Whisper common hallucinations during game music, laughter, or silence (ClipKaro filter)
WHISPER_HALLUCINATIONS = {
    "thank you for watching", "thanks for watching", "subtitles by", "amara.org",
    "please subscribe", "like and subscribe", "translated by", "captions by",
    "mbc", "sbs", "♪", "♫", "[music]", "(music)",
}


def strip_hallucinations(words):
    """Remove fake words Whisper invents during laughs, screams, or background game music."""
    if not words:
        return words
    joined = " ".join(w.get("w", "").lower() for w in words)
    for bad in WHISPER_HALLUCINATIONS:
        if bad in joined and len(words) <= 6:
            return []
    out = []
    for w in words:
        tok = w.get("w", "").strip()
        if not tok or tok.lower() in {"♪", "♫", "[music]", "(music)", "..."}:
            continue
        # Drop single-word stretched hallucinations (>3.5s for 1 word)
        if (w["e"] - w["s"]) > 3.8 and len(tok) < 12:
            w = dict(w, e=round(w["s"] + 0.9, 2))
        out.append(w)
    return out


def ai_polish_captions(words, stream, cfg):
    """ClipKaro v2.3 Caption Proofreader & Natural Hinglish Romanizer:
    1. Deterministically converts any Devanagari/Urdu script to Roman Hinglish first.
    2. Strips Whisper music/laugh hallucinations.
    3. Calls the free AI router to fix clear mishearings (e.g. '2 ABHAIN, WHAT IS THIS?' -> '2 ABEY KYA HAI!')
       and spell Hinglish the exact way Indian viewers write it online, while preserving exact word count & timestamps!
    """
    words = strip_hallucinations(romanize_word_list(words))
    if not words or len(words) < 3:
        return words

    try:
        from . import moments
        if moments.resolve_provider(cfg) == "heuristic":
            return words
        indexed = [f"{i}:{w['w']}" for i, w in enumerate(words)]
        prompt = (
            f"You are proofing word-by-word captions for a short clip by '{stream.get('name', 'Creator')}' "
            f"titled '{stream.get('title', '')}'.\n"
            "Rules:\n"
            "1. Keep the EXACT same word indices (0 to N-1) so timestamps stay 100% synced.\n"
            "2. Fix obvious speech-to-text mishearings (e.g., 'abhain' -> 'abey', 'saari' -> 'sorry', "
            "or scream hallucinations like 'what is this' on a Hindi stream -> 'kya hai!').\n"
            "3. Write all Hindi/Desi words in natural Romanized Hinglish using English letters "
            "(e.g., 'lady ko dekhne jaata hoon', 'gussa shaant', 'abey kya hai'). NEVER use Arabic, Urdu, or Devanagari script.\n"
            "Return ONLY a JSON array of strings with the exact same length as the input list.\n\n"
            f"INPUT ({len(words)} words):\n" + json.dumps([w["w"] for w in words])
        )
        raw = moments._ask(prompt, cfg)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            fixed = json.loads(m.group(0))
            if isinstance(fixed, list) and len(fixed) == len(words):
                out = []
                for w, new_tok in zip(words, fixed):
                    clean_tok = to_hinglish(str(new_tok).strip()) or w["w"]
                    out.append({"s": w["s"], "e": w["e"], "w": clean_tok})
                return out
    except Exception:
        pass
    return words
