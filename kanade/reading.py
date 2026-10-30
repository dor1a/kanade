"""Korean readings of Japanese and Chinese names, so that Korean typing finds them.

Janome gives the kana reading of Japanese text and a kana table turns it into
Hangul. People spell Japanese in Hangul in more than one way (켄시 or 겐시, 츠 or
쓰, 토우쿄우 or 토쿄), so each name gets a few variants. Kanji Janome cannot read,
and text written only in Han characters, also get the Korean reading of the
characters from hanja (周杰倫 → 주걸륜).
"""

import functools
import itertools
import logging
import re
import threading
import tomllib
from collections.abc import Callable

import hanja

from .text import fold, is_hangul

log = logging.getLogger(__name__)

HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
KANA = re.compile(r"[ぁ-ゖァ-ヺー]")

# The common Hangul spelling of each mora.
_ROWS = {
    "アイウエオ": "아이우에오", "カキクケコ": "카키쿠케코", "ガギグゲゴ": "가기구게고",
    "サシスセソ": "사시스세소", "ザジズゼゾ": "자지즈제조", "タチツテト": "타치츠테토",
    "ダヂヅデド": "다지즈데도", "ナニヌネノ": "나니누네노", "ハヒフヘホ": "하히후헤호",
    "バビブベボ": "바비부베보", "パピプペポ": "파피푸페포", "マミムメモ": "마미무메모",
    "ヤユヨ": "야유요", "ラリルレロ": "라리루레로", "ワヰヱヲ": "와이에오", "ヴ": "부",
    "ァィゥェォ": "아이우에오", "ャュョ": "야유요", "ヮ": "와",
}
_MORA = {k: v for kana, hangul in _ROWS.items() for k, v in zip(kana, hangul)}
_DIGRAPHS = {
    "キャ": "캬", "キュ": "큐", "キョ": "쿄", "ギャ": "갸", "ギュ": "규", "ギョ": "교",
    "シャ": "샤", "シュ": "슈", "ショ": "쇼", "ジャ": "자", "ジュ": "주", "ジョ": "조",
    "チャ": "차", "チュ": "추", "チョ": "초", "ヂャ": "자", "ヂュ": "주", "ヂョ": "조",
    "ニャ": "냐", "ニュ": "뉴", "ニョ": "뇨", "ヒャ": "햐", "ヒュ": "휴", "ヒョ": "효",
    "ビャ": "뱌", "ビュ": "뷰", "ビョ": "뵤", "ピャ": "퍄", "ピュ": "퓨", "ピョ": "표",
    "ミャ": "먀", "ミュ": "뮤", "ミョ": "묘", "リャ": "랴", "リュ": "류", "リョ": "료",
    "ファ": "파", "フィ": "피", "フェ": "페", "フォ": "포", "フュ": "퓨",
    "ティ": "티", "ディ": "디", "トゥ": "투", "ドゥ": "두", "テュ": "튜", "デュ": "듀",
    "ウィ": "위", "ウェ": "웨", "ウォ": "워", "イェ": "예", "シェ": "셰", "ジェ": "제", "チェ": "체",
    "ヴァ": "바", "ヴィ": "비", "ヴェ": "베", "ヴォ": "보",
    "ツァ": "차", "ツィ": "치", "ツェ": "체", "ツォ": "초", "クァ": "콰", "グァ": "과",
}
# The official romanization writes word-initial ㅋ, ㅌ, ㅊ as ㄱ, ㄷ, ㅈ (겐시, 도쿄)
# and ツ as 쓰 everywhere.
_INITIAL_SHIFT = {15: 0, 16: 3, 14: 12}
_O_VOWELS, _U_VOWELS = {8, 12}, {13, 17}
_FINAL_N, _FINAL_S = 4, 19


def _katakana(text: str) -> str:
    return "".join(chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in text)


def _morae(kata: str) -> list[tuple[str, str]]:
    """Split katakana into (kana, hangul) units; ッ, ン, and ー come back as markers."""
    out = []
    i = 0
    while i < len(kata):
        pair = kata[i : i + 2]
        if pair in _DIGRAPHS:
            out.append((pair, _DIGRAPHS[pair]))
            i += 2
            continue
        ch = kata[i]
        if ch in "ッンー":
            out.append((ch, ""))
        elif ch in _MORA:
            out.append((ch, _MORA[ch]))
        else:
            out.append((ch, ch))
        i += 1
    return out


def _parts(syllable: str) -> tuple[int, int, int]:
    code = ord(syllable) - 0xAC00
    return code // 588, code % 588 // 28, code % 28


def _compose(lead: int, vowel: int, tail: int) -> str:
    return chr(0xAC00 + lead * 588 + vowel * 28 + tail)


def _render(morae: list[tuple[str, str]], official: bool, shorten: bool) -> str:
    out: list[str] = []
    for i, (kana, hangul) in enumerate(morae):
        last = out[-1] if out and len(out[-1]) == 1 and is_hangul(out[-1]) else None
        if kana in "ッン":
            if last and _parts(last)[2] == 0:
                lead, vowel, _ = _parts(last)
                out[-1] = _compose(lead, vowel, _FINAL_S if kana == "ッ" else _FINAL_N)
            continue
        if kana == "ー":
            continue
        if shorten and last and kana in "ウオ":
            vowel = _parts(last)[1]
            if vowel in _O_VOWELS or (kana == "ウ" and vowel in _U_VOWELS):
                continue
        if official and kana == "ツ":
            hangul = "쓰"
        if official and i == 0 and len(hangul) == 1 and is_hangul(hangul):
            lead, vowel, tail = _parts(hangul)
            hangul = _compose(_INITIAL_SHIFT.get(lead, lead), vowel, tail)
        out.append(hangul)
    return "".join(out)


def kana_to_hangul(kana: str) -> list[str]:
    """Hangul spellings of a kana word: common and official, with and without long vowels."""
    morae = _morae(_katakana(kana))
    return list(dict.fromkeys(_render(morae, o, s) for o, s in itertools.product((False, True), repeat=2)))


_tokenizer = None
_tokenizer_lock = threading.Lock()


def _tokens(text: str) -> list[tuple[str, str]]:
    """(surface, katakana reading or '') for each Janome token. Janome loads lazily: 1.5 s, about 70 MB."""
    global _tokenizer
    with _tokenizer_lock:
        if _tokenizer is None:
            from janome.tokenizer import Tokenizer

            _tokenizer = Tokenizer()
        tokens = list(_tokenizer.tokenize(text))
    out = []
    for t in tokens:
        reading = t.reading if t.reading and t.reading != "*" else ""
        out.append((t.surface, _katakana(reading) if reading and not HAN.search(reading) else ""))
    return out


@functools.lru_cache(maxsize=None)
def korean_readings(text: str) -> tuple[str, ...]:
    """Hangul readings of Japanese or Chinese text; empty for Hangul and Latin text."""
    if not (KANA.search(text) or HAN.search(text)):
        return ()
    # Each token is spelled on its own so that word-initial rules apply per word,
    # and every variant applies the same rules to all tokens.
    pieces: list[list[tuple[str, str]] | str] = []
    for surface, reading in _tokens(text):
        if reading:
            pieces.append(_morae(reading))
        elif HAN.search(surface):
            pieces.append(hanja.translate(surface, "substitution"))
        else:
            pieces.append(surface)
    readings = {
        "".join(p if isinstance(p, str) else _render(p, official, shorten) for p in pieces)
        for official, shorten in itertools.product((False, True), repeat=2)
    }
    if not KANA.search(text):
        # Han-only text may be Chinese or Japanese, so keep the Korean reading too.
        readings.add(hanja.translate(text, "substitution"))
    readings.discard(text)
    return tuple(sorted(readings))


class Readings:
    """Extra search words for a name: hand-kept aliases, MusicBrainz aliases, and generated readings."""

    def __init__(self, aliases_path: str, artist_aliases: Callable[[str], list[str]] | None = None):
        self._path = aliases_path
        self._artist_aliases = artist_aliases
        self._aliases: dict[str, list[str]] = {}

    def load_aliases(self) -> None:
        """Reread the alias file; a missing file means no aliases, a broken one keeps the last good copy."""
        try:
            with open(self._path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            self._aliases = {}
            return
        except (OSError, tomllib.TOMLDecodeError) as e:
            log.error("could not read %s (%s); keeping the previous aliases", self._path, e)
            return
        aliases: dict[str, list[str]] = {}
        for name, words in data.items():
            words = [words] if isinstance(words, str) else words
            if isinstance(words, list):
                aliases[fold(name)] = [str(w) for w in words]
        self._aliases = aliases
        log.info("loaded %d aliases from %s", len(aliases), self._path)

    def extra(self, text: str) -> list[str]:
        if not text:
            return []
        words = list(self._aliases.get(fold(text), ()))
        if self._artist_aliases:
            words += self._artist_aliases(text)
        words += korean_readings(text)
        return words
