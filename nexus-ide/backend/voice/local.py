"""Local-only, bounded speech inference.

Design contract
---------------
* Audio is processed in-process only. Raw audio is never forwarded to a remote
  service and models are never downloaded as part of a request.
* Input is bounded before decode: ``MAX_AUDIO_BYTES`` and
  ``MAX_DURATION_SECONDS``. Decode always resamples to
  mono / s16 / 16 kHz (the format faster-whisper expects).
* Failures are typed (:class:`VoiceError` subclasses) so the HTTP layer can map
  them to stable status codes and machine-readable ``code`` values instead of
  leaking tracebacks or native library messages.
* STT and TTS keep one model each in a process-wide cache. The caches are
  guarded so switching model or device releases the previous model first.
* CPU is the safe default. CUDA is opt-in; Piper always runs on CPU so that a
  voice conversation never needs STT + TTS + LLM resident in VRAM at once.
"""

from __future__ import annotations

import importlib.util
import io
import os
import threading
import time
import wave
from pathlib import Path
from typing import Any

ROOT = Path(
    os.environ.get("NEXUS_VOICE_MODELS_DIR", Path(__file__).resolve().parents[2] / "data" / "voice")
)

# --- Input contract -------------------------------------------------------
SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_FORMAT = "s16"
MAX_DURATION_SECONDS = 60.0
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SAMPLES = int(SAMPLE_RATE * MAX_DURATION_SECONDS)
MAX_TEXT_CHARS = 3000
MIN_SPEED = 0.6
MAX_SPEED = 1.5
DEFAULT_TRANSCRIBE_TIMEOUT = 120.0
SILENCE_PEAK = 0.003  # ~ -50 dBFS; below this a clip is treated as silence.

SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "audio/webm",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/ogg",
        "audio/mp4",
        "audio/m4a",
        "audio/aac",
        "audio/mpeg",
        "audio/mp3",
        "video/webm",
    }
)

# --- Conservative resource budget (RTX 3060 Ti 8 GB + 32 GB RAM) ----------
GPU_TOTAL_MB = 8192
GPU_RESERVE_MB = 2048  # display, driver and any concurrent LLM headroom
CPU_THREADS = 4
STT_VRAM_ESTIMATE_MB = {"tiny": 400, "base": 800, "small": 1600, "medium": 3000}

STT_MODELS = ("tiny", "base", "small", "medium")
DEFAULT_VOICE = "pt_PT-tugão-medium"

_stt_lock = threading.Lock()
_tts_lock = threading.Lock()
_stt_key: tuple[str, str] | None = None
_stt_model: Any = None
_tts_key: str | None = None
_tts_model: Any = None


# --- Typed errors ---------------------------------------------------------


class VoiceError(Exception):
    """Base class for expected, user-facing voice failures."""

    code = "voice_error"
    status = 503

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class InvalidArgumentError(VoiceError):
    code = "invalid_argument"
    status = 400


class InvalidAudioError(VoiceError):
    code = "invalid_audio"
    status = 400


class UnsupportedFormatError(VoiceError):
    code = "unsupported_format"
    status = 415


class EmptyAudioError(VoiceError):
    """Decoded to nothing, or to silence only."""

    code = "empty_audio"
    status = 400


class AudioTooLongError(VoiceError):
    code = "audio_too_long"
    status = 413


class ModelMissingError(VoiceError):
    code = "model_missing"
    status = 503


class DependencyMissingError(VoiceError):
    code = "dependency_missing"
    status = 503


class IncompatibleModelError(VoiceError):
    code = "model_incompatible"
    status = 503


class OutOfMemoryError(VoiceError):
    code = "out_of_memory"
    status = 507


class ProcessingTimeoutError(VoiceError):
    code = "timeout"
    status = 504


# --- Helpers --------------------------------------------------------------


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _stt_path(name: str) -> Path:
    return ROOT / "stt" / name


def _stt_installed(name: str) -> bool:
    path = _stt_path(name)
    return all(
        (path / file).is_file()
        for file in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
    )


def default_stt_model() -> str:
    """Prefer the better multilingual model, retaining a lightweight fallback."""
    return next((name for name in ("small", "base", "tiny", "medium") if _stt_installed(name)), "base")


def _voices() -> dict[str, Path]:
    """Only installed pt-PT voices by name; never accept paths from the client."""
    directory = ROOT / "tts"
    if not directory.is_dir():
        return {}
    found: dict[str, Path] = {}
    for path in directory.rglob("*.onnx"):
        if not path.name.lower().startswith("pt_pt-"):
            continue
        if path.with_suffix(".onnx.json").is_file():
            found[path.stem] = path
    return found


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _cuda_available() -> bool:
    try:
        import ctranslate2  # type: ignore[import-untyped]

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False


def _gpu_total_mb() -> int:
    raw = os.environ.get("NEXUS_VOICE_GPU_TOTAL_MB")
    if raw and raw.isdigit():
        return int(raw)
    return GPU_TOTAL_MB


def _stt_vram_estimate(model: str) -> int:
    return STT_VRAM_ESTIMATE_MB.get(model, 0)


def resource_budget(device: str = "cpu", model: str | None = None) -> dict[str, Any]:
    """Return the conservative budget used for a transcription attempt."""
    target = model or default_stt_model()
    total = _gpu_total_mb()
    available = max(total - GPU_RESERVE_MB, 0)
    return {
        "gpu_total_mb": total,
        "gpu_reserve_mb": GPU_RESERVE_MB,
        "gpu_budget_mb": available,
        "stt_device": device,
        "stt_compute_type": "int8" if device == "cpu" else "float16",
        "stt_vram_estimate_mb": _stt_vram_estimate(target),
        "stt_cpu_threads": CPU_THREADS,
        "tts_device": "cpu",
        "tts_use_cuda": False,
        "concurrent_models": "stt (cpu or cuda) + tts (cpu); LLM not loaded by voice",
        "policy": "if cuda OOM or contention, retry with device=cpu",
    }


def _check_budget(device: str, model: str) -> None:
    if device != "cuda":
        return
    budget = _gpu_total_mb() - GPU_RESERVE_MB
    estimate = _stt_vram_estimate(model)
    if estimate > budget:
        raise OutOfMemoryError(
            f"O modelo '{model}' pode não caber no orçamento de VRAM "
            f"({estimate} MB > {budget} MB). Usa device=cpu ou um modelo menor."
        )


def _is_silent(audio: Any) -> bool:
    return audio.size == 0 or float(abs(audio).max()) < SILENCE_PEAK


def _lock_or_timeout(lock: threading.Lock, timeout: float | None) -> None:
    """Acquire a model lock, converting a busy server into a 504 instead of a hang."""
    if timeout is None:
        lock.acquire()
        return
    if timeout <= 0:
        raise ProcessingTimeoutError("Tempo limite de atendimento excedido antes de iniciar.")
    if not lock.acquire(timeout=timeout):
        raise ProcessingTimeoutError("O servidor de voz está ocupado. Tenta novamente.")


def _raise_mapped(exc: BaseException, *, source: str) -> None:
    """Map native/loader failures to typed errors with sanitised messages."""
    if isinstance(exc, VoiceError):
        raise exc
    if isinstance(exc, MemoryError):
        raise OutOfMemoryError(
            "Memória esgotada ao carregar o modelo. Usa device=cpu ou um modelo menor."
        ) from exc
    text = str(exc).lower()
    # CUDA can be reported as present while cublas/cudnn DLLs are missing. That is
    # an incompatibility, not an out-of-memory condition.
    cuda_library_problem = any(
        marker in text for marker in ("cublas", "cudnn", "cudart", "nvcuda", "cufft")
    ) and any(
        marker in text
        for marker in ("not found", "cannot be loaded", "no such file", "dll", "load")
    )
    if cuda_library_problem:
        raise IncompatibleModelError(
            "CUDA/cuDNN não está configurado (bibliotecas em falta). Usa device=cpu."
        ) from exc
    if any(
        marker in text
        for marker in (
            "out of memory",
            "cudaerrormemoryallocation",
            "cublas_status_alloc_failed",
            "cudnn_status_alloc_failed",
            "insufficient memory",
        )
    ):
        raise OutOfMemoryError(
            "Memória de vídeo (VRAM) esgotada. Usa device=cpu ou um modelo menor."
        ) from exc
    if any(
        marker in text
        for marker in ("no such file", "does not exist", "cannot identify", "model.bin")
    ):
        raise ModelMissingError("Modelo local não encontrado ou incompleto.") from exc
    if any(
        marker in text
        for marker in (
            "compute type",
            "float16",
            "unsupported",
            "cuda",
            "device",
            "version",
            "capability",
        )
    ):
        raise IncompatibleModelError(
            f"Modelo ou dispositivo incompatível ({source}). Usa device=cpu."
        ) from exc
    raise RuntimeError(f"Falha no motor local ({source}).") from exc


# --- Audio decode ---------------------------------------------------------


def decode_audio(data: bytes) -> tuple[Any, float]:
    """Decode arbitrary local audio to mono s16 PCM at 16 kHz.

    Returns ``(samples, duration_seconds)`` where ``samples`` is a float32
    numpy array in ``[-1, 1)``. Raises typed :class:`VoiceError` on empty,
    invalid, unsupported, over-long or silent input.
    """
    if not data:
        raise EmptyAudioError("Gravação vazia.")
    if len(data) > MAX_AUDIO_BYTES:
        raise AudioTooLongError(f"A gravação excede {MAX_AUDIO_BYTES // (1024 * 1024)} MB.")
    try:
        import av
        import numpy as np
    except ImportError as exc:
        raise DependencyMissingError(
            "Motor de áudio (PyAV) não instalado. Instala o extra voice."
        ) from exc

    chunks: list[Any] = []
    samples = 0
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            if not container.streams.audio:
                raise InvalidAudioError("O ficheiro não contém uma faixa de áudio.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples += converted.samples
                    if samples > MAX_SAMPLES:
                        raise AudioTooLongError(
                            f"A gravação excede {int(MAX_DURATION_SECONDS)} segundos."
                        )
                    chunks.append(converted.to_ndarray().reshape(-1))
    except VoiceError:
        raise
    except Exception as exc:
        raise InvalidAudioError("Áudio inválido ou formato não suportado.") from exc

    if not chunks:
        raise EmptyAudioError("A gravação não contém áudio decodificado.")

    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    duration = len(audio) / SAMPLE_RATE
    if duration <= 0:
        raise EmptyAudioError("A gravação não contém áudio decodificado.")
    if _is_silent(audio):
        raise EmptyAudioError("A gravação está em silêncio.")
    return audio, duration


# --- STT ------------------------------------------------------------------


def _load_stt_model(model: str, device: str) -> Any:
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
    except ImportError as exc:
        raise DependencyMissingError(
            "Motor STT não instalado. Instala o extra voice."
        ) from exc
    _check_budget(device, model)
    compute_type = "int8" if device == "cpu" else "float16"
    try:
        return WhisperModel(
            str(_stt_path(model)),
            device=device,
            compute_type=compute_type,
            local_files_only=True,
            cpu_threads=CPU_THREADS,
            num_workers=1,
        )
    except Exception as exc:
        _raise_mapped(exc, source="faster-whisper")


def transcribe(
    data: bytes,
    model: str | None = None,
    device: str = "cpu",
    *,
    timeout: float | None = DEFAULT_TRANSCRIBE_TIMEOUT,
) -> dict[str, Any]:
    """Decode and transcribe one turn, offline, with a bounded input contract.

    ``language`` is always ``pt``: faster-whisper only exposes the generic
    ISO-639-1 code. It does *not* guarantee a European (PT-PT) variant, so the
    result reports ``variant`` honestly rather than claiming pt-PT.
    """
    if model is None:
        model = default_stt_model()
    if model not in STT_MODELS:
        raise InvalidArgumentError("Modelo STT inválido.")
    if device not in ("cpu", "cuda"):
        raise InvalidArgumentError("Dispositivo inválido. Usa 'cpu' ou 'cuda'.")
    if device == "cuda" and not _cuda_available():
        raise IncompatibleModelError("CUDA não está disponível. Usa device=cpu.")
    if not _stt_installed(model):
        raise ModelMissingError(f"Modelo STT '{model}' não instalado. Consulta a configuração de voz.")

    started = time.monotonic()
    audio, duration = decode_audio(data)
    if timeout is not None and time.monotonic() - started > timeout:
        raise ProcessingTimeoutError("Tempo limite de transcrição excedido.")

    global _stt_key, _stt_model
    _lock_or_timeout(_stt_lock, timeout)
    try:
        key = (model, device)
        if _stt_key != key:
            # Release the previous model before loading another into RAM/VRAM.
            _stt_model = None
            _stt_key = None
            _stt_model = _load_stt_model(model, device)
            _stt_key = key
        segments, _ = _stt_model.transcribe(
            audio,
            language="pt",
            vad_filter=True,
            beam_size=3,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except VoiceError:
        _stt_model = None
        _stt_key = None
        raise
    except Exception as exc:
        # Never keep a half-loaded or GPU-broken model cached for the next turn.
        _stt_model = None
        _stt_key = None
        _raise_mapped(exc, source="faster-whisper")
    finally:
        _stt_lock.release()

    return {
        "text": text,
        "language": "pt",
        "variant": "pt",
        "regional": "pt-PT-não-garantido",
        "duration": duration,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "engine": "faster-whisper",
        "model": model,
        "device": device,
    }


# --- TTS ------------------------------------------------------------------


def _load_tts_model(name: str) -> Any:
    voices = _voices()
    if name not in voices:
        raise ModelMissingError(
            "Voz pt-PT não instalada ou não encontrada. Consulta a configuração de voz."
        )
    try:
        from piper import PiperVoice
    except ImportError as exc:
        raise DependencyMissingError("Motor Piper não instalado. Instala o extra voice.") from exc
    try:
        return PiperVoice.load(voices[name], use_cuda=False)
    except Exception as exc:
        _raise_mapped(exc, source="piper")


def _validate_wav(data: bytes) -> None:
    if not data.startswith(b"RIFF") or b"WAVE" not in data[:12]:
        raise InvalidAudioError("A síntese não produziu um WAV válido.")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            if wav.getnframes() <= 0:
                raise EmptyAudioError("A síntese não produziu áudio.")
            raw = wav.readframes(wav.getnframes())
    except VoiceError:
        raise
    except Exception as exc:
        raise InvalidAudioError("A síntese não produziu um WAV válido.") from exc
    if not raw:
        raise EmptyAudioError("A síntese não produziu áudio.")
    # 16-bit PCM is the only format Piper emits; guard against an all-zero buffer.
    if len(raw) >= 2:
        import struct

        peak = max(abs(value) for (value,) in struct.iter_unpack("<h", raw[: len(raw) - (len(raw) % 2)]))
        if peak < int(SILENCE_PEAK * 32767):
            raise EmptyAudioError("A síntese resultou em silêncio.")


def synthesize(
    text: str,
    voice: str | None = None,
    speed: float = 1.0,
    *,
    timeout: float | None = DEFAULT_TRANSCRIBE_TIMEOUT,
) -> bytes:
    """Synthesise speech with Piper on CPU and return a validated WAV."""
    global _tts_key, _tts_model
    if not text or not text.strip():
        raise InvalidArgumentError("Texto vazio.")
    if len(text) > MAX_TEXT_CHARS:
        raise InvalidArgumentError(f"Texto excede {MAX_TEXT_CHARS} caracteres.")
    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise InvalidArgumentError(f"Velocidade fora de {MIN_SPEED}..{MAX_SPEED}.")

    voices = _voices()
    name = voice or (DEFAULT_VOICE if DEFAULT_VOICE in voices else next(iter(voices), ""))
    if not name:
        raise ModelMissingError("Nenhuma voz pt-PT instalada. Consulta a configuração de voz.")
    if name not in voices:
        raise ModelMissingError(
            "Voz pt-PT não instalada ou não encontrada. Consulta a configuração de voz."
        )

    started = time.monotonic()
    _lock_or_timeout(_tts_lock, timeout)
    try:
        global _tts_model
        if _tts_key != name:
            _tts_model = None
            _tts_key = None
            _tts_model = _load_tts_model(name)
            _tts_key = name
        result = io.BytesIO()
        try:
            from piper import SynthesisConfig
        except ImportError as exc:
            raise DependencyMissingError(
                "Motor Piper não instalado. Instala o extra voice."
            ) from exc
        try:
            with wave.open(result, "wb") as wav:
                _tts_model.synthesize_wav(
                    text, wav, syn_config=SynthesisConfig(length_scale=1.0 / speed)
                )
        except VoiceError:
            _tts_model = None
            _tts_key = None
            raise
        except Exception as exc:
            _tts_model = None
            _tts_key = None
            _raise_mapped(exc, source="piper")
        data = result.getvalue()
    except VoiceError:
        _tts_model = None
        _tts_key = None
        raise
    except Exception as exc:
        _tts_model = None
        _tts_key = None
        _raise_mapped(exc, source="piper")
    finally:
        _tts_lock.release()

    if timeout is not None and time.monotonic() - started > timeout:
        raise ProcessingTimeoutError("Tempo limite de síntese excedido.")
    _validate_wav(data)
    return data


# --- Status ---------------------------------------------------------------


def status() -> dict[str, Any]:
    """Report readiness and the explicit audio/resource contract."""
    stt_available = _module_available("faster_whisper")
    tts_available = _module_available("piper")
    devices = ["cpu"]
    if stt_available and _cuda_available():
        devices.append("cuda")
    voices = _voices()
    voice_ids = sorted(voices)
    stt_ready = stt_available and any(_stt_installed(name) for name in STT_MODELS)
    return {
        "ok": True,
        "local_only": True,
        "network": "none",
        "contract": {
            "input": {
                "max_bytes": MAX_AUDIO_BYTES,
                "max_duration_seconds": MAX_DURATION_SECONDS,
                "sample_rate": SAMPLE_RATE,
                "channels": CHANNELS,
                "sample_format": SAMPLE_FORMAT,
                "preferred": "audio/wav, pcm_s16le, mono, 16000 Hz",
                "accepted_content_types": sorted(SUPPORTED_CONTENT_TYPES),
                "decoder": "PyAV (local)",
            },
            "transcribe_output": "JSON {text, language=pt, variant, duration, model, device}",
            "synthesize_output": "audio/wav, pcm_s16le",
            "silent_input": "rejected with code=empty_audio",
        },
        "stt": {
            "ready": stt_ready,
            "engine": "faster-whisper",
            "models": [{"id": name, "installed": _stt_installed(name)} for name in STT_MODELS],
            "devices": devices,
            "cuda_note": (
                "CUDA pode ser detetado sem cublas/cuDNN configurados; "
                "usa device=cpu se a inferência falhar."
            ),
            "default_model": default_stt_model(),
            # faster-whisper only exposes the generic code; pt-PT is NOT guaranteed.
            "language": "pt",
            "regional_variant": None,
            "regional_note": (
                "language='pt' é genérico; pt-PT não é garantido pelo faster-whisper."
            ),
        },
        "tts": {
            "ready": tts_available and bool(voices),
            "engine": "piper",
            "voices": [
                {
                    "id": name,
                    "name": name,
                    "language": "pt-PT",
                    "regional": "pt_PT",
                    "path": _display_path(voices[name]),
                }
                for name in voice_ids
            ],
            "default": DEFAULT_VOICE if DEFAULT_VOICE in voices else (voice_ids[0] if voice_ids else None),
            "accent_note": "Voz pt-PT; sotaque do Porto não verificado.",
        },
        "budget": resource_budget(),
        "limitations": [
            "Modelos ausentes não são descarregados em pedidos.",
            "Áudio truncado é decodificado até ao fim disponível; não é detetável como truncamento.",
            "O cancelamento nativo de inferência C não é possível; pedidos serializam e expiram com 504.",
            "faster-whisper usa language='pt'; PT-PT não é garantido.",
            "CUDA pode ser detetado sem cublas/cuDNN; nesse caso usa device=cpu.",
        ],
    }


def reset_models() -> None:
    """Release cached models. Used by tests and explicit unload requests."""
    global _stt_key, _stt_model, _tts_key, _tts_model
    _stt_model = None
    _stt_key = None
    _tts_model = None
    _tts_key = None