from __future__ import annotations

import json
import time
import wave
from typing import TYPE_CHECKING

from discord.ext import voice_recv

if TYPE_CHECKING:
    from pathlib import Path

    import discord

SAMPLE_RATE = 48000
CHANNELS = 2
SAMPLE_WIDTH = 2  # 16-bit pcm
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH
GAP_THRESHOLD = 0.5  # seconds of quiet before a new alignment boundary
MANIFEST_NAME = "tracks.json"


def align(boundaries: list[tuple[float, float]], file_seconds: float) -> float:
    """Maps a position in a compact speech-only track back to session wall-clock seconds."""
    wall = file_seconds
    for file_sec, wall_sec in boundaries:
        if file_sec > file_seconds:
            break
        wall = wall_sec + (file_seconds - file_sec)
    return wall


class UserTrack:
    """One speaker's compact wav plus the boundaries that map it back to wall-clock time."""

    def __init__(self, path: Path, display_name: str) -> None:
        self.path = path
        self.display_name = display_name
        self.boundaries: list[tuple[float, float]] = []
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(CHANNELS)
        self._wav.setsampwidth(SAMPLE_WIDTH)
        self._wav.setframerate(SAMPLE_RATE)
        self._bytes_written = 0
        self._next_expected_wall: float | None = None

    @property
    def file_seconds(self) -> float:
        return self._bytes_written / BYTES_PER_SECOND

    def write(self, pcm: bytes, wall: float) -> None:
        if self._next_expected_wall is None or wall - self._next_expected_wall > GAP_THRESHOLD:
            self.boundaries.append((self.file_seconds, wall))
        self._wav.writeframes(pcm)
        self._bytes_written += len(pcm)
        self._next_expected_wall = wall + len(pcm) / BYTES_PER_SECOND

    def close(self) -> None:
        self._wav.close()


class ConsentGateSink(voice_recv.AudioSink):
    """Per-user wav writer that drops packets from anyone not in the include set.

    The include set is shared with the Voice cog and mutated live by consent
    clicks and optin/optout, so the gate is enforced at capture: audio from a
    user who has not consented, or who opted out, never touches a buffer or
    the disk. write() runs on the receive thread — nothing async in here.
    """

    def __init__(self, session_dir: Path, included: set[int]) -> None:
        super().__init__()
        self.session_dir = session_dir
        self.included = included
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._tracks: dict[int, UserTrack] = {}
        self._t0 = time.monotonic()
        self._finalized = False

    def wants_opus(self) -> bool:
        return False

    def write(self, user: discord.User | discord.Member | None, data: voice_recv.VoiceData) -> None:
        if user is None or user.id not in self.included:
            return
        track = self._tracks.get(user.id)
        if track is None:
            track = UserTrack(self.session_dir / f"{user.id}.wav", user.display_name)
            self._tracks[user.id] = track
        track.write(data.pcm, time.monotonic() - self._t0)

    def cleanup(self) -> None:
        self.finalize()

    def finalize(self) -> None:
        """Closes every track and writes the manifest the pipeline reads. Idempotent."""
        if self._finalized:
            return
        self._finalized = True
        manifest = {}
        for user_id, track in self._tracks.items():
            track.close()
            manifest[str(user_id)] = {
                "file": track.path.name,
                "name": track.display_name,
                "boundaries": track.boundaries,
            }
        (self.session_dir / MANIFEST_NAME).write_text(json.dumps(manifest))
