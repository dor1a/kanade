"""In-memory track index for autocomplete.

Plex search puts an artist-name match in its artist hub and returns only a few of
that artist's tracks in the track hub, so autocomplete matches here instead.

Each track is matched on its title, artists, and album plus the extra words the
caller supplies for them (Korean readings, aliases). Text is compared as jamo, so
a syllable that is still being typed already matches; a query of initial
consonants (ㅇㄴㅈ) matches the initials of the Hangul words; and when nothing
matches exactly, rapidfuzz offers near misses for typos.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .plex import Track
from .text import fold, initials, is_initials_query, jamo

FUZZY_CUTOFF = 80
FUZZY_MIN_LENGTH = 4  # jamo; shorter queries match too much by accident

Extra = Callable[[str], list[str]]


@dataclass(frozen=True)
class _Text:
    text: str
    initials: str

    @classmethod
    def of(cls, words: list[str]) -> "_Text":
        words = [fold(w) for w in words if w]
        # Initials run together within a name but not across names, so ㅈㅇㄴ finds 좋은 날
        # without matching the end of a title and the start of an artist.
        return cls(jamo(" ".join(words)), "|".join(initials(w) for w in words))

    def has(self, mode: str, words: list[str]) -> bool:
        hay = self.initials if mode == "initials" else self.text
        return all(w in hay for w in words)


@dataclass(frozen=True)
class _Entry:
    title: _Text
    all: _Text
    track: Track


@dataclass(frozen=True)
class _Artist:
    name: str
    all: _Text


@dataclass(frozen=True)
class IndexState:
    entries: list[_Entry] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    by_key: dict[str, Track] = field(default_factory=dict)
    artists: list[_Artist] = field(default_factory=list)
    artist_texts: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    by_artist: dict[str, list[Track]] = field(default_factory=dict)


def build(tracks: list[Track], extra: Extra | None = None) -> IndexState:
    """Build the whole index; slow with readings, so callers run it off the event loop."""
    extra = extra or (lambda _: [])
    ordered = sorted(tracks, key=lambda t: (fold(t.album_artist), fold(t.album), t.disc, t.number))
    names: dict[str, str] = {}
    by_artist: dict[str, list[Track]] = {}
    entries = []
    for t in ordered:
        # A track belongs to its track artist and its album artist.
        for key, name in {fold(n): n for n in (t.album_artist, t.artist) if n}.items():
            names.setdefault(key, name)
            by_artist.setdefault(key, []).append(t)
        fields = [t.title, t.artist, t.album_artist, t.album]
        words = [w for f in dict.fromkeys(fields) for w in [f, *extra(f)]]
        entries.append(_Entry(_Text.of([t.title, *extra(t.title)]), _Text.of(words), t))
    artists = [_Artist(name, _Text.of([name, *extra(name)])) for key, name in sorted(names.items())]
    return IndexState(
        entries=entries,
        texts=[e.all.text for e in entries],
        by_key={t.rating_key: t for t in ordered},
        artists=artists,
        artist_texts=[a.all.text for a in artists],
        names=names,
        by_artist=by_artist,
    )


def _query(query: str) -> tuple[str, list[str]]:
    q = fold(query)
    if is_initials_query(q):
        return "initials", q.split()
    return "text", jamo(q).split()


def _near(words: list[str], texts: list[str], limit: int) -> list[int]:
    query = " ".join(words)
    if len(query.replace(" ", "")) < FUZZY_MIN_LENGTH:
        return []
    hits = process.extract(query, texts, scorer=fuzz.partial_ratio, score_cutoff=FUZZY_CUTOFF, limit=limit)
    return [i for _, _, i in hits]


class TrackIndex:
    def __init__(self) -> None:
        self._s = IndexState()

    def __len__(self) -> int:
        return len(self._s.entries)

    def swap(self, state: IndexState) -> None:
        # One assignment, so readers on the event loop see the old or the new index whole.
        self._s = state

    def replace(self, tracks: list[Track], extra: Extra | None = None) -> None:
        self.swap(build(tracks, extra))

    def get(self, rating_key: str) -> Track | None:
        return self._s.by_key.get(rating_key)

    def search(self, query: str, limit: int) -> list[Track]:
        """Tracks whose title, artists, album, and their extra words contain every word of the query."""
        s = self._s
        mode, words = _query(query)
        if not words:
            return []
        hits = [i for i, e in enumerate(s.entries) if e.all.has(mode, words)]
        # Title matches first; the stable sort keeps album order within each group.
        hits.sort(key=lambda i: not s.entries[i].title.has(mode, words))
        if not hits and mode == "text":
            hits = _near(words, s.texts, limit)
        return [s.entries[i].track for i in hits[:limit]]

    def artists(self, query: str, limit: int) -> list[str]:
        """Artist names matching the query the same way as tracks, or the first ones when it is empty."""
        s = self._s
        mode, words = _query(query)
        if not words:
            return [a.name for a in s.artists[:limit]]
        hits = [i for i, a in enumerate(s.artists) if a.all.has(mode, words)]
        if not hits and mode == "text":
            hits = _near(words, s.artist_texts, limit)
        return [s.artists[i].name for i in hits[:limit]]

    def artist_name(self, name: str) -> str | None:
        """The name as Plex spells it, for a name typed in any case."""
        return self._s.names.get(fold(name))

    def tracks_by(self, artist: str) -> list[Track]:
        """The artist's tracks in album order."""
        return list(self._s.by_artist.get(fold(artist), []))

    def _pool(self, artist: str | None) -> list[Track]:
        s = self._s
        return s.by_artist.get(fold(artist), []) if artist else [e.track for e in s.entries]

    def pick_next(self, artist: str | None, played: set[str]) -> Track | None:
        """A random unplayed track by the artist, or from the whole library once the artist runs out."""
        for pool in (self._pool(artist), self._pool(None)):
            fresh = [t for t in pool if t.rating_key not in played]
            if fresh:
                return random.choice(fresh)
        return None

    def random_tracks(self, count: int, artist: str | None, exclude: set[str]) -> list[Track]:
        """Random tracks, unplayed ones first; repeats only when too few are left."""
        pool = self._pool(artist)
        fresh = [t for t in pool if t.rating_key not in exclude]
        source = fresh if len(fresh) >= count else pool
        return random.sample(source, min(count, len(source)))
