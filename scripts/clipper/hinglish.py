"""Hinglish (Romanized Hindi) converter, script detector, and hook verifier.

Ensures Hindi/Desi streams (e.g. CarryisLive, FING Plays, Mortal, Samay Raina, Scout, Triggered Insaan)
ALWAYS render subtitles in clean Romanized Hinglish — NEVER in Urdu/Arabic script and NEVER in
unreadable Devanagari boxes — while preserving the full natural duration of gameplay/cutscene clips!
"""

import json
import re

WORD_OVERRIDES = {
    "में": "mein", "मैं": "main", "हूँ": "hoon", "हूं": "hoon", "है": "hai", "हैं": "hain",
    "था": "tha", "थी": "thi", "थे": "the", "का": "ka", "की": "ki", "के": "ke", "को": "ko",
    "से": "se", "पर": "par", "पे": "pe", "ने": "ne", "तो": "toh", "भी": "bhi", "ही": "hi",
    "ना": "na", "नहीं": "nahi", "क्या": "kya", "क्यों": "kyun", "कैसे": "kaise", "कहाँ": "kahan",
    "अबे": "abey", "अरे": "arey", "भाई": "bhai", "यार": "yaar", "ब्रो": "bro", "गया": "gaya",
    "गई": "gayi", "गए": "gaye", "रहा": "raha", "रही": "rahi", "रहे": "rahe", "कर": "kar",
    "करो": "karo", "करता": "karta", "करती": "karti", "कहती": "kehti", "कहता": "kehta",
    "बोला": "bola", "बोली": "boli", "देखा": "dekha", "देखने": "dekhne", "देखो": "dekho",
    "जाता": "jaata", "जाती": "jaati", "आता": "aata", "हो": "ho", "होता": "hota",
    "गुस्सा": "gussa", "गुस्से": "gusse", "शांत": "shaant", "एक": "1", "दो": "2", "तीन": "3",
    "चार": "4", "पांच": "5", "पाँच": "5", "छह": "6", "सात": "7", "आठ": "8", "नौ": "9", "दस": "10",
    "लेके": "leke", "तक": "tak", "गिना": "gina", "गिर": "gir", "तुझे": "tujhe", "मुझे": "mujhe",
    "उसने": "usne", "ऐसे": "aise", "वो": "woh", "ये": "yeh", "वह": "woh", "यह": "yeh",
    "लेडी": "lady", "सॉरी": "sorry", "बहन": "behen", "माँ": "maa", "कसम": "kasam",
    "बेटा": "beta", "जल्दी": "jaldi", "बैठ": "baith", "आगे": "aage", "अंदर": "andar",
}

VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "अं": "an", "अः": "ah",
}

CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "ध", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h",
    "क़": "q", "ख़": "kh", "ग़": "gh", "ज़": "z", "ड़": "r", "ढ़": "rh", "फ़": "f",
    "क्ष": "ksh", "त्र": "tr", "ज्ञ": "gy",
}
CONSONANTS["ध"] = "dh"

MATRAS = {
    "ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
    "ं": "n", "ँ": "n", "ः": "h", "्": "", "़": "",
}

DEVANAGARI_DIGITS = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

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
    return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]", text or ""))


def has_devanagari(text):
    return bool(re.search(r"[\u0900-\u097F]", text or ""))


def _romanize_devanagari_word(word):
    clean = word.strip(".,!?;:\"'()-")
    prefix = word[:len(word) - len(word.lstrip(".,!?;:\"'()-"))]
    suffix = word[len(word.rstrip(".,!?;:\"'()-")):]
    if clean in WORD_OVERRIDES:
        return prefix + WORD_OVERRIDES[clean] + suffix

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
    out = []
    for w in words:
        rom = to_hinglish(w.get("w", "")).strip()
        if rom:
            out.append({"s": w["s"], "e": w["e"], "w": rom})
    return out


WHISPER_HALLUCINATIONS = {
    "thank you for watching", "thanks for watching", "subtitles by", "amara.org",
    "please subscribe", "like and subscribe", "translated by", "captions by",
    "mbc", "sbs", "♪", "♫", "[music]", "(music)",
}


def strip_hallucinations(words):
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
        if (w["e"] - w["s"]) > 3.8 and len(tok) < 12:
            w = dict(w, e=round(w["s"] + 0.9, 2))
        out.append(w)
    return out


def ai_polish_captions(words, stream, cfg):
    words = strip_hallucinations(romanize_word_list(words))
    if not words or len(words) < 3:
        return words

    try:
        from . import moments
        if moments.resolve_provider(cfg) == "heuristic":
            return words
        prompt = (
            f"You are proofing word-by-word captions for a short clip by '{stream.get('name', 'Creator')}' "
            f"titled '{stream.get('title', '')}'.\n"
            "Rules:\n"
            "1. Keep the EXACT same word indices (0 to N-1) so timestamps stay 100% synced.\n"
            "2. Fix obvious speech-to-text mishearings.\n"
            "3. Write all Hindi/Desi words in natural Romanized Hinglish using English letters. NEVER use Arabic, Urdu, or Devanagari script.\n"
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


HINDI_CREATOR_KEYWORDS = (
    "carryislive", "carryminati", "fing", "fing plays", "mortal", "soul", "scout", "gamerfleet",
    "triggered insaan", "live insaan", "fukra insaan", "samay raina",
    "techno gamerz", "total gaming", "ajjubhai", "mythpat", "payal gaming",
    "jonathan gaming", "snax", "regaltos", "8bit", "godlike", "maxtern",
    "purav jha", "harsh beniwal", "ashish chanchlani", "bb ki vines",
    "tanmay bhat", "beastboyshub", "rachitroo", "casetoo", "ankit panth",
)

HOUSEKEEPING_PATTERNS = (
    "kitne like", "kitne likes", "like kar do", "likes ho gaye", "subscribe kar",
    "channel ko subscribe", "superchat", "super chat", "member ban", "membership",
    "shoutout to", "thanks for the", "funded", "donation",
)


def is_hindi_stream(stream_info):
    """Auto-detect Indian/Hindi creators (including FING Plays, CarryisLive, etc.) so English in-game
    radio songs never switch Whisper to English translation."""
    blob = f"{stream_info.get('name', '')} {stream_info.get('channel', '')} {stream_info.get('uploader', '')} {stream_info.get('title', '')}".lower()
    return any(k in blob for k in HINDI_CREATOR_KEYWORDS)


def trim_housekeeping_and_dead_air(words, total_dur, min_keep=12.0):
    """Only trim trailing streamer housekeeping ('humare kitne likes ho gaye hain yaar?') at the very
    end of a clip — NEVER chop off active gameplay, cutscene dialogue, or environmental build-up!
    """
    if not words or len(words) < 4:
        return 0.0, total_dur, words

    cut_end = total_dur
    # Only check the final 8 words for explicit stream housekeeping ("kitne likes ho gaye")
    for idx in range(max(0, len(words) - 8), len(words)):
        tail_phrase = " ".join(w["w"].lower() for w in words[idx:])
        if any(pat in tail_phrase for pat in HOUSEKEEPING_PATTERNS):
            candidate_end = max(min_keep, words[idx]["s"] - 0.25)
            if candidate_end >= min_keep and candidate_end < total_dur - 1.0:
                cut_end = round(candidate_end, 2)
                words = [w for w in words if w["e"] <= cut_end + 0.1]
            break

    return 0.0, cut_end, words


def verify_hook_against_clip(moment, words, stream, cfg):
    """Ensure `moment['hook_text']` and `moment['caption']` accurately match the actual clip content,
    written in the sleek FING Plays seam-banner style (e.g. 'Flying our first plane in GTA 6' or 'Holy sh#t').
    """
    if not words or len(words) < 4:
        return moment
    actual_transcript = " ".join(w["w"] for w in words)
    hook = (moment.get("hook_text") or "").strip()

    stop = {"carry", "carryislive", "carryminati", "fing", "gta", "gta6", "gtavi", "the", "this", "that", "in", "on", "at", "vs", "is", "are", "bro", "bhai", "our", "first"}
    hook_tokens = {re.sub(r"[^a-z0-9]", "", w.lower()) for w in hook.split()} - stop - {""}
    clip_tokens = {re.sub(r"[^a-z0-9]", "", w["w"].lower()) for w in words}

    try:
        from . import moments
        if moments.resolve_provider(cfg) != "heuristic":
            prompt = (
                f"Here is the EXACT word-for-word transcript of a vertical gaming clip by '{stream.get('name', 'Creator')}' "
                f"from '{stream.get('title', '')}':\n"
                f"\"{actual_transcript}\"\n\n"
                f"Current tentative seam banner hook: \"{hook}\"\n"
                "Task: Write an accurate, high-retention 2 to 6 word `hook_text` (NO quotes, NO colons, natural Sentence case "
                "like 'Flying our first plane in GTA 6' or 'Holy sh#t' or 'GTA 6 graphics are unreal 🔥') "
                "and a 1-sentence `caption` that directly reflect what ACTUALLY happens in this clip.\n"
                "Return ONLY valid JSON: {\"hook_text\": \"...\", \"caption\": \"...\"}"
            )
            raw = moments._ask(prompt, cfg)
            raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                data = json.loads(m.group(0))
                if data.get("hook_text"):
                    moment["hook_text"] = str(data["hook_text"]).strip()
                if data.get("caption"):
                    moment["caption"] = str(data["caption"]).strip()
                return moment
    except Exception:
        pass

    if not (hook_tokens & clip_tokens):
        low = actual_transcript.lower()
        if "plane" in low or "fly" in low:
            moment["hook_text"] = "Flying our first plane in GTA 6"
        elif "holy shit" in low or "oh my god" in low or "beta hai" in low:
            moment["hook_text"] = "Holy sh#t"
        elif "tel" in low or "fuel" in low or "petrol" in low:
            moment["hook_text"] = "GTA 6 cars run out of fuel 🔥"
        elif "graphics" in low or "real" in low or "paani" in low:
            moment["hook_text"] = "GTA 6 graphics are unreal 🔥"
    return moment
