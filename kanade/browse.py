"""Menus for /browse: pick an album, then a track or the whole album."""

from collections.abc import Awaitable, Callable

import discord

from .plex import Track

PAGE = 25  # Discord allows 25 options in one select menu.
TEXT_LIMIT = 100
TIMEOUT = 600  # Shorter than the 15 minutes an interaction token stays valid.

PlayTracks = Callable[[discord.Interaction, list[Track]], Awaitable[None]]


def _albums(artist: str, tracks: list[Track]) -> list[tuple[str, str, list[Track]]]:
    albums: dict[tuple[str, str], list[Track]] = {}
    for t in tracks:
        albums.setdefault((t.album_artist, t.album), []).append(t)
    grouped = [(album_artist, album, items) for (album_artist, album), items in albums.items()]
    # The artist's own albums first, then compilations it appears on.
    grouped.sort(key=lambda a: a[0].casefold() != artist.casefold())
    return grouped


class BrowseView(discord.ui.View):
    def __init__(self, origin: discord.Interaction, artist: str, tracks: list[Track], play: PlayTracks):
        super().__init__(timeout=TIMEOUT)
        self._origin = origin
        self._artist = artist
        self._albums = _albums(artist, tracks)
        self._play = play
        self._album: int | None = None
        self._page = 0
        self._render()

    def text(self) -> str:
        if self._album is None:
            return f"{self._artist}: 앨범 {len(self._albums)}개"
        _, album, items = self._albums[self._album]
        return f"{self._artist} / {album}: {len(items)}곡"

    def _render(self) -> None:
        self.clear_items()
        if self._album is None:
            total = len(self._albums)
            start = self._page * PAGE
            options = []
            for i, (album_artist, album, items) in enumerate(self._albums[start : start + PAGE], start=start):
                same = album_artist.casefold() == self._artist.casefold()
                note = f"{len(items)}곡" if same else f"{album_artist}, {len(items)}곡"
                options.append(
                    discord.SelectOption(
                        label=(album or "(앨범 없음)")[:TEXT_LIMIT], value=str(i), description=note[:TEXT_LIMIT]
                    )
                )
            select = discord.ui.Select(placeholder="앨범 고르기", options=options)

            async def open_album(interaction: discord.Interaction) -> None:
                self._album, self._page = int(select.values[0]), 0
                await self._redraw(interaction)

            select.callback = open_album
            self.add_item(select)
        else:
            items = self._albums[self._album][2]
            total = len(items)
            start = self._page * PAGE
            options = [
                discord.SelectOption(label=f"{t.number}. {t.title or '(제목 없음)'}"[:TEXT_LIMIT], value=str(i))
                for i, t in enumerate(items[start : start + PAGE], start=start)
            ]
            select = discord.ui.Select(placeholder="곡 고르기", options=options)

            async def play_track(interaction: discord.Interaction) -> None:
                await self._play(interaction, [items[int(select.values[0])]])

            async def play_album(interaction: discord.Interaction) -> None:
                await self._play(interaction, list(items))

            select.callback = play_track
            self.add_item(select)
            whole = discord.ui.Button(label="앨범 전체 재생", style=discord.ButtonStyle.primary)
            whole.callback = play_album
            self.add_item(whole)
            back = discord.ui.Button(label="앨범 목록으로", style=discord.ButtonStyle.secondary)
            back.callback = self._back
            self.add_item(back)
        if total > PAGE:
            prev = discord.ui.Button(label="이전", style=discord.ButtonStyle.secondary, disabled=self._page == 0)
            prev.callback = self._prev_page
            self.add_item(prev)
            nxt = discord.ui.Button(label="다음", style=discord.ButtonStyle.secondary, disabled=start + PAGE >= total)
            nxt.callback = self._next_page
            self.add_item(nxt)

    async def _redraw(self, interaction: discord.Interaction) -> None:
        self._render()
        await interaction.response.edit_message(content=self.text(), view=self)

    async def _back(self, interaction: discord.Interaction) -> None:
        self._page = self._album // PAGE
        self._album = None
        await self._redraw(interaction)

    async def _prev_page(self, interaction: discord.Interaction) -> None:
        self._page -= 1
        await self._redraw(interaction)

    async def _next_page(self, interaction: discord.Interaction) -> None:
        self._page += 1
        await self._redraw(interaction)

    async def on_timeout(self) -> None:
        try:
            await self._origin.edit_original_response(view=None)
        except discord.HTTPException:
            pass
