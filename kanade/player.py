"""Per-guild queue and playback."""

import asyncio
import logging
from collections import deque

import discord

from .plex import PlexClient, Track

log = logging.getLogger(__name__)


class GuildPlayer:
    def __init__(self, plex: PlexClient, bitrate_kbps: int, loop: asyncio.AbstractEventLoop):
        self._plex = plex
        self._bitrate = bitrate_kbps
        self._loop = loop
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self._stream = None

    async def connect(self, channel: discord.VoiceChannel | discord.StageChannel) -> None:
        if self.voice and self.voice.is_connected():
            if self.voice.channel != channel:
                await self.voice.move_to(channel)
            return
        self.voice = await channel.connect(self_deaf=True)

    async def enqueue(self, track: Track) -> bool:
        """Queue a track; return True when it starts right away."""
        self.queue.append(track)
        if self.current is None:
            await self._play_next()
            return True
        return False

    def skip(self) -> None:
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            # stop() fires the after callback, which starts the next track.
            self.voice.stop()

    async def stop(self) -> None:
        self.queue.clear()
        self.current = None
        if self.voice:
            await self.voice.disconnect(force=False)
            self.voice = None
        self._close_stream()

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except Exception:
                log.debug("closing stream failed", exc_info=True)
            self._stream = None

    async def _play_next(self) -> None:
        self._close_stream()
        if not self.queue or not self.voice or not self.voice.is_connected():
            self.current = None
            return
        track = self.queue.popleft()
        self.current = track
        try:
            self._stream = await self._plex.open_stream(track)
        except Exception:
            log.exception("could not open %s", track.label)
            await self._play_next()
            return
        source = discord.FFmpegOpusAudio(self._stream, pipe=True, bitrate=self._bitrate)
        self.voice.play(source, after=self._after)
        log.info("playing %s", track.label)

    def _after(self, error: Exception | None) -> None:
        # Runs on the player thread; hop back to the event loop.
        if error:
            log.error("playback error: %s", error)
        asyncio.run_coroutine_threadsafe(self._play_next(), self._loop)
