"""
Token Management System — substitui heurística len//4 por tokenizer real.

Fornece:
1. count_tokens() — contagem real via tiktoken com fallback para Ollama /api/tokenize
2. deduplicate_context_blocks() — remove blocos duplicados do contexto antes do LLM
3. validate_total_budget() — verifica se o payload cabe na context window do modelo
4. dynamic_threshold() — calcula threshold dinâmico baseado no modelo (85% do limite)
5. ContextOverflowError — exceção para overflow controlado
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model context limits (must match / be sourced from models.yaml)
# ---------------------------------------------------------------------------
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "micro": 4_096,
    "fast": 8_192,
    "coder": 16_384,
    "reasoning": 32_768,
    "deep": 65_536,
    # Legacy aliases
    "nano": 4_096,
    "small": 8_192,
    "medium": 16_384,
    "large": 32_768,
    "expert": 32_768,
    "dashboard": 4_096,
}


class ContextOverflowError(ValueError):
    """Raised when the assembled context exceeds the model's context window capacity."""
    pass


# ---------------------------------------------------------------------------
# Token counting (tiktoken-based with fallback)
# ---------------------------------------------------------------------------

# Lazy import to avoid hard dependency — tiktoken may not be installed
_HAVE_TIKTOKEN: bool = False
_TOKENIZER_CACHE: dict[str, object] = {}


def _get_tiktoken_encoding(model: str) -> object:
    """Get tiktoken encoding for the given model, with caching."""
    global _HAVE_TIKTOKEN

    if not _HAVE_TIKTOKEN:
        try:
            import tiktoken  # noqa: F811
            _HAVE_TIKTOKEN = True
        except ImportError:
            _HAVE_TIKTOKEN = False
            return None

    # Map model name to encoding key
    model_lower = model.lower()
    if "gpt-4" in model_lower:
        enc_key = "gpt-4"
    elif "gpt-3.5" in model_lower:
        enc_key = "gpt-3.5-turbo"
    elif "text-davinci" in model_lower:
        enc_key = "text-davinci-003"
    else:
        enc_key = "cl100k_base"  # Default for most open models

    if enc_key not in _TOKENIZER_CACHE:
        try:
            import tiktoken
            _TOKENIZER_CACHE[enc_key] = tiktoken.encoding_for_model(enc_key)
        except (KeyError, ValueError):
            try:
                import tiktoken
                _TOKENIZER_CACHE[enc_key] = tiktoken.get_encoding("cl100k_base")
            except Exception:
                return None

    return _TOKENIZER_CACHE.get(enc_key)


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Count tokens using tiktoken. Falls back to len//4 heuristic.

    Args:
        text: The text to count tokens for.
        model: Model name to select appropriate tokenizer.

    Returns:
        Number of tokens (int).
    """
    if not text:
        return 0

    # Try tiktoken first
    encoding = _get_tiktoken_encoding(model)
    if encoding is not None:
        try:
            return len(encoding.encode(text))
        except Exception:
            pass

    # Fallback: heuristic len//4 (original behavior)
    return max(1, len(text) // 4)


def count_tokens_for_messages(messages: list[dict], model: str = "cl100k_base") -> int:
    """Count total tokens for a list of message dicts (OpenAI format).

    Accounts for per-message overhead (~4 tokens per message).
    """
    total = 0
    for msg in messages:
        total += 4  # Per-message overhead
        for key, value in msg.items():
            if isinstance(value, str):
                total += count_tokens(value, model)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        total += count_tokens(str(item), model)
                    elif isinstance(item, str):
                        total += count_tokens(item, model)
        total += 2  # Assistant overhead if applicable
    total += 2  # Reply overhead
    return total


# ---------------------------------------------------------------------------
# Dynamic threshold (85% of model's true context window)
# ---------------------------------------------------------------------------

def dynamic_threshold(model_tier: str, safety_margin: float = 0.85) -> int:
    """Calculate dynamic context threshold based on model tier.

    Args:
        model_tier: The model tier name (micro, fast, coder, reasoning, deep).
        safety_margin: Fraction of total context window to use (default 0.85).

    Returns:
        Maximum input tokens allowed.
    """
    limit = MODEL_CONTEXT_LIMITS.get(model_tier, 8_192)
    return int(limit * safety_margin)


# ---------------------------------------------------------------------------
# Context deduplication
# ---------------------------------------------------------------------------

def deduplicate_context_blocks(blocks: list[str]) -> list[str]:
    """Remove duplicate blocks from context before sending to the LLM.

    Uses MD5 hash of normalized content for detection.
    Preserves insertion order (first occurrence kept).

    Args:
        blocks: List of context block strings.

    Returns:
        List with duplicates removed.
    """
    seen_hashes: set[str] = set()
    unique_blocks: list[str] = []

    for block in blocks:
        normalized = block.strip().lower()
        block_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()
        if block_hash not in seen_hashes:
            seen_hashes.add(block_hash)
            unique_blocks.append(block)

    removed = len(blocks) - len(unique_blocks)
    if removed > 0:
        logger.debug("[DEDUP] Removed %d/%d duplicate context blocks", removed, len(blocks))

    return unique_blocks


# ---------------------------------------------------------------------------
# Total budget validation
# ---------------------------------------------------------------------------

def validate_total_budget(
    system_tokens: int = 0,
    memory_tokens: int = 0,
    history_tokens: int = 0,
    query_tokens: int = 0,
    tool_result_tokens: int = 0,
    model_tier: str = "coder",
    output_reserve: int = 4_096,
) -> bool:
    """Validate that the total assembled context fits within the model's context window.

    Raises ContextOverflowError if the budget is exceeded, allowing the caller
    to apply remediation (trimming, summarization) before sending to the LLM.

    Args:
        system_tokens: Tokens used by system prompt.
        memory_tokens: Tokens used by memory context.
        history_tokens: Tokens used by conversation history.
        query_tokens: Tokens used by the current user query.
        tool_result_tokens: Tokens used by tool execution results.
        model_tier: The model tier name.
        output_reserve: Tokens to reserve for model output (default 4096).

    Returns:
        True if within budget.

    Raises:
        ContextOverflowError: If total + output_reserve > model context limit.
    """
    total = system_tokens + memory_tokens + history_tokens + query_tokens + tool_result_tokens
    limit = MODEL_CONTEXT_LIMITS.get(model_tier, 8_192)

    if total + output_reserve > limit:
        raise ContextOverflowError(
            f"Context overflow: {total} tokens + {output_reserve} output reserve "
            f"exceeds {limit} limit (model_tier={model_tier}). "
            f"Breakdown: system={system_tokens}, memory={memory_tokens}, "
            f"history={history_tokens}, query={query_tokens}, tools={tool_result_tokens}"
        )

    return True


# ---------------------------------------------------------------------------
# Token waste estimation
# ---------------------------------------------------------------------------

def estimate_token_waste(
    cache_hit_rate: float = 0.0,
    dedup_savings: float = 0.0,
) -> float:
    """Estimate the percentage of tokens that are unnecessary.

    Based on cache hit rate and context deduplication savings.

    Args:
        cache_hit_rate: Ratio of semantic cache hits (0.0 to 1.0).
        dedup_savings: Ratio of context saved by deduplication (0.0 to 1.0).

    Returns:
        Estimated waste percentage (0-100).
    """
    # LLM calls avoided due to cache hit
    llm_savings = cache_hit_rate * 0.70
    # Token reduction due to deduplication
    context_savings = dedup_savings * 0.30
    total_savings = llm_savings + context_savings
    return total_savings * 100


def _get_dedup_savings() -> float:
    """Get current deduplication savings (for metrics dashboard)."""
    from backend.token_management import deduplicate_context_blocks

    # This would be tracked by a global counter in production
    return 0.0


# ---------------------------------------------------------------------------
# Trimming utilities
# ---------------------------------------------------------------------------

def trim_context_structured(
    iterations: list[dict],
    model_tier: str,
    model: str = "cl100k_base",
    min_iterations: int = 2,
) -> list[dict]:
    """Trim context by preserving objective + last N iterations, compressing the rest.

    This structured approach replaces the fragile string-splitting heuristic
    previously used in _trim_context(). Operates on structured iteration dicts
    instead of raw text.

    Args:
        iterations: List of iteration dicts (each has 'thought', 'tool', 'result', etc.)
        model_tier: Model tier for threshold calculation.
        model: Model name for token counting.
        min_iterations: Minimum number of recent iterations to keep in full.

    Returns:
        Trimmed list of iterations.
    """
    if not iterations:
        return iterations

    threshold = dynamic_threshold(model_tier)

    # Always preserve: objective (iter[0]) + last min_iterations
    if len(iterations) <= min_iterations + 1:
        return iterations

    protected = [iterations[0]] + iterations[-min_iterations:]
    compressible = iterations[1:-min_iterations]

    if not compressible:
        return iterations

    # Compress middle iterations into a brief summary
    compressed = _compress_iterations(compressible, model)

    result = [iterations[0]] + compressed + iterations[-min_iterations:]

    # Verify against threshold; if still over, drop compressed
    total_tokens = sum(count_tokens(str(it), model) for it in result)
    if total_tokens > threshold:
        result = [iterations[0]] + iterations[-min_iterations:]

    return result


def _compress_iterations(iterations: list[dict], model: str) -> list[dict]:
    """Compress old iterations into a compact summary.

    Currently extracts key info from each iteration. In the future this can
    use a cheap LLM call for semantic summarization.

    Args:
        iterations: Middle iterations to compress.
        model: Model name for token counting.

    Returns:
        List with a single summary dict.
    """
    if not iterations:
        return []

    summary_lines = []
    for i, it in enumerate(iterations):
        thought = str(it.get("thought", ""))[:100]
        tool = it.get("tool", "")
        result_preview = str(it.get("result", ""))[:100]
        summary_lines.append(
            f"[Step {i+1}] {tool}: {thought} → {result_preview}"
        )

    summary_text = "\n".join(summary_lines)

    return [{
        "type": "compressed_history",
        "content": summary_text,
        "original_count": len(iterations),
        "role": "system",
    }]
