from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import config

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class Segment:
    start: float
    end: float
    text: str


class TranscriptionProvider(Protocol):
    async def transcribe(self, wav_path: Path) -> list[Segment]: ...


class FasterWhisperProvider:
    """Local faster-whisper on cpu. The model loads once, lazily, off the event loop."""

    def __init__(self) -> None:
        self._model: Any = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _load() -> Any:
        from faster_whisper import WhisperModel  # heavy import, deferred on purpose

        return WhisperModel(
            getattr(config, "WHISPER_MODEL", "small"),
            device="cpu",
            compute_type="int8",
            cpu_threads=getattr(config, "WHISPER_THREADS", 2),
            download_root=getattr(config, "MODELS_DIR", "./models"),
        )

    async def transcribe(self, wav_path: Path) -> list[Segment]:
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)

        def run() -> list[Segment]:
            segments, _info = self._model.transcribe(str(wav_path), vad_filter=True)
            return [Segment(s.start, s.end, s.text.strip()) for s in segments]

        return await asyncio.to_thread(run)


class HostedProvider:
    """Stub for a hosted transcription api, kept behind the same interface for later."""

    async def transcribe(self, wav_path: Path) -> list[Segment]:
        raise NotImplementedError("hosted transcription is not wired up yet")
