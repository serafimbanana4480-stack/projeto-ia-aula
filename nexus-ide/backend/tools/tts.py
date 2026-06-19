"""TTS (Text-to-Speech) — voice output for NEXUS IDE.

Supports multiple providers:
- pyttsx3: Local, offline, cross-platform
- edge-tts: High-quality online voices (Microsoft Edge)
- gTTS: Google TTS (requires internet)
- elevenlabs: Premium AI voices (requires API key)

Configuration:
- TTS_ENABLED=true/false
- TTS_PROVIDER=pyttsx3|edge-tts|gtts|elevenlabs
- TTS_VOICE_ID=voice_id (provider-specific)
- TTS_LANGUAGE=pt-PT (default language)
- TTS_SPEED=1.0 (speech rate)

Usage:
    from backend.tools.tts import speak, speak_async
    speak("Olá mundo!")
    await speak_async("Hello world!")
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy imports to avoid loading heavy libraries at startup
_tts_providers: dict[str, Any] = {}


def _get_provider(name: str):
    """Lazy-load TTS provider."""
    global _tts_providers
    if name in _tts_providers:
        return _tts_providers[name]

    if name == "pyttsx3":
        try:
            import pyttsx3

            engine = pyttsx3.init()
            _tts_providers[name] = engine
            return engine
        except ImportError:
            logger.warning("pyttsx3 not installed. Install: pip install pyttsx3")
            return None
        except Exception as exc:
            logger.warning("Failed to initialize pyttsx3: %s", exc)
            return None

    elif name == "edge-tts":
        try:
            import edge_tts

            _tts_providers[name] = edge_tts
            return edge_tts
        except ImportError:
            logger.warning("edge-tts not installed. Install: pip install edge-tts")
            return None

    elif name == "gtts":
        try:
            from gtts import gTTS

            _tts_providers[name] = gTTS
            return gTTS
        except ImportError:
            logger.warning("gTTS not installed. Install: pip install gtts")
            return None

    elif name == "elevenlabs":
        try:
            from elevenlabs import generate, set_api_key

            _tts_providers[name] = (generate, set_api_key)
            return _tts_providers[name]
        except ImportError:
            logger.warning("elevenlabs not installed. Install: pip install elevenlabs")
            return None

    return None


class TTSConfig:
    """TTS configuration from environment."""

    def __init__(self) -> None:
        self.enabled = os.getenv("TTS_ENABLED", "false").lower() in ("true", "1", "yes", "on")
        self.provider = os.getenv("TTS_PROVIDER", "pyttsx3").lower()
        self.voice_id = os.getenv("TTS_VOICE_ID", "")
        self.language = os.getenv("TTS_LANGUAGE", "pt-PT")
        self.speed = float(os.getenv("TTS_SPEED", "1.0"))
        self.output_dir = Path(os.getenv("TTS_OUTPUT_DIR", "data/tts"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        """Check if TTS is available and configured."""
        if not self.enabled:
            return False
        provider = _get_provider(self.provider)
        return provider is not None


_config = TTSConfig()


def _speak_pyttsx3(text: str, config: TTSConfig) -> None:
    """Speak using pyttsx3 (local, offline)."""
    engine = _get_provider("pyttsx3")
    if engine is None:
        return

    # Configure voice
    voices = engine.getProperty("voices")
    if config.voice_id and voices:
        for voice in voices:
            if config.voice_id in voice.id or config.voice_id in voice.name:
                engine.setProperty("voice", voice.id)
                break
    elif voices:
        # Try to find a voice matching the language
        for voice in voices:
            if config.language[:2] in voice.id.lower() or config.language[:2] in voice.name.lower():
                engine.setProperty("voice", voice.id)
                break

    engine.setProperty("rate", int(200 * config.speed))
    engine.say(text)
    engine.runAndWait()


async def _speak_edge_tts(text: str, config: TTSConfig) -> None:
    """Speak using edge-tts (Microsoft Edge voices, online)."""
    edge_tts = _get_provider("edge-tts")
    if edge_tts is None:
        return

    # Voice mapping for Portuguese
    voice = (
        config.voice_id or "pt-PT-DiaNeural" if config.language == "pt-PT" else "en-US-GuyNeural"
    )
    if config.language == "pt-PT":
        voice = "pt-PT-DiaNeural"
    elif config.language == "en-US":
        voice = "en-US-GuyNeural"
    elif config.language == "en-GB":
        voice = "en-GB-SoniaNeural"
    else:
        voice = config.voice_id or "en-US-GuyNeural"

    output_file = config.output_dir / f"tts_{hash(text) % 100000}.mp3"

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(output_file))

    # Play the audio
    await _play_audio(str(output_file))


async def _play_audio(file_path: str) -> None:
    """Play audio file using system player."""
    import platform

    system = platform.system()
    try:
        if system == "Windows":
            # winsound only supports WAV, so we need a different approach for MP3
            # Use start command to play with default player
            os.system(f'start "" "{file_path}"')
        elif system == "Darwin":  # macOS
            os.system(f'afplay "{file_path}"')
        else:  # Linux
            os.system(f'xdg-open "{file_path}" > /dev/null 2>&1 &')
    except Exception as exc:
        logger.warning("Failed to play audio: %s", exc)


def _speak_gtts(text: str, config: TTSConfig) -> None:
    """Speak using gTTS (Google TTS, requires internet)."""
    gTTS = _get_provider("gtts")
    if gTTS is None:
        return

    try:
        tts = gTTS(text=text, lang=config.language[:2], slow=(config.speed < 1.0))
        output_file = config.output_dir / f"tts_{hash(text) % 100000}.mp3"
        tts.save(str(output_file))

        # Play
        import asyncio

        asyncio.run(_play_audio(str(output_file)))
    except Exception as exc:
        logger.warning("gTTS failed: %s", exc)


def _speak_elevenlabs(text: str, config: TTSConfig) -> None:
    """Speak using ElevenLabs (premium, requires API key)."""
    elevenlabs = _get_provider("elevenlabs")
    if elevenlabs is None:
        return

    generate, set_api_key = elevenlabs
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        logger.warning("ElevenLabs API key not set")
        return

    set_api_key(api_key)

    try:
        voice = config.voice_id or "Rachel"
        audio = generate(text=text, voice=voice, model="eleven_multilingual_v2")
        output_file = config.output_dir / f"tts_{hash(text) % 100000}.mp3"
        with open(output_file, "wb") as f:
            f.write(audio)

        import asyncio

        asyncio.run(_play_audio(str(output_file)))
    except Exception as exc:
        logger.warning("ElevenLabs failed: %s", exc)


def speak(text: str, provider: str | None = None) -> dict[str, Any]:
    """Speak text aloud using the configured TTS provider.

    Args:
        text: Text to speak.
        provider: Override provider (pyttsx3, edge-tts, gtts, elevenlabs).

    Returns:
        Dict with success status and details.
    """
    config = TTSConfig()
    if not config.enabled:
        return {"success": False, "reason": "TTS disabled"}

    if not text or not text.strip():
        return {"success": False, "reason": "empty text"}

    provider = provider or config.provider
    provider_obj = _get_provider(provider)

    if provider_obj is None:
        return {"success": False, "reason": f"provider '{provider}' not available"}

    try:
        if provider == "pyttsx3":
            _speak_pyttsx3(text, config)
        elif provider == "gtts":
            _speak_gtts(text, config)
        elif provider == "elevenlabs":
            _speak_elevenlabs(text, config)
        else:
            # edge-tts is async
            asyncio.run(_speak_edge_tts(text, config))

        return {"success": True, "provider": provider, "text": text[:100]}
    except Exception as exc:
        logger.error("TTS failed: %s", exc)
        return {"success": False, "reason": str(exc)}


async def speak_async(text: str, provider: str | None = None) -> dict[str, Any]:
    """Async version of speak()."""
    config = TTSConfig()
    if not config.enabled:
        return {"success": False, "reason": "TTS disabled"}

    if not text or not text.strip():
        return {"success": False, "reason": "empty text"}

    provider = provider or config.provider
    provider_obj = _get_provider(provider)

    if provider_obj is None:
        return {"success": False, "reason": f"provider '{provider}' not available"}

    try:
        if provider == "edge-tts":
            await _speak_edge_tts(text, config)
        elif provider == "pyttsx3":
            # pyttsx3 is synchronous, run in thread
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _speak_pyttsx3, text, config)
        elif provider == "gtts":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _speak_gtts, text, config)
        elif provider == "elevenlabs":
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _speak_elevenlabs, text, config)

        return {"success": True, "provider": provider, "text": text[:100]}
    except Exception as exc:
        logger.error("TTS failed: %s", exc)
        return {"success": False, "reason": str(exc)}


def tts_status() -> dict[str, Any]:
    """Return the TTS subsystem status and a small voice sample.

    Safe to call even if no TTS provider is installed.
    """
    config = TTSConfig()
    voices: list[dict[str, str]] = []
    try:
        voices = get_available_voices()
    except Exception:
        voices = []
    return {
        "provider": config.provider,
        "rate": config.rate,
        "volume": config.volume,
        "voice_id": config.voice_id,
        "available_providers": ["pyttsx3", "gtts", "elevenlabs"],
        "voices": voices,
        "ready": bool(voices),
    }


def get_available_voices() -> list[dict[str, str]]:
    """Get list of available voices for the current provider."""
    config = TTSConfig()
    provider = config.provider

    voices = []
    if provider == "pyttsx3":
        engine = _get_provider("pyttsx3")
        if engine:
            for voice in engine.getProperty("voices"):
                voices.append(
                    {
                        "id": voice.id,
                        "name": voice.name,
                        "language": getattr(voice, "languages", ["unknown"])[0]
                        if hasattr(voice, "languages")
                        else "unknown",
                    }
                )
    elif provider == "edge-tts":
        # Common Edge voices
        voices = [
            {"id": "pt-PT-DiaNeural", "name": "Dia (Portuguese)"},
            {"id": "pt-BR-AntonioNeural", "name": "Antonio (Brazilian Portuguese)"},
            {"id": "en-US-GuyNeural", "name": "Guy (US English)"},
            {"id": "en-US-JennyNeural", "name": "Jenny (US English)"},
            {"id": "en-GB-SoniaNeural", "name": "Sonia (British English)"},
            {"id": "es-ES-AlvaroNeural", "name": "Alvaro (Spanish)"},
            {"id": "fr-FR-HenriNeural", "name": "Henri (French)"},
            {"id": "de-DE-KatjaNeural", "name": "Katja (German)"},
        ]


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

from backend.tools.registry import ToolSpec, register_tool

register_tool(
    ToolSpec(
        name="speak",
        description=(
            "Convert text to speech using the configured TTS provider. "
            "Supports pyttsx3 (local), edge-tts (online), gTTS (Google), and elevenlabs (premium)."
        ),
        schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to speak",
                },
                "provider": {
                    "type": "string",
                    "description": "TTS provider override (pyttsx3, edge-tts, gtts, elevenlabs)",
                },
            },
            "required": ["text"],
        },
        handler=speak,
    )
)

register_tool(
    ToolSpec(
        name="tts_status",
        description="Get TTS status and available voices.",
        schema={
            "type": "object",
            "properties": {},
        },
        handler=tts_status,
    )
)
