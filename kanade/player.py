"""Per-guild queue and playback."""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable

import discord

from .plex import PlexClient, Track

log = logging.getLogger(__name__)

MAX_OPEN_FAILURES = 3  # Continuous play stops picking tracks while Plex keeps failing.
EMPTY_CHANNEL_GRACE = 60  # Seconds to wait for someone to come back before leaving.

PickNext = Callable[[str | None, set[str]], Track | None]
Announce = Callable[["GuildPlayer", Track], Awaitable[None]]


class GuildPlayer:
    def __init__(
        self,
        plex: PlexClient,
        bitrate_kbps: int,
        loop: asyncio.AbstractEventLoop,
        pick_next: PickNext,
        announce: Announce,
    ):
        self._plex = plex
        self._bitrate = bitrate_kbps
        self._loop = loop
        self._pick_next = pick_next
        self._announce = announce
        self._tasks: set[asyncio.Task] = set()
        self._leave_task: asyncio.Task | None = None
        # Where now-playing cards go when a track starts without a command.
        self.announce_channel: discord.abc.Messageable | None = None
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self._stream = None
        self._active = False
        self._failures = 0
        self.played: set[str] = set()
        # When the queue runs out, continuous play follows the last track's artist,
        # or draws from autoplay_artist, where None means the whole library.
        self.follow_artist = True
        self.autoplay_artist: str | None = None

    async def connect(self, channel: discord.VoiceChannel | discord.StageChannel) -> None:
        self._active = True
        if self.voice and self.voice.is_connected():
            if self.voice.channel != channel:
                await self.voice.move_to(channel)
            return
        self.voice = await channel.connect(self_deaf=True)

    def set_autoplay(self, follow_artist: bool, artist: str | None = None) -> None:
        self.follow_artist = follow_artist
        self.autoplay_artist = artist

    def autoplay_source(self) -> str | None:
        """The artist continuous play draws from after the queue; None means the whole library."""
        if not self.follow_artist:
            return self.autoplay_artist
        last = self.queue[-1] if self.queue else self.current
        return last.artist if last else None

    def known_keys(self) -> set[str]:
        keys = self.played | {t.rating_key for t in self.queue}
        if self.current:
            keys.add(self.current.rating_key)
        return keys

    async def enqueue(self, track: Track) -> bool:
        """Queue a track; return True when playback starts right away.

        The command that started it answers with the now-playing card, so no card is posted here.
        """
        self.queue.append(track)
        if self.current is None:
            await self._play_next(announce=False)
            return True
        return False

    def skip(self) -> None:
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            # stop() fires the after callback, which starts the next track.
            self.voice.stop()

    def check_listeners(self) -> None:
        """Leave a while after the last listener goes; called on every voice state change."""
        if not self._active or not self.voice or not self.voice.is_connected():
            return
        if self._has_listeners():
            if self._leave_task:
                self._leave_task.cancel()
                self._leave_task = None
        elif self._leave_task is None:
            self._leave_task = asyncio.create_task(self._leave_later())

    async def _leave_later(self) -> None:
        await asyncio.sleep(EMPTY_CHANNEL_GRACE)
        self._leave_task = None
        if self.voice and self.voice.is_connected() and not self._has_listeners():
            log.info("nobody came back to %s; leaving", self.voice.channel)
            await self.stop()

    async def stop(self) -> None:
        self._active = False
        if self._leave_task:
            self._leave_task.cancel()
            self._leave_task = None
        self.queue.clear()
        self.current = None
        self.played.clear()
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

    def _has_listeners(self) -> bool:
        me = self.voice.user.id
        for user_id in self.voice.channel.voice_states:
            if user_id == me:
                continue
            member = self.voice.guild.get_member(user_id)
            if member is None or not member.bot:
                return True
        return False

    def _autoplay(self, last: Track) -> None:
        if self._failures >= MAX_OPEN_FAILURES:
            return
        artist = last.artist if self.follow_artist else self.autoplay_artist
        track = self._pick_next(artist, self.played)
        if track is None and self.played:
            # Everything has played once; start over.
            self.played.clear()
            track = self._pick_next(artist, self.played)
        if track:
            self.queue.append(track)

    async def _play_next(self, announce: bool = True) -> None:
        self._close_stream()
        last, self.current = self.current, None
        if not self._active or not self.voice or not self.voice.is_connected():
            return
        if not self._has_listeners():
            log.info("nobody is listening in %s; leaving", self.voice.channel)
            await self.stop()
            return
        if not self.queue and last is not None:
            self._autoplay(last)
        if not self.queue:
            return
        track = self.queue.popleft()
        self.current = track
        self.played.add(track.rating_key)
        try:
            self._stream = await self._plex.open_stream(track)
        except Exception:
            log.exception("could not open %s", track.label)
            self._failures += 1
            await self._play_next(announce)
            return
        self._failures = 0
        source = discord.FFmpegOpusAudio(self._stream, pipe=True, bitrate=self._bitrate)
        self.voice.play(source, after=self._after)
        log.info("playing %s", track.label)
        if announce:
            task = asyncio.create_task(self._announce(self, track))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    def _after(self, error: Exception | None) -> None:
        # Runs on the player thread; hop back to the event loop.
        if error:
            log.error("playback error: %s", error)
        asyncio.run_coroutine_threadsafe(self._play_next(), self._loop)
