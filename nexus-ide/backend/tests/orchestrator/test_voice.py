"""Voice API limits, typed failures and the local-only contract."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.middleware.auth import require_auth
from backend.orchestrator.routes import voice
from backend.voice import local


def client() -> TestClient:
    app = FastAPI()
    app.include_router(voice.router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: {"id": "test"}
    return TestClient(app)


def test_transcription_checks_input_and_returns_recognition(monkeypatch):
    monkeypatch.setattr(
        voice.local,
        "transcribe",
        lambda data, model, device, **kwargs: {
            "text": "olá",
            "language": "pt",
            "duration": 1.0,
        },
    )
    api = client()
    assert api.post("/api/voice/transcribe", content=b"audio").status_code == 415
    assert (
        api.post(
            "/api/voice/transcribe", content=b"", headers={"Content-Type": "audio/webm"}
        ).status_code
        == 400
    )
    response = api.post(
        "/api/voice/transcribe?model=base&device=cpu",
        content=b"audio",
        headers={"Content-Type": "audio/webm;codecs=opus"},
    )
    assert response.status_code == 200
    assert response.json()["text"] == "olá"


def test_voice_limit_and_missing_model(monkeypatch):
    api = client()
    monkeypatch.setattr(voice, "MAX_AUDIO_BYTES", 3)
    assert (
        api.post(
            "/api/voice/transcribe", content=b"1234", headers={"Content-Type": "audio/wav"}
        ).status_code
        == 413
    )

    def missing(*args, **kwargs):
        raise RuntimeError("Modelo não instalado")

    monkeypatch.setattr(voice.local, "transcribe", missing)
    response = api.post(
        "/api/voice/transcribe", content=b"123", headers={"Content-Type": "audio/wav"}
    )
    assert response.status_code == 503
    assert "não instalado" in response.json()["detail"]


def test_synthesis_returns_wav_and_limits_text(monkeypatch):
    monkeypatch.setattr(
        voice.local, "synthesize", lambda text, name, speed, **kwargs: b"RIFFaudio"
    )
    api = client()
    response = api.post("/api/voice/synthesize", json={"text": "olá", "speed": 1.0})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert api.post("/api/voice/synthesize", json={"text": "x" * 3001}).status_code == 422


def test_synthesis_rejects_whitespace_text():
    api = client()
    response = api.post("/api/voice/synthesize", json={"text": "   ", "speed": 1.0})
    assert response.status_code == 400


def test_transcribe_maps_typed_errors(monkeypatch):
    cases = [
        (local.EmptyAudioError("silêncio"), 400, "empty_audio"),
        (local.UnsupportedFormatError("formato"), 415, "unsupported_format"),
        (local.AudioTooLongError("longo"), 413, "audio_too_long"),
        (local.ModelMissingError("modelo"), 503, "model_missing"),
        (local.DependencyMissingError("dependência"), 503, "dependency_missing"),
        (local.IncompatibleModelError("incompatível"), 503, "model_incompatible"),
        (local.OutOfMemoryError("oom"), 507, "out_of_memory"),
        (local.ProcessingTimeoutError("timeout"), 504, "timeout"),
    ]
    api = client()
    for error, status, code in cases:
        monkeypatch.setattr(voice.local, "transcribe", lambda *a, _e=error, **k: (_ for _ in ()).throw(_e))
        response = api.post(
            "/api/voice/transcribe", content=b"audio", headers={"Content-Type": "audio/wav"}
        )
        assert response.status_code == status, code
        assert response.headers["x-voice-error-code"] == code


def test_synthesis_maps_model_missing(monkeypatch):
    monkeypatch.setattr(
        voice.local,
        "synthesize",
        lambda *a, **k: (_ for _ in ()).throw(local.ModelMissingError("voz")),
    )
    api = client()
    response = api.post("/api/voice/synthesize", json={"text": "olá", "speed": 1.0})
    assert response.status_code == 503
    assert response.headers["x-voice-error-code"] == "model_missing"


def test_status_reports_contract_without_models(monkeypatch):
    monkeypatch.setattr(voice.local, "_stt_installed", lambda name: False)
    monkeypatch.setattr(voice.local, "_voices", lambda: {})
    api = client()
    response = api.get("/api/voice/status")
    assert response.status_code == 200
    body = response.json()
    assert body["local_only"] is True
    assert body["network"] == "none"
    assert body["contract"]["input"]["sample_rate"] == 16_000
    assert body["contract"]["input"]["channels"] == 1
    assert body["stt"]["language"] == "pt"
    assert body["stt"]["regional_variant"] is None


def test_default_stt_prefers_small_and_falls_back_to_base(monkeypatch):
    monkeypatch.setattr(voice.local, "_stt_installed", lambda name: name == "small")
    assert voice.local.default_stt_model() == "small"
    monkeypatch.setattr(voice.local, "_stt_installed", lambda name: name == "base")
    assert voice.local.default_stt_model() == "base"