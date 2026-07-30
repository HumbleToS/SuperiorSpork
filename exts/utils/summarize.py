from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import config

if TYPE_CHECKING:
    from aiohttp import ClientSession

API_URL = "https://api.anthropic.com/v1/messages"
CHUNK_CHARS = 16000
FALLBACK_TITLE = "Voice Session"
RECAP_PROMPT = (
    "You are writing a session recap for a discord voice call. From the transcript, produce:"
    " a first line formatted exactly as 'TITLE: <short evocative title>', then a short narrative summary,"
    " then markdown sections '### Key Decisions', '### Action Items', and '### Notable Quotes'"
    " (quotes keep their speaker names). Summarize only what was said: do not speculate about speakers,"
    " their identities, health, finances, or any other personal attributes, and do not profile anyone."
    " Keep the whole recap under 2000 characters."
)
CHUNK_PROMPT = "Summarize this portion of a voice call transcript in under 400 words, keeping speaker names."


class SummaryProvider(Protocol):
    async def summarize(self, transcript: str) -> tuple[str, str]: ...


class AnthropicProvider:
    """Recap generation over the anthropic messages api, through the bot's shared session."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session

    async def _call(self, prompt: str, text: str, max_tokens: int = 1200) -> str:
        key = getattr(config, "ANTHROPIC_KEY", "")
        if not key or key == "key":
            raise RuntimeError("ANTHROPIC_KEY is not set in config.py")
        payload = {
            "model": getattr(config, "RECAP_MODEL", "claude-haiku-4-5-20251001"),
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": f"{prompt}\n\n<transcript>\n{text}\n</transcript>"}],
        }
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        async with self.session.post(API_URL, json=payload, headers=headers) as resp:
            body = await resp.json()
            if resp.status != 200:
                message = body.get("error", {}).get("message", "unknown error")
                raise RuntimeError(f"anthropic api returned {resp.status}: {message}")
            return "".join(block["text"] for block in body["content"] if block["type"] == "text")

    async def summarize(self, transcript: str) -> tuple[str, str]:
        if len(transcript) > CHUNK_CHARS:
            # hierarchical: summarize chunks, then recap the summaries
            parts = [transcript[i : i + CHUNK_CHARS] for i in range(0, len(transcript), CHUNK_CHARS)]
            partials = [await self._call(CHUNK_PROMPT, part, max_tokens=600) for part in parts]
            transcript = "\n\n".join(partials)

        raw = await self._call(RECAP_PROMPT, transcript)
        title, _, recap = raw.partition("\n")
        if title.upper().startswith("TITLE:"):
            title = title[6:].strip()
        else:
            title, recap = FALLBACK_TITLE, raw
        return title or FALLBACK_TITLE, recap.strip()
