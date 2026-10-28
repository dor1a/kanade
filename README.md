# kanade

A Discord bot that plays music from a Plex library in a voice channel. It is meant for one friends' server.

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

```sh
docker build -t kanade .
docker run --rm --env-file .env kanade
```

The image is `python:3.12-slim` with ffmpeg. Build for `linux/amd64` on Apple Silicon if the host that runs it is x86_64.

## License

MIT, see `LICENSE`. The Docker image installs Debian's `ffmpeg` package, which keeps its own LGPL and GPL terms.
