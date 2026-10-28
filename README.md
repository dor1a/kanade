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

## Status

MVP. The code builds and imports, but it has not played a track in a live voice channel yet.

Planned:

- A search index that finds English, Japanese, and Chinese titles from their Korean readings
- Plex search for movies and shows. It only looks them up; playback stays music only

## Commands

| Command | What it does |
| -- | -- |
| `/play <query>` | Searches Plex as you type and plays the chosen track, or queues it if something is playing |
| `/skip` | Skips the current track |
| `/queue` | Shows the current track and up to ten queued ones |
| `/stop` | Clears the queue and leaves the voice channel |

Commands are registered to one guild (`DISCORD_GUILD_ID`), so they appear right after the bot starts.

## How playback works

- Search uses Plex `/hubs/search`, which Plex intends to be called while the user types. Discord drops autocomplete answers after three seconds, so the bot waits 2.5 seconds at most.
- The bot opens the track's original file on Plex and hands the stream to `discord.FFmpegOpusAudio(pipe=True)`. discord.py feeds it to ffmpeg's stdin from a thread. The Plex token stays in an HTTP header and never appears in the ffmpeg command line.
- Voice uses `discord.py[voice]` 2.7.1, which pulls in `davey` for Discord's end-to-end encrypted voice (DAVE). Discord requires it for voice since 2026-03-01.

## Configuration

Every key the bot reads is in `.env.example`.

| Key | Meaning |
| -- | -- |
| `DISCORD_TOKEN` | Bot token from the Discord developer portal |
| `DISCORD_GUILD_ID` | The server the commands are registered to |
| `PLEX_URL` | Plex base URL, for example `http://plex.example:32400` |
| `PLEX_TOKEN` | Plex token. Sent only as the `X-Plex-Token` header |
| `PLEX_MUSIC_SECTION_ID` | Music library section. Empty searches every section |
| `KANADE_BITRATE_KBPS` | Opus bitrate sent to Discord. Default 128 |

## Discord application

1. Create an application in the Discord developer portal and add a bot. Copy its token.
2. Invite it with the `bot` and `applications.commands` scopes and the Connect and Speak permissions.
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
