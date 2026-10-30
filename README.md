<div align="center">

<img src="assets/kanade.svg" alt="" width="96">

# kanade

**A Discord bot that plays music from a Plex library in a voice channel**

Made for one friends' server.

[![build](https://github.com/dor1a/kanade/actions/workflows/build.yml/badge.svg)](https://github.com/dor1a/kanade/actions/workflows/build.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](Dockerfile)
[![image](https://img.shields.io/badge/image-ghcr.io%2Fdor1a%2Fkanade-2496ED?logo=docker&logoColor=white)](https://github.com/dor1a/kanade/pkgs/container/kanade)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

</div>

> [!NOTE]
> Phase 1 of [the plan](docs/PLAN.md), playback, runs on the friends' server. Phase 2, Korean search, is written and checked in Docker but not yet on the server. Plex movie and show search comes later.

## Commands

| Command | What it does |
| -- | -- |
| `/play <query>` | Searches the music library as you type, in Hangul too (see [Korean search](#korean-search)), and plays the chosen track, or queues it if something is playing |
| `/random [count] [artist]` | Queues random tracks (five by default), from one artist if given, and keeps drawing from the same pool after the queue |
| `/browse <artist>` | Opens menus, visible only to you, to pick one of the artist's albums and then a track or the whole album |
| `/skip` | Skips the current track |
| `/queue` | Shows the current track, up to ten queued ones, and what plays after them |
| `/stop` | Clears the queue and leaves the voice channel |

Commands are registered to one guild (`DISCORD_GUILD_ID`), so they appear right after the bot starts. With `DISCORD_CHANNEL_ID` set, they work only in that channel.

## How playback works

- At startup the bot loads every track in the music library from Plex into memory, and it reloads the list every 30 minutes. Autocomplete keeps the tracks whose title, track artist, album artist, album, and their Korean readings together contain every word typed, title matches first.
- When the queue runs out, playback continues with a random track that has not played since the bot joined the voice channel. After `/play` or `/browse` it comes from the last track's artist, after `/random` from the same pool `/random` used, and it moves to the whole library when that pool runs out. `/stop` ends it. The bot leaves a minute after the last person leaves the voice channel, unless someone comes back.
- The reply to a command that starts playback is a now-playing card with the album art. Later tracks post the same card to `DISCORD_CHANNEL_ID`, or to the channel of the last command when it is empty. Plex is not reachable from Discord, so the bot fetches the art from Plex at 300 px and uploads it with the card.
- Plex `/hubs/search` is not used for this because a query for an artist name lands in its artist hub, and its track hub returns only a few of that artist's tracks. It is the fallback when the track list could not be loaded. Discord drops autocomplete answers after three seconds, so the bot waits 2.5 seconds at most for it.
- The bot opens the track's original file on Plex and hands the stream to `discord.FFmpegOpusAudio(pipe=True)`. discord.py feeds it to ffmpeg's stdin from a thread. The Plex token stays in an HTTP header and never appears in the ffmpeg command line.
- Voice uses `discord.py[voice]` 2.7.1, which pulls in `davey` for Discord's end-to-end encrypted voice (DAVE). Discord requires it for voice since 2026-03-01.

## Korean search

Japanese and Chinese names also match their Korean readings, so the server can type in Hangul.

| Typed | Finds | How |
| -- | -- | -- |
| `키미가` or `기미가` | 君がいない | Janome reads the kana and a table spells it in Hangul: the common spelling (켄시, 츠) and the official one (겐시, 쓰), with and without long vowels (토우쿄우, 도쿄) |
| `욘센넨` or `사천년` | 四千年 | Text in Han characters only also gets the Korean reading of the characters (hanja) |
| `자드` or `웨스트라이프` | ZARD, Westlife | Korean names of the artist on MusicBrainz and Wikidata |
| `다오코` | Daoko | Optional: an LLM's Hangul spelling, for artists in Latin letters that neither source has a Korean name for |
| `ㅈㅇㄴ` | 좋은 날 | Initial consonants of the Hangul words, readings included |
| `요넺` | 米津玄師, with the alias below | Text is compared as jamo, so a syllable that is still being typed matches |
| `요네주켄시` | 米津玄師, with the alias below | When nothing matches exactly, rapidfuzz offers near misses |

- Generated readings go wrong mostly on names (Janome reads 米津玄師 as ヨネツゲンシ). `/etc/kanade/aliases.toml` adds search words for any title, artist, or album, keyed by the name as Plex spells it:

  ```toml
  "米津玄師" = ["요네즈 켄시"]
  "ESTi" = "에스티"
  ```

  The file is reread with the track list every 30 minutes. A broken file keeps the last good copy.
- After startup the bot asks MusicBrainz about each artist not written in Hangul, one request a second, in the background. Wikidata then gives the Korean names of the artists MusicBrainz found, looked up by their MusicBrainz ID a hundred at a time. A few hundred artists take several minutes the first time. The answers are cached in `/data/artists.json`, so later runs ask only about new artists. Artists that had no Korean name are asked again after 30 days. Delete the file to ask about every artist again.
- With `LLM_ENDPOINT` set, the bot then sends the artists still without a Korean name to that OpenAI-compatible endpoint, 25 names a request, and keeps only the answers written in Hangul. Only names with Latin letters are sent: kana already reads exactly, and the model often misread Japanese names in Han characters, so those keep Janome's reading. The prompt asks for the sound of the name, not a translation. An artist is asked once; the answer is cached in the same file and is dropped as soon as MusicBrainz or Wikidata has a name, or when a new version of the bot changes the prompt. The model gets some names wrong (`gemma3:12b-it-qat` spelled 20 of 25 sample names as Korean music sites do, `qwen3.5:9b` 15), and a wrong name only adds an extra search word; the name as Plex spells it still matches. If the endpoint is down, search works as before and the next refresh asks again.
- Building the readings for a few thousand tracks takes about a second and runs off the event loop. Janome adds about 70 MB of memory.

## Configuration

Every key the bot reads is in `.env.example`.

| Key | Meaning |
| -- | -- |
| `DISCORD_TOKEN` | Bot token from the Discord developer portal |
| `DISCORD_GUILD_ID` | The server the commands are registered to |
| `DISCORD_CHANNEL_ID` | The only channel that takes commands and gets now-playing cards. Empty allows every channel |
| `PLEX_URL` | Plex base URL, for example `http://plex.example:32400` |
| `PLEX_TOKEN` | Plex token. Sent only as the `X-Plex-Token` header |
| `PLEX_MUSIC_SECTION_ID` | Music library section. Empty loads every music section |
| `KANADE_BITRATE_KBPS` | Opus bitrate sent to Discord. Default 128 |
| `LLM_ENDPOINT` | Optional OpenAI-compatible base URL, for example `http://ollama:11434/v1`. Empty turns the LLM off |
| `LLM_API_KEY` | Sent as a bearer token when set. Ollama needs none |
| `LLM_MODEL` | Model name. Required when `LLM_ENDPOINT` is set |
| `LLM_REASONING_EFFORT` | Sent as `reasoning_effort` when set. `none` keeps reasoning models from writing a long trace before the answer |
| `TZ` | Time zone for log timestamps, for example `Asia/Seoul`. Empty means UTC. `python:3.12-slim` ships zoneinfo, so nothing else is needed |

| Path | Meaning |
| -- | -- |
| `/etc/kanade/aliases.toml` | Optional alias file for Korean search. Mount it read-only |
| `/data` | Writable, owned by uid 10001. Holds the artist name cache. Without it the cache lives in memory until the bot restarts |

## Discord application

1. Create an application in the Discord developer portal and add a bot. Copy its token.
2. Invite it with the `bot` and `applications.commands` scopes and the View Channels, Send Messages, Embed Links, Attach Files, Connect, and Speak permissions. The message permissions are for the now-playing cards the bot posts on its own.
3. No privileged intents are needed.

## Run

Version tags publish images for `linux/amd64` and `linux/arm64` to GitHub Container Registry. `v0.1.0` gets `0.1.0`, `0.1`, and `latest`. A release candidate such as `v0.1.0-rc.1` gets only its own tag.

```sh
docker run --rm --env-file .env -v ./kanade:/etc/kanade:ro -v kanade-data:/data ghcr.io/dor1a/kanade:0.1
```

To build it yourself:

```sh
docker build -t kanade .
docker run --rm --env-file .env kanade
```

The image is `python:3.12-slim` with ffmpeg. Build for `linux/amd64` on Apple Silicon if the host that runs it is x86_64.

## License

MIT, see `LICENSE`. The Docker image also installs Debian's `ffmpeg` package (LGPL and GPL), Janome (Apache-2.0, with the IPADIC dictionary under its own license), hanja (WTFPL), and rapidfuzz and PyYAML (MIT), each under its own terms. Korean artist names come from MusicBrainz, whose core data is CC0, and from Wikidata, whose structured data is CC0.
