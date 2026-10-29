# kanade plan

> Status: phase 1 is written and checked in Docker: imports, Plex response parsing, and the amd64 and arm64 images. It has not played a track in a live voice channel yet.

## Summary

kanade plays music from a Plex library in a Discord voice channel, for one friends' server.

| Item | Detail |
| -- | -- |
| Environment | One host with docker compose |
| Shape | One Python process, one image with ffmpeg |
| Discord | Guild commands on one server, `discord.py[voice]` 2.7.1 with `davey` for end-to-end encrypted voice |
| Plex | The Plex HTTP API through `aiohttp`. The token goes only in the `X-Plex-Token` header |
| License | MIT |

## Phases

| Phase | Scope | Done when |
| -- | -- | -- |
| 1. Playback | `/play` with autocomplete, `/random`, `/browse`, `/skip`, `/queue`, `/stop`, continuous play, now-playing cards, one command channel | A track plays on the friends' server from a published image |
| 2. Korean search | A local index of the music library, matched while the user types | A Korean query finds an English, Japanese, or Chinese title within Discord's three-second autocomplete limit |
| 3. Media search | Search Plex movies and shows and list what is there. Lookup only | Decided later |

## Korean search (phase 2 draft)

Plex search matches the stored text, so a Korean query cannot find a title written in another script. The index keeps several readings for each title and artist.

The plain-text part is in place. At startup and every 30 minutes the bot loads each track's title, track artist, album artist, and album from Plex into memory, and autocomplete keeps the tracks that contain every typed word. Plex search fell short here as well: a query for an artist name lands in the artist hub, and the track hub returned 3 of that artist's 347 tracks in one test. The readings below go into the same in-memory entries.

| Source | Readings stored | Example |
| -- | -- | -- |
| Japanese | The kana reading (`pykakasi`) written in Hangul, not the Korean reading of the kanji | 米津玄師 → 요네즈 켄시 |
| Chinese | Both the Korean reading of the characters (`hanja`) and the pinyin (`pypinyin`) written in Hangul | 周杰倫 → 주걸륜, 저우제룬 |
| English | Korean aliases from MusicBrainz (`inc=aliases`, `locale=ko`). Some artists have none | |
| Korean | As written, plus the initial consonants | 아이유 → ㅇㅇㅇ |

- Rules misread the kanji in Japanese names often enough that a hand-kept alias table covers them.
- Autocomplete runs on every keystroke, so queries match by prefix on decomposed jamo, with `rapidfuzz` for typos.
- All text is NFC-normalized.
- The library is about 2,500 tracks (mp3 and flac), small enough to hold the whole index in memory.

## Out of scope

- Video. Discord documents no way for a bot to send video, and Activities need a public HTTPS origin
- More than one server. Commands are registered to one guild
- Plex transcoding. The bot reads the original file and ffmpeg encodes Opus
- Paid APIs or services

## How it is built

- Checks and image builds run in the `python:3.12-slim` container, so the host needs only Docker.
- Phase 1 depends only on `discord.py[voice]`. Phase 2 candidates are `pykakasi`, `pypinyin`, `hanja`, and `rapidfuzz`. Anything beyond these needs a written reason.
- A release candidate tag (`vX.Y.Z-rc.N`) is tested on the server before the release tag.
- One small feature at a time, each finished before the next.

## Decisions left to a person

| Item | Where the draft is |
| -- | -- |
| Where the alias table lives (SQLite or Postgres). The track list itself is rebuilt from Plex in memory | Korean search |
| Contents of the alias table | Korean search |
| Meaning-based aliases from a local model (optional) | Korean search |
| Media search commands and output | Phases |
