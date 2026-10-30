"""Korean aliases for artists from MusicBrainz, cached in a file.

MusicBrainz allows one request per second, so the first run over a few hundred
artists takes minutes. It runs in the background and only asks about artists
that are not cached yet. Delete the cache file to ask again.
"""

import asyncio
import json
import logging
import os
import re

import aiohttp

from .text import fold

log = logging.getLogger(__name__)

API = "https://musicbrainz.org/ws/2/artist/"
USER_AGENT = "kanade ( https://github.com/dor1a/kanade )"
REQUEST_GAP = 1.1  # MusicBrainz allows one request per second per client.
BUSY_PAUSE = 5  # Extra wait after a 503, which is how MusicBrainz says "slow down".
MIN_SCORE = 95
SAVE_EVERY = 50
HANGUL = re.compile(r"[가-힣]")


def korean_aliases(name: str, data: dict) -> list[str]:
    """Hangul aliases of the search hit whose name or alias is exactly `name`."""
    want = fold(name)
    for artist in data.get("artists", []):
        if int(artist.get("score", 0)) < MIN_SCORE:
            continue
        aliases = artist.get("aliases") or []
        names = [artist.get("name", ""), artist.get("sort-name", "")] + [a.get("name", "") for a in aliases]
        if want not in {fold(n) for n in names}:
            continue
        return sorted(
            {a["name"] for a in aliases if a.get("name") and (a.get("locale") == "ko" or HANGUL.search(a["name"]))}
        )
    return []


class ArtistAliases:
    def __init__(self, path: str):
        self._path = path
        self._cache: dict[str, list[str]] = {}
        self._can_save = True

    def __call__(self, name: str) -> list[str]:
        return self._cache.get(name, [])

    def load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            log.exception("could not read %s; starting with an empty MusicBrainz cache", self._path)
            return
        self._cache = {k: [str(a) for a in v] for k, v in data.items() if isinstance(v, list)}
        log.info("loaded MusicBrainz aliases for %d artists", len(self._cache))

    def missing(self, names: set[str]) -> list[str]:
        # Names already in Hangul need no alias.
        return sorted(n for n in names if n and n not in self._cache and not HANGUL.search(n))

    async def fill(self, names: set[str]) -> int:
        """Ask MusicBrainz about artists not cached yet; return how many got Korean aliases."""
        todo = self.missing(names)
        if not todo:
            return 0
        log.info("asking MusicBrainz about %d artists", len(todo))
        found = 0
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        async with aiohttp.ClientSession(headers=headers) as session:
            for i, name in enumerate(todo):
                if i:
                    await asyncio.sleep(REQUEST_GAP)
                try:
                    aliases = await self._lookup(session, name)
                except Exception:
                    # Not cached, so the next refresh asks again.
                    log.debug("MusicBrainz lookup failed for %s", name, exc_info=True)
                    continue
                self._cache[name] = aliases
                found += bool(aliases)
                if (i + 1) % SAVE_EVERY == 0:
                    self._save()
        self._save()
        log.info("MusicBrainz had Korean aliases for %d of %d artists", found, len(todo))
        return found

    async def _lookup(self, session: aiohttp.ClientSession, name: str) -> list[str]:
        phrase = name.replace("\\", "\\\\").replace('"', '\\"')
        params = {"query": f'artist:"{phrase}"', "fmt": "json", "limit": "5"}
        async with session.get(API, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 503:
                await asyncio.sleep(BUSY_PAUSE)
                raise RuntimeError("MusicBrainz asked to slow down")
            resp.raise_for_status()
            data = await resp.json()
        return korean_aliases(name, data)

    def _save(self) -> None:
        if not self._can_save:
            return
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError:
            self._can_save = False
            log.warning("cannot write %s; MusicBrainz aliases stay in memory until the bot restarts", self._path)
