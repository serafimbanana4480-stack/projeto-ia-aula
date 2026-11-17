"""Focused tests for local Piper synthesis, WAV validation and dependency errors."""
from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from backend.voice import local


@pytest.fixture(autouse=True)
def _clean_model_cache():
    local.reset_models()
    yield
    local.reset_models()


class _FakePiper:
    def __init__(self, *, amp: float = 0.3, frames: int = 16_000, rate: int = 22_050) -> None:
        self.amp = amp
        self.frames = frames
        self.rate = rate
        self.texts: list[str] = []
        self.syn_config = None

    def synthesize_wav(self, text, wav, syn_config=None):
        self.texts.append(text)
        self.syn_config = syn_config
        t = np.arange(self.frames) / self.rate
        samples = (self.amp * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(self.rate)
        wav.writeframes(samples.tobytes())


def _peak(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as wav:
        raw = wav.readframes(wav.getnframes())
    values = np.frombuffer(raw, dtype="<i2")
    return int(np.max(np.abs(values))) if values.size else 0


def _patch_voice(monkeypatch, fake):
    monkeypatch.setattr(local, "_voices", lambda: {"pt_PT-tugão-medium": Path("pt_PT-tugão-medium.onnx")})
    monkeypatch.setattr(local, "_load_tts_model", lambda name: fake)


def test_synthesize_rejects_empty_and_whitespace():
    with pytest.raises(local.InvalidArgumentError):
        local.synthesize("")
    with pytest.raises(local.InvalidArgumentError):
        local.synthesize("   ")


def test_synthesize_rejects_too_long_text():
    with pytest.raises(local.InvalidArgumentError):
        local.synthesize("x" * (local.MAX_TEXT_CHARS + 1))


def test_synthesize_rejects_bad_speed():
    with pytest.raises(local.InvalidArgumentError):
        local.synthesize("olá", speed=0.1)
    with pytest.raises(local.InvalidArgumentError):
        local.synthesize("olá", speed=2.0)


def test_synthesize_requires_installed_voice(monkeypatch):
    monkeypatch.setattr(local, "_voices", lambda: {})
    with pytest.raises(local.ModelMissingError) as excinfo:
        local.synthesize("olá")
    assert excinfo.value.code == "model_missing"


def test_synthesize_rejects_unknown_voice(monkeypatch):
    monkeypatch.setattr(local, "_voices", lambda: {"pt_PT-tugão-medium": Path("x")})
    with pytest.raises(local.ModelMissingError):
        local.synthesize("olá", voice="outra")


def test_synthesize_returns_valid_non_silent_wav(monkeypatch):
    fake = _FakePiper()
    _patch_voice(monkeypatch, fake)

    data = local.synthesize("olá mundo", voice=None, speed=1.25)

    assert data.startswith(b"RIFF")
    assert b"WAVE" in data[:12]
    assert _peak(data) > int(local.SILENCE_PEAK * 32767)
    with wave.open(io.BytesIO(data), "rb") as wav:
        assert wav.getnframes() > 0
        assert wav.getframerate() == 22_050
    assert fake.texts == ["olá mundo"]
    assert fake.syn_config.length_scale == pytest.approx(1.0 / 1.25)


def test_synthesize_rejects_silent_output(monkeypatch):
    _patch_voice(monkeypatch, _FakePiper(amp=0.0))
    with pytest.raises(local.EmptyAudioError) as excinfo:
        local.synthesize("olá")
    assert excinfo.value.code == "empty_audio"


def test_synthesize_missing_dependency(monkeypatch):
    monkeypatch.setattr(local, "_voices", lambda: {"pt_PT-x": Path("x")})
    monkeypatch.setitem(sys.modules, "piper", None)
    with pytest.raises(local.DependencyMissingError) as excinfo:
        local.synthesize("olá")
    assert excinfo.value.status == 503


def test_synthesize_maps_memory_error(monkeypatch):
    def boom(name):
        raise MemoryError("allocation failed")

    monkeypatch.setattr(local, "_voices", lambda: {"pt_PT-x": Path("x")})
    monkeypatch.setattr(local, "_load_tts_model", boom)
    with pytest.raises(local.OutOfMemoryError):
        local.synthesize("olá")


def test_synthesize_timeout_when_server_busy(monkeypatch):
    monkeypatch.setattr(local, "_voices", lambda: {"pt_PT-x": Path("x")})
    monkeypatch.setattr(local, "_load_tts_model", lambda name: _FakePiper())
    local._tts_lock.acquire()
    try:
        with pytest.raises(local.ProcessingTimeoutError) as excinfo:
            local.synthesize("olá", timeout=0.05)
        assert excinfo.value.status == 504
    finally:
        local._tts_lock.release()


def test_status_reports_pt_pt_regional_voice(monkeypatch):
    path = local.ROOT / "tts" / "pt" / "pt_PT" / "tugão" / "medium" / "pt_PT-tugão-medium.onnx"
    monkeypatch.setattr(local, "_voices", lambda: {"pt_PT-tugão-medium": path})
    info = local.status()

    voices = info["tts"]["voices"]
    assert voices[0]["id"] == "pt_PT-tugão-medium"
    assert voices[0]["language"] == "pt-PT"
    assert voices[0]["regional"] == "pt_PT"
    assert voices[0]["path"].endswith("pt_PT-tugão-medium.onnx")
    assert ".." not in voices[0]["path"]