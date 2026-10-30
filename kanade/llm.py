"""Hangul spellings of artist names from an OpenAI-compatible chat endpoint.

The last resort for artists that neither MusicBrainz nor Wikidata has a Korean
name for. Models get some names wrong, so an answer is kept only when it is
written in Hangul, and the cache keeps it apart from the data sources.
"""

import json
import re
from dataclasses import dataclass

import aiohttp

BATCH = 25
TIMEOUT = 300  # A model that is not loaded yet can take minutes to answer.
# Bump when SYSTEM or the names sent change; cached answers from another version are dropped and asked again.
VERSION = 3
ONLY_HANGUL = re.compile(r"[가-힣]+(?: [가-힣]+)*")
SYSTEM = (
    "You write artist names in Hangul the way Korean music sites spell them. "
    "Spell how each name sounds; never translate the meaning of its words. "
    "Japanese personal names written in Latin letters are given name first; write them family name first in Hangul. "
    "Reply with only a JSON object that maps each given name to its Hangul spelling."
)


def parse(names: list[str], text: str) -> dict[str, list[str]]:
    """Hangul answers per asked name; raises ValueError when the reply holds no JSON object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the reply")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("the reply is not a JSON object")
    answers = {}
    for name in names:
        value = data.get(name)
        values = value if isinstance(value, list) else [value]
        answers[name] = sorted({v.strip() for v in values if isinstance(v, str) and ONLY_HANGUL.fullmatch(v.strip())})
    return answers


@dataclass(frozen=True)
class LLM:
    endpoint: str
    model: str
    api_key: str = ""
    reasoning_effort: str = ""

    async def hangul(self, session: aiohttp.ClientSession, names: list[str]) -> dict[str, list[str]]:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(names, ensure_ascii=False)},
            ],
        }
        # Only reasoning models take this field; some other endpoints reject it.
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with session.post(f"{self.endpoint}/chat/completions", json=body, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
        return parse(names, data["choices"][0]["message"]["content"])
