from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from .capture import MANIFEST_NAME, align
from .summarize import AnthropicProvider
from .transcribe import FasterWhisperProvider

if TYPE_CHECKING:
    import uuid
    from collections.abc import Awaitable, Callable

    import asyncpg

    from bot import Spork

_logger = logging.getLogger(__name__)

VOICE_DIR = Path("data/voice")
MAX_ATTEMPTS = 3
BACKOFF_BASE = 300  # 5 minutes, doubled per failed attempt


class Pipeline:
    """Drives queued sessions through transcription and recap, one at a time.

    Invariants this class owns: raw audio is deleted the moment a transcript
    is stored, and on final failure; retries reuse the stored transcript, so
    audio never outlives transcription.
    """

    def __init__(self, bot: Spork) -> None:
        self.bot = bot
        self.store = bot.sessions
        self.transcriber = FasterWhisperProvider()
        self.summarizer = AnthropicProvider(bot.session)
        # the recaps cog injects these so the pipeline stays presentation-free
        self.on_done: Callable[[asyncpg.Record, str, str, str], Awaitable[None]] | None = None
        self.on_failed: Callable[[asyncpg.Record, str], Awaitable[None]] | None = None

    @staticmethod
    def session_dir(session_id: uuid.UUID) -> Path:
        return VOICE_DIR / str(session_id)

    @classmethod
    def delete_audio(cls, session_id: uuid.UUID) -> None:
        shutil.rmtree(cls.session_dir(session_id), ignore_errors=True)

    async def sweep_orphans(self) -> None:
        """Startup cleanup: no audio directory may exist without a retryable session."""
        for row in await self.store.stale_recording_sessions():
            await self.store.fail(row["id"], "recording was interrupted by a restart")
            self.delete_audio(row["id"])
        await self.store.reset_processing()

        keep = {str(session_id) for session_id in await self.store.retryable_session_ids()}
        for name in await asyncio.to_thread(self._sweep_dirs, keep):
            _logger.info(f"Swept orphaned session audio {name}")

    @staticmethod
    def _sweep_dirs(keep: set[str]) -> list[str]:
        if not VOICE_DIR.exists():
            return []
        swept = []
        for path in VOICE_DIR.iterdir():
            if path.is_dir() and path.name not in keep:
                shutil.rmtree(path, ignore_errors=True)
                swept.append(path.name)
        return swept

    async def poll_once(self) -> None:
        row = await self.store.claim_next()
        if row is None:
            return
        session_id = row["id"]
        try:
            transcript = row["transcript"]
            if transcript is None:
                transcript = await self._transcribe_session(session_id)
                await self.store.save_transcript(session_id, transcript)
                # raw audio dies the moment the transcript is stored
                self.delete_audio(session_id)
            title, recap = await self.summarizer.summarize(transcript)
            await self.store.finish(session_id, title, recap)
            _logger.info(f"Session {session_id} processed")
            if self.on_done is not None:
                await self.on_done(row, title, recap, transcript)
        except Exception as exc:
            if row["attempts"] >= MAX_ATTEMPTS:
                await self.store.fail(session_id, str(exc))
                self.delete_audio(session_id)  # final failure also cleans up
                _logger.error(f"Session {session_id} failed permanently", exc_info=exc)
                if self.on_failed is not None:
                    await self.on_failed(row, str(exc))
            else:
                delay = BACKOFF_BASE * (2 ** (row["attempts"] - 1))
                await self.store.requeue(session_id, str(exc), delay)
                _logger.warning(f"Session {session_id} attempt {row['attempts']} failed, retrying in {delay}s", exc_info=exc)

    @staticmethod
    def _load_manifest(session_dir: Path) -> dict | None:
        """Reads the manifest, keeping only tracks whose wav holds actual audio."""
        manifest_path = session_dir / MANIFEST_NAME
        if not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text())
        header_only = 44  # a bare wav header means the user never spoke
        return {
            user_id: meta
            for user_id, meta in manifest.items()
            if (session_dir / meta["file"]).exists() and (session_dir / meta["file"]).stat().st_size > header_only
        }

    async def _transcribe_session(self, session_id: uuid.UUID) -> str:
        session_dir = self.session_dir(session_id)
        manifest = await asyncio.to_thread(self._load_manifest, session_dir)
        if manifest is None:
            raise RuntimeError("session audio is gone (container recreated?), nothing left to transcribe")

        lines: list[tuple[float, str, str]] = []
        for meta in manifest.values():
            segments = await self.transcriber.transcribe(session_dir / meta["file"])
            boundaries = [tuple(b) for b in meta["boundaries"]]
            lines.extend(
                (align(boundaries, segment.start), meta["name"], segment.text) for segment in segments if segment.text
            )

        lines.sort(key=lambda line: line[0])
        if not lines:
            return "(nothing intelligible was said)"
        return "\n".join(f"[{int(wall // 60):02d}:{int(wall % 60):02d}] {name}: {text}" for wall, name, text in lines)
