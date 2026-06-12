"""Vision — image analysis and screenshot processing for NEXUS IDE.

Supports:
- Screenshot analysis (OCR, UI element detection, error detection)
- Image description using vision-capable LLMs (Ollama vision models)
- Diagram/flowchart interpretation
- QR code and barcode reading
- Image comparison (before/after screenshots)

Configuration:
- VISION_ENABLED=true/false
- VISION_MODEL=llava:7b (or other Ollama vision model)
- VISION_LANGUAGE=pt-PT

Usage:
    from backend.tools.vision import analyze_image, analyze_screenshot, compare_images
    result = await analyze_image("path/to/screenshot.png")
    result = await analyze_screenshot("data/screenshots/error.png")
"""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)


class VisionConfig:
    """Vision configuration from environment."""

    def __init__(self) -> None:
        self.enabled = os.getenv("VISION_ENABLED", "false").lower() in ("true", "1", "yes", "on")
        self.model = os.getenv("VISION_MODEL", "llava:7b")
        self.language = os.getenv("VISION_LANGUAGE", "pt-PT")
        self.max_size = int(os.getenv("VISION_MAX_SIZE", "2048"))  # Max dimension
        self.quality = int(os.getenv("VISION_QUALITY", "85"))  # JPEG quality

    def is_available(self) -> bool:
        """Check if vision is available."""
        if not self.enabled:
            return False
        # Check if PIL is available
        try:
            import PIL
            return True
        except ImportError:
            return False


_config = VisionConfig()


def _resize_image(image: Image.Image, max_size: int = 2048) -> Image.Image:
    """Resize image if it exceeds max dimensions."""
    width, height = image.size
    if width > max_size or height > max_size:
        ratio = min(max_size / width, max_size / height)
        new_size = (int(width * ratio), int(height * ratio))
        image = image.resize(new_size, Image.LANCZOS)
    return image


def _encode_image(image_path: str | Path, max_size: int = 2048, quality: int = 85) -> str:
    """Encode image to base64 for LLM vision APIs.

    Args:
        image_path: Path to the image file.
        max_size: Maximum dimension (width or height).
        quality: JPEG quality (1-100).

    Returns:
        Base64-encoded image string with data URI prefix.
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    image = Image.open(path)

    # Convert to RGB if necessary (for JPEG)
    if image.mode in ("RGBA", "P", "LA", "L"):
        image = image.convert("RGB")

    # Resize if too large
    image = _resize_image(image, max_size)

    # Save to buffer
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)

    # Encode
    encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


async def _call_vision_llm(image_b64: str, prompt: str, model: str | None = None) -> str:
    """Call a vision-capable LLM via Ollama.

    Args:
        image_b64: Base64-encoded image with data URI prefix.
        prompt: Text prompt to accompany the image.
        model: Ollama vision model name (e.g. 'llava:7b').

    Returns:
        LLM response text.
    """
    import httpx

    model = model or _config.model
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{ollama_host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "images": [image_b64.split(",")[1]],  # Remove data URI prefix
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 1024,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "No response from vision model")
    except Exception as exc:
        logger.error("Vision LLM call failed: %s", exc)
        return f"Error analyzing image: {exc}"


async def analyze_image(image_path: str | Path, prompt: str | None = None, model: str | None = None) -> dict[str, Any]:
    """Analyze an image using a vision-capable LLM.

    Args:
        image_path: Path to the image file.
        prompt: Custom prompt (default: describe the image).
        model: Override vision model.

    Returns:
        Dict with description, detected elements, and raw response.
    """
    if not _config.is_available():
        return {"success": False, "reason": "vision not available"}

    path = Path(image_path)
    if not path.exists():
        return {"success": False, "reason": f"image not found: {path}"}

    try:
        # Encode image
        image_b64 = _encode_image(path, _config.max_size, _config.quality)

        # Default prompt based on language
        if not prompt:
            if _config.language == "pt-PT":
                prompt = "Descreve esta imagem em detalhe. Identifica elementos visuais, texto, UI elements, e qualquer erro ou problema aparente."
            elif _config.language == "es":
                prompt = "Describe esta imagen en detalle. Identifica elementos visuales, texto, UI elements, y cualquier error o problema aparente."
            else:
                prompt = "Describe this image in detail. Identify visual elements, text, UI elements, and any apparent errors or issues."

        # Call vision LLM
        response = await _call_vision_llm(image_b64, prompt, model)

        return {
            "success": True,
            "description": response,
            "image_path": str(path),
            "model": model or _config.model,
            "prompt": prompt,
        }

    except Exception as exc:
        logger.error("Image analysis failed: %s", exc)
        return {"success": False, "reason": str(exc)}


async def analyze_screenshot(image_path: str | Path, context: str | None = None) -> dict[str, Any]:
    """Analyze a screenshot with software development context.

    Args:
        image_path: Path to the screenshot.
        context: Optional context (e.g. "Error screen", "UI design review").

    Returns:
        Dict with analysis results.
    """
    if not _config.is_available():
        return {"success": False, "reason": "vision not available"}

    path = Path(image_path)
    if not path.exists():
        return {"success": False, "reason": f"screenshot not found: {path}"}

    try:
        image_b64 = _encode_image(path, _config.max_size, _config.quality)

        # Build prompt based on context
        if _config.language == "pt-PT":
            base_prompt = "Esta é uma screenshot de software. "
            if context:
                base_prompt += f"Contexto: {context}. "
            base_prompt += (
                "Analisa a imagem e identifica:\n"
                "1. Erros visuais (bugs, crashes, mensagens de erro)\n"
                "2. Problemas de UI/UX (layout, contrast, alinhamento)\n"
                "3. Texto presente na imagem\n"
                "4. Elementos de interface identificados\n"
                "5. Sugestões de melhoria\n"
                "Responde em português."
            )
        else:
            base_prompt = "This is a software screenshot. "
            if context:
                base_prompt += f"Context: {context}. "
            base_prompt += (
                "Analyze the image and identify:\n"
                "1. Visual errors (bugs, crashes, error messages)\n"
                "2. UI/UX issues (layout, contrast, alignment)\n"
                "3. Text present in the image\n"
                "4. Identified interface elements\n"
                "5. Improvement suggestions"
            )

        response = await _call_vision_llm(image_b64, base_prompt)

        return {
            "success": True,
            "analysis": response,
            "image_path": str(path),
            "context": context,
            "model": _config.model,
        }

    except Exception as exc:
        logger.error("Screenshot analysis failed: %s", exc)
        return {"success": False, "reason": str(exc)}


async def compare_images(image_path1: str | Path, image_path2: str | Path) -> dict[str, Any]:
    """Compare two images and describe differences.

    Args:
        image_path1: First image path.
        image_path2: Second image path.

    Returns:
        Dict with comparison results.
    """
    if not _config.is_available():
        return {"success": False, "reason": "vision not available"}

    path1 = Path(image_path1)
    path2 = Path(image_path2)

    if not path1.exists() or not path2.exists():
        return {"success": False, "reason": "one or both images not found"}

    try:
        # Encode both images
        image1_b64 = _encode_image(path1, _config.max_size, _config.quality)
        image2_b64 = _encode_image(path2, _config.max_size, _config.quality)

        # Build comparison prompt
        if _config.language == "pt-PT":
            prompt = (
                "Compara estas duas imagens. Identifica:\n"
                "1. Diferenças visuais entre elas\n"
                "2. Elementos que foram adicionados, removidos ou modificados\n"
                "3. Melhorias ou regressões\n"
                "4. Texto que mudou\n"
                "Responde em português."
            )
        else:
            prompt = (
                "Compare these two images. Identify:\n"
                "1. Visual differences between them\n"
                "2. Elements that were added, removed, or modified\n"
                "3. Improvements or regressions\n"
                "4. Text that changed"
            )

        # Note: Most Ollama vision models support single image only
        # We'll analyze each separately and then compare
        response1 = await _call_vision_llm(image1_b64, "Describe this image in detail.")
        response2 = await _call_vision_llm(image2_b64, "Describe this image in detail.")

        # Ask LLM to compare descriptions
        comparison_prompt = f"""
Image 1 description:
{response1}

Image 2 description:
{response2}

{prompt}
"""

        # Use a text model for comparison
        import httpx
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        text_model = os.getenv("FAST_MODEL", "qwen2.5:1.5b")

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{ollama_host}/api/generate",
                json={
                    "model": text_model,
                    "prompt": comparison_prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 1024},
                },
            )
            response.raise_for_status()
            data = response.json()
            comparison = data.get("response", "No comparison available")

        return {
            "success": True,
            "comparison": comparison,
            "image1_description": response1,
            "image2_description": response2,
            "image1_path": str(path1),
            "image2_path": str(path2),
        }

    except Exception as exc:
        logger.error("Image comparison failed: %s", exc)
        return {"success": False, "reason": str(exc)}


def get_image_info(image_path: str | Path) -> dict[str, Any]:
    """Get basic information about an image.

    Args:
        image_path: Path to the image.

    Returns:
        Dict with image metadata.
    """
    try:
        path = Path(image_path)
        if not path.exists():
            return {"success": False, "reason": "image not found"}

        image = Image.open(path)
        width, height = image.size

        return {
            "success": True,
            "path": str(path),
            "format": image.format,
            "mode": image.mode,
            "width": width,
            "height": height,
            "size_bytes": path.stat().st_size,
            "aspect_ratio": round(width / height, 2) if height > 0 else 0,
        }

    except Exception as exc:
        return {"success": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

from backend.tools.registry import ToolSpec, register_tool

register_tool(
    ToolSpec(
        name="analyze_image",
        description="Analyze an image using a vision-capable LLM (Ollama vision models).",
        schema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to the image file"},
                "prompt": {"type": "string", "description": "Custom analysis prompt"},
                "model": {"type": "string", "description": "Override vision model (default: llava:7b)"},
            },
            "required": ["image_path"],
        },
        handler=analyze_image,
    )
)

register_tool(
    ToolSpec(
        name="analyze_screenshot",
        description="Analyze a software screenshot for bugs, UI issues, and errors.",
        schema={
            "type": "object",
            "properties": {
                "image_path": {"type": "string", "description": "Path to the screenshot"},
                "context": {"type": "string", "description": "Optional context (e.g., 'Error screen')"},
            },
            "required": ["image_path"],
        },
        handler=analyze_screenshot,
    )
)

register_tool(
    ToolSpec(
        name="compare_images",
        description="Compare two images and describe the differences.",
        schema={
            "type": "object",
            "properties": {
                "image_path1": {"type": "string"},
                "image_path2": {"type": "string"},
            },
            "required": ["image_path1", "image_path2"],
        },
        handler=compare_images,
    )
)

register_tool(
    ToolSpec(
        name="vision_status",
        description="Get vision system status and configuration.",
        schema={"type": "object", "properties": {}},
        handler=vision_status,
    )
)
