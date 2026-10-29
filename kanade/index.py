"""In-memory track index for autocomplete.

Plex search puts an artist-name match in its artist hub and returns only a few of
that artist's tracks in the track hub, so autocomplete matches here instead.
"""

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

    def __len__(self) -> int:
        return len(self._entries)

    def replace(self, tracks: list[Track]) -> None:
        ordered = sorted(tracks, key=lambda t: (_fold(t.album_artist), _fold(t.album), t.disc, t.number))
        self._entries = [
            _Entry(_fold(t.title), _fold(" ".join((t.title, t.artist, t.album_artist, t.album))), t)
            for t in ordered
        ]
        self._by_key = {t.rating_key: t for t in ordered}

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
