"""Robust JSON extraction, repair, and schema validation for LLM outputs.

LLMs frequently wrap JSON in markdown fences, add explanatory text, use
single quotes, or emit trailing commas.  This module handles all the
common failure modes so call sites don't have to reimplement the same
extraction logic over and over.

Usage:
    from llm_core.structured_output import extract_and_validate

    data = extract_and_validate(raw_response, expected_keys={"N1", "N2", "N3"})
    if data is None:
        # unrecoverable parse failure — fall back to rule-based labels
        ...
    else:
        # data is a dict with at least the expected keys
        ...
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_json(text: str) -> Optional[str]:
    """Extract the first complete JSON object from a potentially noisy response.

    Handles:
      - ```json ... ``` markdown fences
      - ``` ... ``` unlabelled fences
      - leading/trailing explanatory text
      - missing closing brace (tries to auto-complete)

    Returns the raw JSON substring, or None if no object-like structure found.
    """
    if not text:
        return None

    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```", "", cleaned)

    # Find first {
    start = cleaned.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(start, len(cleaned)):
        c = cleaned[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        # Unclosed object — try to auto-complete by appending missing braces
        missing = depth
        if missing > 0:
            candidate = cleaned[start:] + ("}" * missing)
            logger.debug("extract_json: auto-appended %d closing braces", missing)
            return candidate
        return None

    return cleaned[start:end]


def repair_json(text: str) -> str:
    """Apply common repairs to malformed JSON.

    - Remove trailing commas before } or ]
    - Replace single-quoted string delimiters with double quotes (when safe)
    - Replace smart quotes
    """
    if not text:
        return text

    # Replace smart quotes with ASCII quotes
    result = text.replace("\u201c", '"').replace("\u201d", '"')
    result = result.replace("\u2018", "'").replace("\u2019", "'")

    # Remove trailing commas: ,\s*} or ,\s*]
    result = re.sub(r",(\s*[}\]])", r"\1", result)

    # Best-effort single → double quote conversion.  Only safe when the value
    # contains no apostrophes.  Skip if result already looks like valid JSON.
    try:
        json.loads(result)
        return result
    except json.JSONDecodeError:
        pass

    # Convert 'key': to "key":
    result = re.sub(r"'([^'\\]*)'(\s*:)", r'"\1"\2', result)
    # Convert : 'value' to : "value" (only when no internal quotes)
    result = re.sub(r"(:\s*)'([^'\\]*)'", r'\1"\2"', result)

    return result


def extract_and_validate(
    raw: str,
    *,
    expected_keys: Optional[Set[str]] = None,
    required_keys: Optional[Set[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Extract JSON from *raw*, repair it, parse it, and validate keys.

    Parameters
    ----------
    raw : str
        The raw LLM response text.
    expected_keys : set[str], optional
        If provided, the parsed dict must contain at least these keys.
        Missing keys cause the result to still be returned (log warning).
        Use this for batches where some missing entries are acceptable.
    required_keys : set[str], optional
        If provided, the parsed dict must contain all these keys.
        Missing any of them causes None to be returned.
        Use this for strict schemas.

    Returns
    -------
    dict or None
        The parsed dict on success, None on unrecoverable failure.
    """
    if not raw:
        return None

    extracted = extract_json(raw)
    if not extracted:
        logger.debug("extract_and_validate: no JSON object found in response")
        return None

    # Try parsing as-is first
    try:
        data = json.loads(extracted)
    except json.JSONDecodeError:
        # Try repair
        repaired = repair_json(extracted)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError as exc:
            logger.debug("extract_and_validate: JSON parse failed even after repair: %s", exc)
            return None

    if not isinstance(data, dict):
        logger.debug("extract_and_validate: parsed value is not a dict (type=%s)", type(data).__name__)
        return None

    if required_keys:
        missing = required_keys - set(data.keys())
        if missing:
            logger.debug("extract_and_validate: required keys missing: %s", sorted(missing))
            return None

    if expected_keys:
        missing = expected_keys - set(data.keys())
        if missing:
            logger.debug(
                "extract_and_validate: expected keys missing (partial ok): %s",
                sorted(missing),
            )

    return data


# ---------------------------------------------------------------------------
# Convenience wrappers for common use cases
# ---------------------------------------------------------------------------

def parse_label_response(raw: str, required_ids: Set[str]) -> Dict[str, Any]:
    """Parse a flowchart node-labeling response.

    Returns a dict with at most the required_ids as keys.  Missing keys are
    simply absent from the result (caller must handle).  Returns {} on
    unrecoverable failure.
    """
    data = extract_and_validate(raw, expected_keys=required_ids)
    if data is None:
        return {}
    return {k: v for k, v in data.items() if k in required_ids}
