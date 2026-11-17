"""Focused tests for the local voice audio contract, decode and STT bounds.

No model is downloaded here: model-dependent paths are exercised with fakes and
the real ``data/voice`` tree is never assumed to exist.
"""
from __future__ import annotations

import io
import sys
import threading
import wave

import numpy as np
import pytest

from backend.voice import local


@pytest.fixture(autouse=True)
def _clean_model_cache():
    local.reset_models()
    yield
    local.reset_models()


def _wav_bytes(
    *,
    seconds: float = 1.0,
    rate: int = 16_000,
    channels: int = 1,
    amp: float = 0.3,
    freq: float = 440.0,
) -> bytes:
    frames = int(rate * seconds)
    t = np.arange(frames) / rate
    samples = (amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    if channels == 2:
        samples = np.repeat(samples, 2)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def _opus_bytes(container_format: str = "webm") -> bytes:
    av = pytest.importorskip("av")
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format=container_format) as container:
        stream = container.add_stream("libopus", rate=48_000)
        stream.layout = "mono"
        samples = (np.sin(np.arange(48_000) / 48_000 * 2 * np.pi * 440) * 12_000).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = 48_000
        frame.pts = 0
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


def _aac_mp4_bytes() -> bytes:
    av = pytest.importorskip("av")
    buffer = io.BytesIO()
    with av.open(buffer, mode="w", format="mp4") as container:
        stream = container.add_stream("aac", rate=48_000)
        stream.layout = "mono"
        samples = (np.sin(np.arange(48_000) / 48_000 * 2 * np.pi * 440) * 0.3).astype(np.float32)
        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format="fltp", layout="mono"
        )
        frame.sample_rate = 48_000
        frame.pts = 0
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


class _Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeWhisper:
    def __init__(self, text: str = "olá", *, gate: threading.Event | None = None) -> None:
        self.text = text
        self.gate = gate
        self.kwargs: dict = {}

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        if self.gate is not None:
            self.gate.wait(5)
        return [_Segment(self.text)], None


# --- Decode contract ------------------------------------------------------


def test_decode_mono_wav_returns_float32_and_duration():
    audio, duration = local.decode_audio(_wav_bytes(seconds=1.0))
    assert duration == pytest.approx(1.0, abs=0.02)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert float(np.max(np.abs(audio))) > local.SILENCE_PEAK


def test_decode_resamples_stereo_44100_to_mono_16k():
    audio, duration = local.decode_audio(_wav_bytes(seconds=1.0, rate=44_100, channels=2))
    assert duration == pytest.approx(1.0, abs=0.02)
    assert audio.ndim == 1
    assert len(audio) == pytest.approx(local.SAMPLE_RATE, abs=50)


def test_decode_rejects_empty_bytes():
    with pytest.raises(local.EmptyAudioError):
        local.decode_audio(b"")


def test_decode_rejects_garbage():
    with pytest.raises(local.InvalidAudioError):
        local.decode_audio(b"not audio at all")


def test_decode_rejects_header_without_audio_stream():
    # A RIFF/WAVE header that declares no audio payload decodes to nothing.
    with pytest.raises(local.EmptyAudioError):
        local.decode_audio(_wav_bytes(seconds=0.01)[:44])


def test_decode_rejects_silence():
    with pytest.raises(local.EmptyAudioError) as excinfo:
        local.decode_audio(_wav_bytes(seconds=0.5, amp=0.0))
    assert excinfo.value.code == "empty_audio"


def test_decode_rejects_too_long(monkeypatch):
    monkeypatch.setattr(local, "MAX_SAMPLES", 1_000)
    with pytest.raises(local.AudioTooLongError) as excinfo:
        local.decode_audio(_wav_bytes(seconds=0.5))
    assert excinfo.value.status == 413


def test_decode_truncated_half_reports_shorter_duration():
    full = _wav_bytes(seconds=1.0)
    _, duration = local.decode_audio(full[: len(full) // 2])
    assert 0.3 < duration < 0.7


def test_decode_opus_webm_when_encoder_available():
    audio, duration = local.decode_audio(_opus_bytes("webm"))
    assert duration == pytest.approx(1.0, abs=0.1)
    assert len(audio) > 0


def test_decode_opus_ogg_when_encoder_available():
    audio, duration = local.decode_audio(_opus_bytes("ogg"))
    assert duration == pytest.approx(1.0, abs=0.1)
    assert len(audio) > 0


def test_decode_aac_mp4_when_encoder_available():
    audio, duration = local.decode_audio(_aac_mp4_bytes())
    assert duration == pytest.approx(1.0, abs=0.1)
    assert len(audio) > 0


def test_decode_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", None)
    with pytest.raises(local.DependencyMissingError) as excinfo:
        local.decode_audio(b"whatever")
    assert excinfo.value.status == 503


# --- STT ------------------------------------------------------------------


def test_transcribe_rejects_bad_model_and_device():
    data = _wav_bytes()
    with pytest.raises(local.InvalidArgumentError):
        local.transcribe(data, model="large")
    with pytest.raises(local.InvalidArgumentError):
        local.transcribe(data, model="base", device="tpu")


def test_transcribe_model_missing(monkeypatch):
    monkeypatch.setattr(local, "_stt_installed", lambda name: False)
    with pytest.raises(local.ModelMissingError) as excinfo:
        local.transcribe(_wav_bytes(), model="base")
    assert excinfo.value.code == "model_missing"


def test_transcribe_cuda_unavailable_is_incompatible(monkeypatch):
    monkeypatch.setattr(local, "_cuda_available", lambda: False)
    monkeypatch.setattr(local, "_stt_installed", lambda name: True)
    with pytest.raises(local.IncompatibleModelError) as excinfo:
        local.transcribe(_wav_bytes(), model="base", device="cuda")
    assert excinfo.value.code == "model_incompatible"


def test_transcribe_uses_fake_model_and_reports_pt(monkeypatch):
    fake = _FakeWhisper("bom dia")
    monkeypatch.setattr(local, "_stt_installed", lambda name: True)
    monkeypatch.setattr(local, "_load_stt_model", lambda model, device: fake)

    result = local.transcribe(_wav_bytes(seconds=0.5), model="base", device="cpu")

    assert result["text"] == "bom dia"
    assert result["language"] == "pt"
    assert result["variant"] == "pt"
    assert result["regional"] == "pt-PT-não-garantido"
    assert result["model"] == "base"
    assert result["device"] == "cpu"
    assert fake.kwargs["language"] == "pt"
    assert fake.kwargs["vad_filter"] is True


def test_transcribe_timeout_when_server_busy(monkeypatch):
    monkeypatch.setattr(local, "_stt_installed", lambda name: True)
    monkeypatch.setattr(local, "_load_stt_model", lambda model, device: _FakeWhisper())
    local._stt_lock.acquire()
    try:
        with pytest.raises(local.ProcessingTimeoutError) as excinfo:
            local.transcribe(_wav_bytes(), model="base", timeout=0.05)
        assert excinfo.value.code == "timeout"
        assert excinfo.value.status == 504
    finally:
        local._stt_lock.release()


def test_transcribe_maps_load_memory_error(monkeypatch):
    def boom(model, device):
        raise MemoryError("allocation failed")

    monkeypatch.setattr(local, "_stt_installed", lambda name: True)
    monkeypatch.setattr(local, "_load_stt_model", boom)
    with pytest.raises(local.OutOfMemoryError) as excinfo:
        local.transcribe(_wav_bytes(), model="base")
    assert excinfo.value.status == 507


def test_transcribe_maps_incompatible_compute_type(monkeypatch):
    def boom(model, device):
        raise RuntimeError("unsupported compute type float16 for this device")

    monkeypatch.setattr(local, "_stt_installed", lambda name: True)
    monkeypatch.setattr(local, "_load_stt_model", boom)
    with pytest.raises(local.IncompatibleModelError):
        local.transcribe(_wav_bytes(), model="base")


def test_budget_rejects_model_larger_than_gpu_allowance(monkeypatch):
    monkeypatch.setattr(local, "_gpu_total_mb", lambda: 1024)
    with pytest.raises(local.OutOfMemoryError):
        local._check_budget("cuda", "medium")


def test_cuda_missing_library_is_incompatible_not_oom():
    with pytest.raises(local.IncompatibleModelError) as excinfo:
        local._raise_mapped(
            RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"),
            source="faster-whisper",
        )
    assert excinfo.value.code == "model_incompatible"


def test_cuda_out_of_memory_still_maps_to_oom():
    with pytest.raises(local.OutOfMemoryError):
        local._raise_mapped(RuntimeError("CUDA out of memory"), source="faster-whisper")


def test_missing_model_message_maps_to_model_missing():
    with pytest.raises(local.ModelMissingError):
        local._raise_mapped(
            RuntimeError("model.bin does not exist"), source="faster-whisper"
        )


def test_error_codes_and_status_are_explicit():
    assert local.InvalidAudioError("x").status == 400
    assert local.UnsupportedFormatError("x").status == 415
    assert local.AudioTooLongError("x").status == 413
    assert local.ModelMissingError("x").status == 503
    assert local.DependencyMissingError("x").status == 503
    assert local.IncompatibleModelError("x").status == 503
    assert local.OutOfMemoryError("x").status == 507
    assert local.ProcessingTimeoutError("x").status == 504


def test_status_contract_is_local_and_honest_about_pt_pt(monkeypatch):
    monkeypatch.setattr(local, "_stt_installed", lambda name: False)
    monkeypatch.setattr(local, "_voices", lambda: {})
    info = local.status()

    assert info["local_only"] is True
    assert info["network"] == "none"
    assert info["contract"]["input"]["sample_rate"] == 16_000
    assert info["contract"]["input"]["channels"] == 1
    assert info["contract"]["input"]["max_duration_seconds"] == 60.0
    assert info["stt"]["language"] == "pt"
    assert info["stt"]["regional_variant"] is None
    assert "pt-PT" in info["stt"]["regional_note"]
    assert info["tts"]["ready"] is False
    assert info["budget"]["tts_use_cuda"] is False
    assert info["budget"]["stt_cpu_threads"] <= 4