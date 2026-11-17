"""Live local-model checks. Opt-in so the default suite stays fast.

Run explicitly (no download; local files only):

    $env:NEXUS_VOICE_RUN_MODEL_TESTS = "1"
    .venv\\Scripts\\python.exe -m pytest backend/tests/voice/test_local_models_live.py -q
"""
from __future__ import annotations

import io
import os
import time
import wave

import numpy as np
import pytest

from backend.voice import local

pytestmark = pytest.mark.skipif(
    os.environ.get("NEXUS_VOICE_RUN_MODEL_TESTS") != "1",
    reason="set NEXUS_VOICE_RUN_MODEL_TESTS=1 to exercise the real local models",
)


def _peak(data: bytes) -> int:
    with wave.open(io.BytesIO(data), "rb") as wav:
        raw = wav.readframes(wav.getnframes())
    values = np.frombuffer(raw, dtype="<i2")
    return int(np.max(np.abs(values))) if values.size else 0


def test_live_tts_and_stt_cold_warm_roundtrip():
    if not local._stt_installed("small") or not local._voices():
        pytest.skip("local voice models are not installed")

    text = "Bom dia. Este é um teste de voz em português de Portugal."

    tts_cold_start = time.perf_counter()
    wav = local.synthesize(text)
    tts_cold = time.perf_counter() - tts_cold_start

    tts_warm_start = time.perf_counter()
    wav_warm = local.synthesize(text)
    tts_warm = time.perf_counter() - tts_warm_start

    assert wav.startswith(b"RIFF")
    assert _peak(wav) > int(local.SILENCE_PEAK * 32767)
    assert len(wav_warm) > 0

    stt_cold_start = time.perf_counter()
    cold = local.transcribe(wav, model="small", device="cpu")
    stt_cold = time.perf_counter() - stt_cold_start

    stt_warm_start = time.perf_counter()
    warm = local.transcribe(wav, model="small", device="cpu")
    stt_warm = time.perf_counter() - stt_warm_start

    assert cold["text"].strip()
    assert cold["language"] == "pt"
    assert cold["regional"] == "pt-PT-não-garantido"
    assert warm["text"].strip()

    print(
        f"\n[voice-live] tts cold={tts_cold:.3f}s warm={tts_warm:.3f}s "
        f"stt cold={stt_cold:.3f}s warm={stt_warm:.3f}s "
        f"text={cold['text']!r}"
    )