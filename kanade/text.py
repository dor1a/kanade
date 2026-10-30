"""Text folding shared by the index, the readings, and MusicBrainz lookups."""

import unicodedata

INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
# Compound vowels and finals split into their parts, so a syllable that is still
# being typed (오 on the way to 와, 달 on the way to 닭) already matches.
_VOWELS = ["ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅗㅏ", "ㅗㅐ", "ㅗㅣ", "ㅛ", "ㅜ",
           "ㅜㅓ", "ㅜㅔ", "ㅜㅣ", "ㅠ", "ㅡ", "ㅡㅣ", "ㅣ"]
_FINALS = ["", "ㄱ", "ㄲ", "ㄱㅅ", "ㄴ", "ㄴㅈ", "ㄴㅎ", "ㄷ", "ㄹ", "ㄹㄱ", "ㄹㅁ", "ㄹㅂ", "ㄹㅅ", "ㄹㅌ",
           "ㄹㅍ", "ㄹㅎ", "ㅁ", "ㅂ", "ㅂㅅ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]
_COMPAT = {"ㅘ": "ㅗㅏ", "ㅙ": "ㅗㅐ", "ㅚ": "ㅗㅣ", "ㅝ": "ㅜㅓ", "ㅞ": "ㅜㅔ", "ㅟ": "ㅜㅣ", "ㅢ": "ㅡㅣ",
           "ㄳ": "ㄱㅅ", "ㄵ": "ㄴㅈ", "ㄶ": "ㄴㅎ", "ㄺ": "ㄹㄱ", "ㄻ": "ㄹㅁ", "ㄼ": "ㄹㅂ", "ㄽ": "ㄹㅅ",
           "ㄾ": "ㄹㅌ", "ㄿ": "ㄹㅍ", "ㅀ": "ㄹㅎ", "ㅄ": "ㅂㅅ"}
SYLLABLE_FIRST, SYLLABLE_LAST = 0xAC00, 0xD7A3
# NFKC turns compatibility jamo (what a keyboard types, ㅇ) into conjoining jamo
# (U+110B), which would no longer match the index, so map them back.
_TO_COMPAT = str.maketrans(
    {chr(0x1100 + i): c for i, c in enumerate(INITIALS)}
    | {chr(0x1161 + i): c for i, c in enumerate("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")}
    | {chr(0x11A8 + i): c for i, c in enumerate("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")}
)


def fold(text: str) -> str:
    # NFKC folds full-width forms and composes Hangul, casefold handles case in every script.
    return unicodedata.normalize("NFKC", text).casefold().translate(_TO_COMPAT)


def is_hangul(ch: str) -> bool:
    return SYLLABLE_FIRST <= ord(ch) <= SYLLABLE_LAST


def jamo(text: str) -> str:
    """Hangul syllables spelled out as jamo; everything else is left as it is."""
    out = []
    for ch in text:
        if is_hangul(ch):
            code = ord(ch) - SYLLABLE_FIRST
            out.append(INITIALS[code // 588] + _VOWELS[code % 588 // 28] + _FINALS[code % 28])
        else:
            out.append(_COMPAT.get(ch, ch))
    return "".join(out)


def initials(text: str) -> str:
    """The initial consonants of the Hangul syllables, run together, for searches like ㅇㅇㅇ."""
    return "".join(INITIALS[(ord(ch) - SYLLABLE_FIRST) // 588] for ch in text if is_hangul(ch))


def is_initials_query(text: str) -> bool:
    bare = text.replace(" ", "")
    return bool(bare) and all(ch in INITIALS for ch in bare)
