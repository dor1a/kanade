"""Korean names for artists from MusicBrainz and Wikidata, cached in a file.

MusicBrainz finds the artist by name and gives its ID and any Korean aliases.
Wikidata items carry that ID (property P434), so one SPARQL query fetches the
Korean labels of a hundred artists without matching by name, which picks the
wrong item for names like LiSA.

When an LLM endpoint is set, it spells the rest in Hangul if their names have
Latin letters. Kana already reads exactly, and the model often misread Japanese
names in Han characters, so those keep Janome's reading. LLM names are used only
while neither source has one.

MusicBrainz allows one request per second, so the first run over a few hundred
artists takes minutes. It runs in the background and only asks about artists
not cached yet, plus those that had no Korean name last time. Delete the cache
file to ask again.
"""

import asyncio
import datetime
import json
import logging
import os
import re

import aiohttp

from .llm import BATCH as LLM_BATCH, VERSION as LLM_VERSION, LLM
from .text import fold

log = logging.getLogger(__name__)

MUSICBRAINZ = "https://musicbrainz.org/ws/2/artist/"
WIKIDATA = "https://query.wikidata.org/sparql"
USER_AGENT = "kanade ( https://github.com/dor1a/kanade )"
REQUEST_GAP = 1.1  # MusicBrainz allows one request per second per client.
BUSY_PAUSE = 5  # Extra wait after a 503, which is how MusicBrainz says "slow down".
MIN_SCORE = 95
SAVE_EVERY = 50
WIKIDATA_BATCH = 100
RECHECK_DAYS = 30  # Both sources keep growing, so artists without a Korean name are asked again.
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
MBID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

QUERY = """SELECT ?mbid ?name WHERE {
  VALUES ?mbid { %s }
  ?item wdt:P434 ?mbid .
  { ?item rdfs:label ?name } UNION { ?item skos:altLabel ?name }
  FILTER(LANG(?name) = "ko")
}"""


def match(name: str, data: dict) -> tuple[str | None, list[str]]:
    """MusicBrainz ID and Hangul aliases of the search hit whose name or alias is exactly `name`."""
    want = fold(name)
    for artist in data.get("artists", []):
        if int(artist.get("score", 0)) < MIN_SCORE:
            continue
        aliases = artist.get("aliases") or []
        names = [artist.get("name", ""), artist.get("sort-name", "")] + [a.get("name", "") for a in aliases]
        if want not in {fold(n) for n in names}:
            continue
        mbid = artist.get("id")
        korean = {a["name"] for a in aliases if a.get("name") and (a.get("locale") == "ko" or HANGUL.search(a["name"]))}
        return (mbid if isinstance(mbid, str) and MBID.fullmatch(mbid) else None), sorted(korean)
    return None, []


def wikidata_names(data: dict) -> dict[str, list[str]]:
    """Hangul labels per MusicBrainz ID from a SPARQL JSON result."""
    names: dict[str, set[str]] = {}
    for row in data.get("results", {}).get("bindings", []):
        mbid = row.get("mbid", {}).get("value")
        name = row.get("name", {}).get("value", "")
        if mbid and HANGUL.search(name):
            names.setdefault(mbid, set()).add(name)
    return {k: sorted(v) for k, v in names.items()}


def _entry(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    mbid = value.get("mbid")
    wikidata = value.get("wikidata")
    llm = value.get("llm")
    llm_version = value.get("llm_version")
    return {
        "mbid": mbid if isinstance(mbid, str) and MBID.fullmatch(mbid) else None,
        "musicbrainz": [str(a) for a in value.get("musicbrainz") or []],
        # None means Wikidata has not been asked yet.
        "wikidata": None if wikidata is None else [str(a) for a in wikidata],
        # None means the LLM has not been asked yet.
        "llm": None if llm is None else [str(a) for a in llm],
        "llm_version": llm_version if isinstance(llm_version, int) else None,
        "checked": str(value.get("checked") or ""),
    }


def _data(entry: dict) -> set[str]:
    return set(entry["musicbrainz"]) | set(entry["wikidata"] or ())


class ArtistAliases:
    def __init__(self, path: str, llm: LLM | None = None):
        self._path = path
        self._llm = llm
        self._cache: dict[str, dict] = {}
        self._can_save = True

    def __call__(self, name: str) -> list[str]:
        entry = self._cache.get(name)
        if not entry:
            return []
        llm = entry["llm"] if entry["llm_version"] == LLM_VERSION else None
        return sorted(_data(entry) or llm or ())

    def load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            log.exception("could not read %s; starting with an empty artist cache", self._path)
            return
        self._cache = {k: e for k, v in data.items() if (e := _entry(v))}
        log.info("loaded Korean names for %d artists", sum(bool(self(n)) for n in self._cache))

    def missing(self, names: set[str], today: datetime.date) -> list[str]:
        """Artists to look up: never asked, or asked long ago without finding a Korean name."""
        stale = (today - datetime.timedelta(days=RECHECK_DAYS)).isoformat()
        todo = []
        # Names already in Hangul need no alias.
        for name in names:
            if not name or HANGUL.search(name):
                continue
            entry = self._cache.get(name)
            if entry is None or (not _data(entry) and entry["checked"] < stale):
                todo.append(name)
        return sorted(todo)

    async def fill(self, names: set[str], today: datetime.date | None = None) -> int:
        """Look up artists not cached yet; return how many got new Korean names."""
        today = today or datetime.date.today()
        todo = self.missing(names, today)
        if not todo and not self._wikidata_pending(names) and not self._llm_pending(names):
            return 0
        before = {n: self(n) for n in names}
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        async with aiohttp.ClientSession(headers=headers) as session:
            if todo:
                log.info("asking MusicBrainz about %d artists", len(todo))
            for i, name in enumerate(todo):
                if i:
                    await asyncio.sleep(REQUEST_GAP)
                try:
                    mbid, aliases = await self._musicbrainz(session, name)
                except Exception:
                    # Not cached, so the next refresh asks again.
                    log.debug("MusicBrainz lookup failed for %s", name, exc_info=True)
                    continue
                old = self._cache.get(name) or {}
                self._cache[name] = {
                    "mbid": mbid,
                    "musicbrainz": aliases,
                    "wikidata": None,
                    "llm": old.get("llm"),
                    "llm_version": old.get("llm_version"),
                    "checked": today.isoformat(),
                }
                if (i + 1) % SAVE_EVERY == 0:
                    self._save()
            await self._fill_wikidata(session, names)
            await self._fill_llm(session, names)
        self._save()
        found = sum(self(n) != before[n] for n in names)
        log.info("%d artists got Korean names", found)
        return found

    def _wikidata_pending(self, names: set[str]) -> list[str]:
        ids = {e["mbid"] for n in names if (e := self._cache.get(n)) and e["mbid"] and e["wikidata"] is None}
        return sorted(ids)

    async def _fill_wikidata(self, session: aiohttp.ClientSession, names: set[str]) -> None:
        pending = self._wikidata_pending(names)
        for start in range(0, len(pending), WIKIDATA_BATCH):
            batch = set(pending[start : start + WIKIDATA_BATCH])
            try:
                labels = await self._wikidata(session, sorted(batch))
            except Exception as e:
                # Left as not asked, so the next refresh tries again.
                log.warning("Wikidata query failed (%s); asking again at the next refresh", e)
                continue
            for entry in self._cache.values():
                if entry["mbid"] in batch:
                    entry["wikidata"] = labels.get(entry["mbid"], [])

    def _llm_pending(self, names: set[str]) -> list[str]:
        """Artists in Latin letters that both sources have answered about without a Korean name."""
        if not self._llm:
            return []
        pending = []
        for name in names:
            entry = self._cache.get(name)
            if not entry or not LATIN.search(name) or _data(entry):
                continue
            if entry["llm"] is not None and entry["llm_version"] == LLM_VERSION:
                continue
            if entry["mbid"] and entry["wikidata"] is None:
                continue
            pending.append(name)
        return sorted(pending)

    async def _fill_llm(self, session: aiohttp.ClientSession, names: set[str]) -> None:
        pending = self._llm_pending(names)
        if pending:
            log.info("asking the LLM about %d artists", len(pending))
        for start in range(0, len(pending), LLM_BATCH):
            batch = pending[start : start + LLM_BATCH]
            try:
                answers = await self._llm.hangul(session, batch)
            except Exception as e:
                # Left as not asked; a down endpoint is not worth waiting on for every batch.
                log.warning("LLM request failed (%s); asking again at the next refresh", e)
                return
            for name in batch:
                self._cache[name]["llm"] = answers.get(name, [])
                self._cache[name]["llm_version"] = LLM_VERSION

    async def _musicbrainz(self, session: aiohttp.ClientSession, name: str) -> tuple[str | None, list[str]]:
        phrase = name.replace("\\", "\\\\").replace('"', '\\"')
        params = {"query": f'artist:"{phrase}"', "fmt": "json", "limit": "5"}
        async with session.get(MUSICBRAINZ, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 503:
                await asyncio.sleep(BUSY_PAUSE)
                raise RuntimeError("MusicBrainz asked to slow down")
            resp.raise_for_status()
            data = await resp.json()
        return match(name, data)

    async def _wikidata(self, session: aiohttp.ClientSession, mbids: list[str]) -> dict[str, list[str]]:
        query = QUERY % " ".join(f'"{m}"' for m in mbids)
        headers = {"Accept": "application/sparql-results+json"}
        timeout = aiohttp.ClientTimeout(total=60)
        async with session.post(WIKIDATA, data={"query": query}, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            return wikidata_names(await resp.json(content_type=None))

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
            log.warning("cannot write %s; artist names stay in memory until the bot restarts", self._path)
