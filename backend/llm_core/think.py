"""Strip reasoning/thinking sections from LLM responses.

Some models (DeepSeek-R1, Qwen-QwQ, etc.) emit chain-of-thought reasoning
inside the response body. We don't want this leaking into descriptions,
labels, or DOCX cells.

The patterns we strip:
  - <think> ... </think>            (XML-style, possibly multi-line)
  - <thinking> ... </thinking>      (variant)
  - ```think ... ```                (fenced block, language=think)
  - ```thinking ... ```             (variant)
  - "Think:" / "Thinking:" prefix on a line, removed up to the next blank line

After stripping, leading/trailing whitespace is collapsed.
"""

import re

# Multi-line tag blocks. DOTALL so '.' matches newlines.
_TAG_BLOCK_RE = re.compile(
    r"<\s*think(?:ing)?\s*>.*?<\s*/\s*think(?:ing)?\s*>",
    re.IGNORECASE | re.DOTALL,
)

# Fenced code blocks marked as ```think or ```thinking
_FENCE_BLOCK_RE = re.compile(
    r"```\s*think(?:ing)?\b.*?```",
    re.IGNORECASE | re.DOTALL,
)

# Leading "Think:" / "Thinking:" paragraph at the very start of the response.
_LEADING_PREFIX_RE = re.compile(
    r"^\s*think(?:ing)?\s*:\s*.*?(?:\n\s*\n|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def strip_think_section(text: str) -> str:
    """Return text with all reasoning/think sections removed.

    Safe to call on None or empty strings — returns the input as-is in that case.
    """
    if not text:
        return text
    out = text
    out = _TAG_BLOCK_RE.sub("", out)
    out = _FENCE_BLOCK_RE.sub("", out)
    out = _LEADING_PREFIX_RE.sub("", out)
    return out.strip()
