"""Minimal Plex Media Server client for music search and streaming."""

import asyncio
import urllib.request
from dataclasses import dataclass
from typing import BinaryIO

import aiohttp

TRACK_TYPE = "track"


@dataclass(frozen=True)
class Track:
    rating_key: str
    title: str
    artist: str
    album: str
    duration_ms: int
    part_key: str

    @property
    def label(self) -> str:
        return f"{self.title} — {self.artist}" if self.artist else self.title


def _track_from_metadata(item: dict) -> Track | None:
    media = item.get("Media") or []
    parts = media[0].get("Part") if media else None
    if not parts or not parts[0].get("key"):
        return None
    return Track(
        rating_key=str(item.get("ratingKey", "")),
        title=item.get("title", ""),
        # Track artist when set, otherwise the album artist.
        artist=item.get("originalTitle") or item.get("grandparentTitle", ""),
        album=item.get("parentTitle", ""),
        duration_ms=int(item.get("duration") or 0),
        part_key=parts[0]["key"],
    )


class PlexClient:
    def __init__(self, base_url: str, token: str, section_id: str = ""):
        self._base_url = base_url
        self._token = token
        self._section_id = section_id
        self._session: aiohttp.ClientSession | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Plex-Token": self._token,
            "Accept": "application/json",
            "X-Plex-Product": "kanade",
            "X-Plex-Client-Identifier": "kanade-discord-bot",
        }

    async def start(self) -> None:
        self._session = aiohttp.ClientSession(headers=self._headers)

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    async def _get(self, path: str, params: dict | None = None, timeout: float = 10) -> dict:
        assert self._session is not None, "PlexClient.start() was not called"
        async with self._session.get(
            f"{self._base_url}{path}", params=params, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def search_tracks(self, query: str, limit: int = 25, timeout: float = 10) -> list[Track]:
        params = {"query": query, "limit": str(limit)}
        if self._section_id:
            params["sectionId"] = self._section_id
        data = await self._get("/hubs/search", params, timeout)
        tracks: list[Track] = []
        for hub in data.get("MediaContainer", {}).get("Hub", []):
            if hub.get("type") != TRACK_TYPE:
                continue
            for item in hub.get("Metadata", []):
                track = _track_from_metadata(item)
                if track:
                    tracks.append(track)
        return tracks[:limit]

    async def track(self, rating_key: str) -> Track | None:
        data = await self._get(f"/library/metadata/{rating_key}")
        for item in data.get("MediaContainer", {}).get("Metadata", []):
            if item.get("type") == TRACK_TYPE:
                return _track_from_metadata(item)
        return None

    async def open_stream(self, track: Track) -> BinaryIO:
        """Open the original file as a blocking stream for discord.py's pipe writer thread.

        The token stays in a request header so it never reaches the ffmpeg command line.
        """
        request = urllib.request.Request(
            f"{self._base_url}{track.part_key}", headers={"X-Plex-Token": self._token}
        )
        return await asyncio.to_thread(urllib.request.urlopen, request, timeout=30)
