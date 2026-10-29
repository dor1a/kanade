"""In-memory track index for autocomplete.

Plex search puts an artist-name match in its artist hub and returns only a few of
that artist's tracks in the track hub, so autocomplete matches here instead.
"""

import random
import unicodedata
from dataclasses import dataclass

from .plex import Track


def _fold(text: str) -> str:
    # NFKC folds full-width forms, casefold handles case in every script.
    return unicodedata.normalize("NFKC", text).casefold()


@dataclass(frozen=True)
class _Entry:
    title: str
    text: str
    track: Track


class TrackIndex:
    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._by_key: dict[str, Track] = {}
        self._artists: list[tuple[str, str]] = []
        self._by_artist: dict[str, list[Track]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def replace(self, tracks: list[Track]) -> None:
        ordered = sorted(tracks, key=lambda t: (_fold(t.album_artist), _fold(t.album), t.disc, t.number))
        names: dict[str, str] = {}
        by_artist: dict[str, list[Track]] = {}
        for t in ordered:
            # A track belongs to its track artist and its album artist.
            for key, name in {_fold(n): n for n in (t.album_artist, t.artist) if n}.items():
                names.setdefault(key, name)
                by_artist.setdefault(key, []).append(t)
        self._entries = [
            _Entry(_fold(t.title), _fold(" ".join((t.title, t.artist, t.album_artist, t.album))), t)
            for t in ordered
        ]
        self._by_key = {t.rating_key: t for t in ordered}
        self._artists = sorted(names.items())
        self._by_artist = by_artist

    def get(self, rating_key: str) -> Track | None:
        return self._by_key.get(rating_key)

    def search(self, query: str, limit: int) -> list[Track]:
        """Tracks whose title, artists, and album together contain every word of the query."""
        words = _fold(query).split()
        if not words:
            return []
        hits = [e for e in self._entries if all(w in e.text for w in words)]
        # Title matches first; the stable sort keeps album order within each group.
        hits.sort(key=lambda e: not all(w in e.title for w in words))
        return [e.track for e in hits[:limit]]

    def artists(self, query: str, limit: int) -> list[str]:
        """Artist names containing every word of the query, or the first ones when it is empty."""
        words = _fold(query).split()
        return [name for key, name in self._artists if all(w in key for w in words)][:limit]

    def tracks_by(self, artist: str) -> list[Track]:
        """The artist's tracks in album order."""
        return list(self._by_artist.get(_fold(artist), []))

    def _pool(self, artist: str | None) -> list[Track]:
        return self._by_artist.get(_fold(artist), []) if artist else [e.track for e in self._entries]

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
