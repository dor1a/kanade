"""Settings read from the environment."""

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: int
    plex_url: str
    plex_token: str
    plex_section_id: str
    bitrate_kbps: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            discord_token=_required("DISCORD_TOKEN"),
            guild_id=int(_required("DISCORD_GUILD_ID")),
            plex_url=_required("PLEX_URL").rstrip("/"),
            plex_token=_required("PLEX_TOKEN"),
            # Empty means search every library section.
            plex_section_id=os.environ.get("PLEX_MUSIC_SECTION_ID", "").strip(),
            bitrate_kbps=int(os.environ.get("KANADE_BITRATE_KBPS", "128")),
        )
