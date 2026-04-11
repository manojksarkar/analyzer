"""Token counting with tiktoken (exact) or character-based fallback.

Every component that touches token budgets uses a single TokenCounter
instance.  Incorrect counting is the most common cause of pipeline
failures in context-sensitive systems.

Usage:
    counter = TokenCounter(model="gpt-4")   # exact via tiktoken
    counter = TokenCounter()                 # fallback: len(text) / 3.5

The fallback ratio (3.5 chars/token) is conservative for C++ code, which
tokenizes less efficiently than English prose (~2.5-3 chars/token for
code).  It is better to slightly overcount than to overflow the context.
"""

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# tiktoken availability
# ---------------------------------------------------------------------------

try:
    import tiktoken
    _HAS_TIKTOKEN = True
except ImportError:
    tiktoken = None  # type: ignore[assignment]
    _HAS_TIKTOKEN = False


# ---------------------------------------------------------------------------
# Token Counter
# ---------------------------------------------------------------------------

# Default chars-per-token when tiktoken is unavailable or model is unknown.
_FALLBACK_CHARS_PER_TOKEN = 3.5

# Map of known model prefixes to tiktoken encoding names.
# Used when the caller passes a model name that tiktoken doesn't recognise
# directly but we can infer the encoding family.
_MODEL_ENCODING_HINTS = {
    "gpt-4": "cl100k_base",
    "gpt-3.5": "cl100k_base",
    "gpt-oss": "cl100k_base",
    "o200k": "o200k_base",
}


class TokenCounter:
    """Count tokens with tiktoken when available, char heuristic otherwise."""

    def __init__(self, model: str = "", fallback_ratio: float = _FALLBACK_CHARS_PER_TOKEN) -> None:
        self._lock = threading.Lock()
        self._model = model
        self._ratio = float(fallback_ratio)
        self._encoder = None
        self._mode = "estimate"

        if _HAS_TIKTOKEN and model:
            self._encoder = _resolve_encoder(model)
            if self._encoder:
                self._mode = "exact"
                logger.debug("TokenCounter: exact mode via tiktoken for %r", model)

        if self._mode == "estimate":
            reason = "tiktoken not installed" if not _HAS_TIKTOKEN else f"no encoding for {model!r}"
            logger.debug("TokenCounter: estimate mode (%.1f chars/token) — %s", self._ratio, reason)

    @property
    def mode(self) -> str:
        """'exact' if using tiktoken, 'estimate' if char heuristic."""
        return self._mode

    def count(self, text: str) -> int:
        """Return the token count for *text*."""
        if not text:
            return 0
        if self._mode == "exact":
            return len(self._encoder.encode(text))
        return int(len(text) / self._ratio) + 1

    def count_messages(self, messages: list) -> int:
        """Estimate token count for a list of chat messages.

        Adds a small overhead per message for role/structural tokens
        (roughly 4 tokens per message for the role + delimiters).
        """
        total = 0
        for msg in messages:
            total += self.count(msg.get("content", "") or "")
            total += 4  # role + structural overhead
        return total + 2  # conversation-level overhead

    def fits(self, text: str, budget: int) -> bool:
        """Return True if *text* fits within *budget* tokens."""
        return self.count(text) <= budget

    def truncate_to_budget(self, text: str, budget: int, marker: str = "\n... [truncated]") -> str:
        """Truncate *text* to fit within *budget* tokens.

        Tries to cut at a line boundary for readability.  Appends *marker*
        if truncation occurred.
        """
        if self.fits(text, budget):
            return text

        marker_tokens = self.count(marker)
        target = max(1, budget - marker_tokens)

        if self._mode == "exact":
            tokens = self._encoder.encode(text)
            truncated_tokens = tokens[:target]
            result = self._encoder.decode(truncated_tokens)
        else:
            char_budget = int(target * self._ratio)
            result = text[:char_budget]

        # Try to cut at a line boundary for readability
        last_newline = result.rfind("\n", len(result) // 2)
        if last_newline > 0:
            result = result[:last_newline]

        return result + marker


# ---------------------------------------------------------------------------
# Module-level convenience — singleton per model
# ---------------------------------------------------------------------------

_instances: dict = {}
_instances_lock = threading.Lock()


def get_counter(model: str = "") -> TokenCounter:
    """Return a cached TokenCounter for *model* (one instance per model)."""
    with _instances_lock:
        if model not in _instances:
            _instances[model] = TokenCounter(model=model)
        return _instances[model]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_encoder(model: str) -> Optional[object]:
    """Try to find a tiktoken encoder for the given model name."""
    # 1. Direct model lookup (e.g. "gpt-4", "gpt-3.5-turbo")
    try:
        return tiktoken.encoding_for_model(model)
    except (KeyError, ValueError):
        pass

    # 2. Prefix-based lookup (e.g. "gpt-oss-120b" → cl100k_base)
    model_lower = model.lower()
    for prefix, encoding_name in _MODEL_ENCODING_HINTS.items():
        if model_lower.startswith(prefix):
            try:
                return tiktoken.get_encoding(encoding_name)
            except Exception:
                pass

    # 3. Default to cl100k_base (most common modern encoding)
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None
