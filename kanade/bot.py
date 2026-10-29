"""Discord bot and slash commands."""

import asyncio
import io
import logging

import discord
from discord import app_commands

from .browse import BrowseView
from .config import Config
from .index import TrackIndex
from .player import GuildPlayer
from .plex import PlexClient, Track

log = logging.getLogger(__name__)

AUTOCOMPLETE_TIMEOUT = 2.5  # Discord drops autocomplete answers after 3 seconds.
CHOICE_LIMIT = 25
NAME_LIMIT = 100
LIST_LIMIT = 10
INDEX_REFRESH_SECONDS = 30 * 60  # New tracks in Plex show up in search after at most this long.

CARD_COLOR = 0x4FA8FF  # The sky blue of the logo.

NOT_IN_VOICE = "먼저 음성 채널에 들어가 주세요."
NOT_INDEXED = "곡 목록을 아직 못 받았어요. 잠시 뒤에 다시 해 주세요."

VoiceTarget = discord.VoiceChannel | discord.StageChannel


def _voice_channel(interaction: discord.Interaction) -> VoiceTarget | None:
    member = interaction.user
    if isinstance(member, discord.Member) and member.voice and member.voice.channel:
        return member.voice.channel
    return None


def _summary(lines: list[str]) -> str:
    shown = lines[:LIST_LIMIT]
    if len(lines) > LIST_LIMIT:
        shown.append(f"외 {len(lines) - LIST_LIMIT}곡")
    return "\n".join(shown)


def _duration(ms: int) -> str:
    minutes, seconds = divmod(ms // 1000, 60)
    return f"{minutes}:{seconds:02d}"


class _Tree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        channel_id = self.client.config.channel_id
        if channel_id is None or interaction.channel_id == channel_id:
            return True
        if interaction.type is discord.InteractionType.application_command:
            await interaction.response.send_message(f"음악 명령은 <#{channel_id}>에서만 써 주세요.", ephemeral=True)
        return False


class Kanade(discord.Client):
    def __init__(self, config: Config):
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.plex = PlexClient(config.plex_url, config.plex_token, config.plex_section_id)
        self.index = TrackIndex()
        self.tree = _Tree(self)
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
            self.players[guild_id] = GuildPlayer(
                self.plex, self.config.bitrate_kbps, asyncio.get_running_loop(), self.index.pick_next, self.announce
            )
        return self.players[guild_id]

    async def card(self, player: GuildPlayer, track: Track) -> tuple[discord.Embed, discord.File | None]:
        """The now-playing card, with album art when Plex has it."""
        embed = discord.Embed(title=(track.title or "(제목 없음)")[:256], description=track.artist[:4096], color=CARD_COLOR)
        embed.set_author(name="지금 재생")
        if track.album:
            embed.add_field(name="앨범", value=track.album[:1024])
        embed.add_field(name="길이", value=_duration(track.duration_ms))
        if player.queue:
            embed.set_footer(text=f"다음: {player.queue[0].label} (대기열 {len(player.queue)}곡)"[:2048])
        else:
            embed.set_footer(text=f"그다음은 {player.autoplay_source() or '전체 곡'}에서 랜덤"[:2048])
        try:
            cover = await self.plex.cover(track)
        except Exception:
            log.debug("cover fetch failed for %s", track.label, exc_info=True)
            cover = None
        if not cover:
            return embed, None
        embed.set_thumbnail(url="attachment://cover.jpg")
        return embed, discord.File(io.BytesIO(cover), filename="cover.jpg")

    async def announce(self, player: GuildPlayer, track: Track) -> None:
        channel = player.announce_channel
        if channel is None:
            return
        embed, cover = await self.card(player, track)
        try:
            await channel.send(embed=embed, files=[cover] if cover else [])
        except discord.Forbidden:
            log.warning("cannot post in %s; the bot needs Send Messages, Embed Links, and Attach Files there", channel)
        except discord.HTTPException:
            log.exception("posting the now-playing card failed")

    async def enqueue(
        self,
        interaction: discord.Interaction,
        channel: VoiceTarget,
        tracks: list[Track],
        follow_artist: bool = True,
        artist: str | None = None,
    ) -> None:
        """Queue tracks, then answer the deferred interaction with the now-playing card if one started.

        Also sets what continuous play draws from once the queue runs out.
        """
        player = self.player_for(interaction.guild_id)
        await player.connect(channel)
        player.set_autoplay(follow_artist, artist)
        configured = self.get_channel(self.config.channel_id) if self.config.channel_id else None
        player.announce_channel = configured or interaction.channel
        idle = player.current is None
        for track in tracks:
            await player.enqueue(track)
        started = player.current if idle else None
        lines = [f"대기열에 추가: {t.label}" for t in tracks if t is not started]
        content = _summary(lines) or None
        if started is None:
            await interaction.edit_original_response(content=content or "넣을 곡이 없어요.")
            return
        embed, cover = await self.card(player, started)
        await interaction.edit_original_response(content=content, embed=embed, attachments=[cover] if cover else [])

    async def play_from_menu(self, interaction: discord.Interaction, tracks: list[Track]) -> None:
        channel = _voice_channel(interaction)
        if channel is None:
            await interaction.response.send_message(NOT_IN_VOICE, ephemeral=True)
            return
        # The menu is only visible to its user; the reply goes to the channel.
        await interaction.response.defer(thinking=True)
        await self.enqueue(interaction, channel, tracks)

    def _register_commands(self) -> None:
        tree = self.tree

        @tree.command(description="곡을 찾아 재생하거나 대기열에 넣는다")
        @app_commands.describe(query="곡 제목이나 아티스트")
        async def play(interaction: discord.Interaction, query: str) -> None:
            channel = _voice_channel(interaction)
            if channel is None:
                await interaction.response.send_message(NOT_IN_VOICE, ephemeral=True)
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
                await interaction.edit_original_response(content=f"찾지 못했어요: {query}")
                return
            await self.enqueue(interaction, channel, [track])

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

        @tree.command(name="random", description="아무 곡이나 넣고, 대기열이 끝나도 랜덤으로 계속 튼다")
        @app_commands.describe(count="처음에 넣을 곡 수", artist="이 아티스트 곡 중에서만")
        async def random_tracks(
            interaction: discord.Interaction, count: app_commands.Range[int, 1, 25] = 5, artist: str | None = None
        ) -> None:
            channel = _voice_channel(interaction)
            if channel is None:
                await interaction.response.send_message(NOT_IN_VOICE, ephemeral=True)
                return
            if not self.index:
                await interaction.response.send_message(NOT_INDEXED, ephemeral=True)
                return
            if artist and not self.index.tracks_by(artist):
                await interaction.response.send_message(f"찾지 못했어요: {artist}", ephemeral=True)
                return
            await interaction.response.defer()
            exclude = self.player_for(interaction.guild_id).known_keys()
            tracks = self.index.random_tracks(count, artist, exclude)
            await self.enqueue(interaction, channel, tracks, follow_artist=False, artist=artist)

        @tree.command(description="아티스트의 앨범과 곡을 골라 재생한다")
        @app_commands.describe(artist="아티스트")
        async def browse(interaction: discord.Interaction, artist: str) -> None:
            if not self.index:
                await interaction.response.send_message(NOT_INDEXED, ephemeral=True)
                return
            tracks = self.index.tracks_by(artist)
            if not tracks:
                await interaction.response.send_message(f"찾지 못했어요: {artist}", ephemeral=True)
                return
            view = BrowseView(interaction, artist, tracks, self.play_from_menu)
            await interaction.response.send_message(view.text(), view=view, ephemeral=True)

        async def artist_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> list[app_commands.Choice[str]]:
            names = self.index.artists(current, CHOICE_LIMIT)
            return [app_commands.Choice(name=n[:NAME_LIMIT], value=n[:NAME_LIMIT]) for n in names]

        random_tracks.autocomplete("artist")(artist_autocomplete)
        browse.autocomplete("artist")(artist_autocomplete)

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
            lines += [f"{i}. {t.label}" for i, t in enumerate(list(player.queue)[:LIST_LIMIT], start=1)]
            if len(player.queue) > LIST_LIMIT:
                lines.append(f"외 {len(player.queue) - LIST_LIMIT}곡")
            source = player.autoplay_source()
            lines.append(f"그다음은 {source or '전체 곡'}에서 랜덤으로 이어서 틀어요.")
            await interaction.response.send_message("\n".join(lines))
