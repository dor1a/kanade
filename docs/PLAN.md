# kanade plan

> Status: phase 1 runs on the friends' server (2026-10-29). Phase 2 is written and checked in Docker with sample names; it has not run on the server yet.

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

## Korean search (phase 2)

Plex search matches the stored text, so a Korean query cannot find a title written in another script. At startup and every 30 minutes the bot loads each track's title, track artist, album artist, and album from Plex into memory, adds Korean readings and aliases for each, and autocomplete keeps the tracks that contain every typed word. Plex search fell short here as well: a query for an artist name lands in the artist hub, and the track hub returned 3 of that artist's 347 tracks in one test.

The library (2026-10-29): 2,523 tracks in 7 sections. Titles are 880 in kana, 128 in Han characters only, 189 in Hangul, and 1,326 in Latin or other scripts. Of 509 album artists, 364 are in Latin script.

| Source | Words added | Example |
| -- | -- | -- |
| Japanese | Janome's kana reading spelled in Hangul: common and official spelling, with and without long vowels | 君がいない → 키미가이나이, 기미가이나이 |
| Han characters only | The Japanese reading and the Korean reading of the characters (`hanja`), since the script does not tell Japanese from Chinese | 四千年 → 욘센넨, 사천년 |
| Artists not in Hangul | Korean aliases from MusicBrainz and Korean labels from Wikidata, cached in `/data/artists.json` | ZARD → 자드, Westlife → 웨스트라이프 |
| Artists neither source names | Optional: an LLM's Hangul spelling, cached in the same file | Daoko → 다오코 |
| Hangul | As written, plus the initial consonants | 좋은 날 → ㅈㅇㄴ |
| Any name | Hand-kept aliases in `/etc/kanade/aliases.toml` | 米津玄師 → 요네즈 켄시 |

- Janome (Apache-2.0) instead of pykakasi (GPL-3.0-or-later). On sample names Janome read everyday words better (君 as キミ, where pykakasi gave クン), and both misread some names, so names go in the alias table either way.
- Text is NFKC-normalized and casefolded, with conjoining jamo mapped back to the compatibility jamo a keyboard types. Hangul is compared as jamo, so a half-typed syllable matches.
- Initials run together within a name, so ㅈㅇㄴ finds 좋은 날, but not across names.
- MusicBrainz finds the artist by name (score 95 or more, and the name or an alias equal to the Plex name). Wikidata labels are then fetched by that MusicBrainz ID (property P434), because a Wikidata search by name picked the wrong item in tests: LiSA matched a given name and ESTi a family name. MusicBrainz had Korean aliases for 46 of 536 artists; Wikidata had Korean names for 12 of 15 sample artists.
- On the first run over 536 artists, MusicBrainz and Wikidata gave Korean names for 285. The LLM is asked only about the rest, and only answers written entirely in Hangul are kept. On 25 sample names with known Korean spellings, `gemma3:12b-it-qat` matched 20 and `qwen3.5:9b` 15 (2026-10-30). Both got Japanese personal names right, family name first; `qwen3.5:9b` misspelled more English names (링크인 파크 for Linkin Park). The model is a setting, so it follows whatever the LLM server runs.
- Other sources were checked and left out. The iTunes Search API on the Korean store returns romanized or original names (あいみょん → aimyon), Spotify and Last.fm have no Korean names, Discogs needs a token and rarely has Korean, and Korean music stores have no public API.
- rapidfuzz `partial_ratio` (cutoff 80) runs only when nothing matches exactly, so it does not push near misses into a good result list.
- On 2,523 sample tracks the index with readings builds in about 1 second and a search takes 1 to 4 ms.
- Not done: pinyin readings for Chinese names (周杰倫 → 저우제룬 with `pypinyin`).

## Out of scope

- Video. Discord documents no way for a bot to send video, and Activities need a public HTTPS origin
- More than one server. Commands are registered to one guild
- Plex transcoding. The bot reads the original file and ffmpeg encodes Opus
- Paid APIs or services

## How it is built

- Checks and image builds run in the `python:3.12-slim` container, so the host needs only Docker.
- Phase 1 depends only on `discord.py[voice]`. Phase 2 adds `janome`, `hanja`, and `rapidfuzz`. `hanja` is installed with `--no-deps` because it lists its test tools as requirements; at runtime it needs only `PyYAML`, which is listed itself. `pypinyin` is still a candidate. Anything beyond these needs a written reason.
- A release candidate tag (`vX.Y.Z-rc.N`) is tested on the server before the release tag.
- One small feature at a time, each finished before the next.

## Decisions left to a person

| Item | Where the draft is |
| -- | -- |
| Contents of the alias table | Korean search |
| Meaning-based aliases from a local model (optional) | Korean search |
| Media search commands and output | Phases |
