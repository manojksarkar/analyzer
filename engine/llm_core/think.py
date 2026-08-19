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

import logging
import re

logger = logging.getLogger(__name__)

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
#
# It must end at a BLANK LINE. The pattern used to accept `\Z` as an alternative ending, so a
# response that opened with "Thinking:" and contained no blank line matched to the end of the
# string and was deleted in full — the model answered, and the caller saw nothing.
_LEADING_PREFIX_RE = re.compile(
    r"^\s*think(?:ing)?\s*:\s*.*?\n\s*\n",
    re.IGNORECASE | re.DOTALL,
)


def strip_think_section(text: str) -> str:
    """Return text with all reasoning/think sections removed.

    Safe to call on None or empty strings — returns the input as-is in that case.

    **Never turns a non-empty response into an empty one.** Stripping is a cleanup, not a
    filter: if the patterns consume everything, the reply did not match our assumptions, and the
    honest answer is the original text rather than silence.

    That guard is not hypothetical. A reasoning model whose reply began "Thinking: …" with no
    blank line matched the leading-prefix pattern to the end of the string and was erased. The
    caller saw an empty string, logged "returned empty response", retried, split the batch and
    retried again — every attempt destroyed the same way. A run that should have taken minutes
    took over half an hour and fell back to mechanical labels, while a healthy gateway answered
    every single request correctly.
    """
    if not text:
        return text
    out = text
    out = _TAG_BLOCK_RE.sub("", out)
    out = _FENCE_BLOCK_RE.sub("", out)
    out = _LEADING_PREFIX_RE.sub("", out)
    out = out.strip()
    if not out:
        logger.debug("think-stripping removed the whole response (%d chars); keeping the "
                     "original — the reply did not match the expected shape", len(text))
        return text.strip()
    return out
