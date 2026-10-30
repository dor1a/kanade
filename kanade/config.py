"""Settings read from the environment."""

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


@dataclass(frozen=True)
class Config:
    discord_token: str
    guild_id: int
    channel_id: int | None
    plex_url: str
    plex_token: str
    plex_section_id: str
    bitrate_kbps: int
    llm_endpoint: str
    llm_api_key: str
    llm_model: str
    llm_reasoning_effort: str

    @classmethod
    def from_env(cls) -> "Config":
        # Empty means no LLM; artist names then come only from MusicBrainz and Wikidata.
        llm_endpoint = os.environ.get("LLM_ENDPOINT", "").strip().rstrip("/")
        return cls(
            discord_token=_required("DISCORD_TOKEN"),
            guild_id=int(_required("DISCORD_GUILD_ID")),
            # Empty means commands work in any channel.
            channel_id=_optional_int("DISCORD_CHANNEL_ID"),
            plex_url=_required("PLEX_URL").rstrip("/"),
            plex_token=_required("PLEX_TOKEN"),
            # Empty means search every library section.
            plex_section_id=os.environ.get("PLEX_MUSIC_SECTION_ID", "").strip(),
            bitrate_kbps=int(os.environ.get("KANADE_BITRATE_KBPS", "128")),
            llm_endpoint=llm_endpoint,
            llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
            llm_model=_required("LLM_MODEL") if llm_endpoint else "",
            llm_reasoning_effort=os.environ.get("LLM_REASONING_EFFORT", "").strip(),
        )
