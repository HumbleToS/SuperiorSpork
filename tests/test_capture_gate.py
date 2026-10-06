import json
from types import SimpleNamespace

from exts.utils.capture import BYTES_PER_SECOND, MANIFEST_NAME, ConsentGateSink, align

CHUNK = b"\x01\x02" * 960 * 2  # one 20ms 48khz stereo s16 frame


def fake_user(user_id: int, name: str = "someone") -> SimpleNamespace:
    return SimpleNamespace(id=user_id, display_name=name)


def fake_data() -> SimpleNamespace:
    return SimpleNamespace(pcm=CHUNK)


def test_non_included_audio_never_touches_disk(tmp_path) -> None:
    sink = ConsentGateSink(tmp_path / "s", included={1})
    sink.write(fake_user(1, "ok"), fake_data())
    sink.write(fake_user(2, "nope"), fake_data())
    sink.write(None, fake_data())
    sink.finalize()

    written = {p.name for p in (tmp_path / "s").iterdir()}
    assert written == {"1.wav", MANIFEST_NAME}


def test_optout_mid_session_stops_writes_immediately(tmp_path) -> None:
    included = {1, 2}
    sink = ConsentGateSink(tmp_path / "s", included)
    sink.write(fake_user(2), fake_data())

    included.discard(2)  # /optout mutates the shared set
    for _ in range(5):
        sink.write(fake_user(2), fake_data())
    sink.finalize()

    wav_header = 44  # standard pcm header; exactly one chunk made it to disk
    assert (tmp_path / "s" / "2.wav").stat().st_size == wav_header + len(CHUNK)


def test_consent_mid_session_starts_inclusion(tmp_path) -> None:
    included: set[int] = set()
    sink = ConsentGateSink(tmp_path / "s", included)
    sink.write(fake_user(3), fake_data())
    assert not (tmp_path / "s" / "3.wav").exists()

    included.add(3)  # consent button mutates the shared set
    sink.write(fake_user(3), fake_data())
    sink.finalize()
    assert (tmp_path / "s" / "3.wav").exists()


def test_boundaries_track_gaps_and_align(tmp_path, monkeypatch) -> None:
    clock = iter([100.0, 100.0, 100.02, 130.0])  # t0, write, write, write-after-gap
    monkeypatch.setattr("exts.utils.capture.time.monotonic", lambda: next(clock))

    sink = ConsentGateSink(tmp_path / "s", included={1})
    for _ in range(3):
        sink.write(fake_user(1), fake_data())
    sink.finalize()

    manifest = json.loads((tmp_path / "s" / MANIFEST_NAME).read_text())
    boundaries = [tuple(b) for b in manifest["1"]["boundaries"]]
    assert len(boundaries) == 2  # session start, then the 30s gap

    file_sec_at_gap = 2 * len(CHUNK) / BYTES_PER_SECOND
    assert align(boundaries, 0.0) == 0.0
    assert align(boundaries, file_sec_at_gap) == 30.0  # third chunk maps to wall 130 - t0


def test_finalize_is_idempotent(tmp_path) -> None:
    sink = ConsentGateSink(tmp_path / "s", included={1})
    sink.write(fake_user(1), fake_data())
    sink.finalize()
    sink.cleanup()  # voice-recv also calls cleanup; must not blow up or rewrite
    assert json.loads((tmp_path / "s" / MANIFEST_NAME).read_text())["1"]["file"] == "1.wav"
