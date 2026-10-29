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
> Phase 1 of [the plan](docs/PLAN.md), playback, is written but has not played a track in a live voice channel yet. Korean search and Plex media search come after it.

## Commands

| Command | What it does |
| -- | -- |
| `/play <query>` | Searches the music library as you type and plays the chosen track, or queues it if something is playing |
| `/random [count] [artist]` | Queues random tracks (five by default), from one artist if given, and keeps drawing from the same pool after the queue |
| `/browse <artist>` | Opens menus, visible only to you, to pick one of the artist's albums and then a track or the whole album |
| `/skip` | Skips the current track |
| `/queue` | Shows the current track, up to ten queued ones, and what plays after them |
| `/stop` | Clears the queue and leaves the voice channel |

Commands are registered to one guild (`DISCORD_GUILD_ID`), so they appear right after the bot starts. With `DISCORD_CHANNEL_ID` set, they work only in that channel.

## How playback works

- At startup the bot loads every track in the music library from Plex into memory, and it reloads the list every 30 minutes. Autocomplete keeps the tracks whose title, track artist, album artist, and album together contain every word typed, title matches first.
- When the queue runs out, playback continues with a random track that has not played since the bot joined the voice channel. After `/play` or `/browse` it comes from the last track's artist, after `/random` from the same pool `/random` used, and it moves to the whole library when that pool runs out. `/stop` ends it, and the bot also leaves when a track ends and no one but bots is left in the voice channel.
- The reply to a command that starts playback is a now-playing card with the album art. Later tracks post the same card to `DISCORD_CHANNEL_ID`, or to the channel of the last command when it is empty. Plex is not reachable from Discord, so the bot fetches the art from Plex at 300 px and uploads it with the card.
- Plex `/hubs/search` is not used for this because a query for an artist name lands in its artist hub, and its track hub returns only a few of that artist's tracks. It is the fallback when the track list could not be loaded. Discord drops autocomplete answers after three seconds, so the bot waits 2.5 seconds at most for it.
- The bot opens the track's original file on Plex and hands the stream to `discord.FFmpegOpusAudio(pipe=True)`. discord.py feeds it to ffmpeg's stdin from a thread. The Plex token stays in an HTTP header and never appears in the ffmpeg command line.
- Voice uses `discord.py[voice]` 2.7.1, which pulls in `davey` for Discord's end-to-end encrypted voice (DAVE). Discord requires it for voice since 2026-03-01.

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
| `TZ` | Time zone for log timestamps, for example `Asia/Seoul`. Empty means UTC. `python:3.12-slim` ships zoneinfo, so nothing else is needed |

## Discord application

1. Create an application in the Discord developer portal and add a bot. Copy its token.
2. Invite it with the `bot` and `applications.commands` scopes and the View Channels, Send Messages, Embed Links, Attach Files, Connect, and Speak permissions. The message permissions are for the now-playing cards the bot posts on its own.
3. No privileged intents are needed.

## Run

Version tags publish images for `linux/amd64` and `linux/arm64` to GitHub Container Registry. `v0.1.0` gets `0.1.0`, `0.1`, and `latest`. A release candidate such as `v0.1.0-rc.1` gets only its own tag.

```sh
docker run --rm --env-file .env ghcr.io/dor1a/kanade:0.1
```

To build it yourself:

```sh
docker build -t kanade .
docker run --rm --env-file .env kanade
```

The image is `python:3.12-slim` with ffmpeg. Build for `linux/amd64` on Apple Silicon if the host that runs it is x86_64.

## License

MIT, see `LICENSE`. The Docker image installs Debian's `ffmpeg` package, which keeps its own LGPL and GPL terms.
