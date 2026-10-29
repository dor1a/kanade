"""Discord bot and slash commands."""

import asyncio
import logging

import discord
from discord import app_commands

from .config import Config
from .index import TrackIndex
from .player import GuildPlayer
from .plex import PlexClient, Track

log = logging.getLogger(__name__)

AUTOCOMPLETE_TIMEOUT = 2.5  # Discord drops autocomplete answers after 3 seconds.
CHOICE_LIMIT = 25
NAME_LIMIT = 100
INDEX_REFRESH_SECONDS = 30 * 60  # New tracks in Plex show up in search after at most this long.


class Kanade(discord.Client):
    def __init__(self, config: Config):
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.plex = PlexClient(config.plex_url, config.plex_token, config.plex_section_id)
        self.index = TrackIndex()
        self.tree = app_commands.CommandTree(self)
        self.players: dict[int, GuildPlayer] = {}
        self._refresh_task: asyncio.Task | None = None
        self._register_commands()

    async def setup_hook(self) -> None:
        await self.plex.start()
        await self.refresh_index()
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        guild = discord.Object(id=self.config.guild_id)
        # Guild commands show up at once; global ones can take a while.
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)

    async def close(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
        for player in self.players.values():
            await player.stop()
        await self.plex.close()
        await super().close()

    async def refresh_index(self) -> None:
        # A failed refresh keeps the previous index; an empty one falls back to Plex search.
        try:
            tracks = await self.plex.all_tracks()
        except Exception:
            log.exception("could not load the track list from Plex")
            return
        self.index.replace(tracks)
        log.info("indexed %d tracks", len(self.index))

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(INDEX_REFRESH_SECONDS)
            await self.refresh_index()

    async def find_tracks(self, query: str, limit: int, timeout: float = 10) -> list[Track]:
        if self.index:
            return self.index.search(query, limit)
        return await self.plex.search_tracks(query, limit=limit, timeout=timeout)

    def player_for(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = GuildPlayer(self.plex, self.config.bitrate_kbps, asyncio.get_running_loop())
        return self.players[guild_id]

    def _register_commands(self) -> None:
        tree = self.tree

        @tree.command(description="Plex에서 곡을 찾아 재생하거나 대기열에 넣는다")
        @app_commands.describe(query="곡 제목이나 아티스트")
        async def play(interaction: discord.Interaction, query: str) -> None:
            member = interaction.user
            if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
                await interaction.response.send_message("먼저 음성 채널에 들어가 주세요.", ephemeral=True)
                return
            await interaction.response.defer()
            # Autocomplete sends the rating key; typed text falls back to the first search hit.
            track = self.index.get(query)
            if track is None and query.isdigit() and not self.index:
                try:
                    track = await self.plex.track(query)
                except Exception:
                    log.debug("rating key lookup failed for %s", query, exc_info=True)
            if track is None:
                hits = await self.find_tracks(query, 1)
                track = hits[0] if hits else None
            if track is None:
                await interaction.followup.send(f"찾지 못했어요: {query}")
                return
            player = self.player_for(interaction.guild_id)
            await player.connect(member.voice.channel)
            started = await player.enqueue(track)
            await interaction.followup.send(("재생: " if started else "대기열에 추가: ") + track.label)

        @play.autocomplete("query")
        async def play_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
            if not current.strip():
                return []
            try:
                tracks = await self.find_tracks(current, CHOICE_LIMIT, timeout=AUTOCOMPLETE_TIMEOUT)
            except Exception:
                log.debug("autocomplete search failed", exc_info=True)
                return []
            return [
                app_commands.Choice(name=t.label[:NAME_LIMIT], value=t.rating_key) for t in tracks if t.rating_key
            ]

        @tree.command(description="지금 곡을 건너뛴다")
        async def skip(interaction: discord.Interaction) -> None:
            player = self.players.get(interaction.guild_id)
            if not player or player.current is None:
                await interaction.response.send_message("재생 중인 곡이 없어요.", ephemeral=True)
                return
            player.skip()
            await interaction.response.send_message(f"건너뜀: {player.current.label}")

        @tree.command(description="재생을 멈추고 음성 채널에서 나간다")
        async def stop(interaction: discord.Interaction) -> None:
            player = self.players.pop(interaction.guild_id, None)
            if player:
                await player.stop()
            await interaction.response.send_message("멈췄어요.")

        @tree.command(description="지금 곡과 대기열을 보여 준다")
        async def queue(interaction: discord.Interaction) -> None:
            player = self.players.get(interaction.guild_id)
            if not player or player.current is None:
                await interaction.response.send_message("대기열이 비어 있어요.", ephemeral=True)
                return
            lines = [f"지금: {player.current.label}"]
            lines += [f"{i}. {t.label}" for i, t in enumerate(list(player.queue)[:10], start=1)]
            if len(player.queue) > 10:
                lines.append(f"외 {len(player.queue) - 10}곡")
            await interaction.response.send_message("\n".join(lines))
