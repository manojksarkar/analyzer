"""Self-review and ensemble generation patterns.

Two related patterns that improve quality at the cost of extra LLM calls:

1. **self_review(client, ...)** — generate → review → revise cycle.
   The model is shown its own output and asked to critique it, then revise
   based on the critique.  3 LLM calls per entity.  Applied selectively:
   function descriptions for non-trivial functions, module summaries, file
   summaries — not for every tiny helper.

2. **ensemble_generate(client, ...)** — generate at 3 temperatures, then ask
   the model to synthesise the three drafts into a single best version.
   4 LLM calls per entity.  Applied to high-visibility text only: module
   summaries and the project summary (not per-function descriptions).

Both patterns return ``None`` on unrecoverable failure so callers can fall
back to the single-shot result.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from .client import LlmClient
from .structured_output import extract_and_validate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Self-review (generate → review → revise)
# ---------------------------------------------------------------------------

_REVIEW_SYSTEM = (
    "You are a strict technical reviewer for C++ codebase documentation. "
    "Your job is to find concrete issues with a proposed description so that "
    "it can be revised. Focus on accuracy, completeness, voice, and clarity."
)

_REVIEW_USER_TEMPLATE = (
    "Review the following description against the evidence and report issues.\n\n"
    "[Evidence]\n{evidence}\n\n"
    "[Proposed Description]\n{draft}\n\n"
    "Check for:\n"
    "  1. Accuracy — does it contradict the evidence or invent behaviour?\n"
    "  2. Completeness — does it miss important behaviours, side effects, or error paths?\n"
    "  3. Voice — is it active, direct, and in the present tense?\n"
    "  4. Abstraction — does it narrate line-by-line instead of explaining intent?\n"
    "  5. Length — is it within 1-3 sentences and free of filler?\n\n"
    'Return ONLY a JSON object: {{"verdict": "OK"|"REVISE", "issues": ["..."]}}\n'
    'If the description is good enough, return {{"verdict": "OK", "issues": []}}.'
)

_REVISE_SYSTEM = (
    "You are a senior C++ engineer rewriting a description. Apply the reviewer's "
    "feedback to produce a clear, accurate, 1-3 sentence description. Return only "
    "the revised description — no preamble, no JSON, no quotes."
)

_REVISE_USER_TEMPLATE = (
    "[Evidence]\n{evidence}\n\n"
    "[Original Description]\n{draft}\n\n"
    "[Reviewer Issues]\n{issues}\n\n"
    "Rewrite the description addressing every issue. Keep it to 1-3 sentences."
)


def self_review(
    client: LlmClient,
    *,
    draft: str,
    evidence: str,
    max_evidence_chars: int = 4000,
) -> Optional[str]:
    """Run a generate → review → revise cycle on *draft*.

    Parameters
    ----------
    client : LlmClient
        Used for both the review and revise calls.
    draft : str
        The original description to review.
    evidence : str
        The source evidence (function body, signature, callees, etc.) the
        reviewer should check the draft against.
    max_evidence_chars : int
        Hard cap on evidence passed to the reviewer, to keep the review
        prompt itself manageable.

    Returns
    -------
    str or None
        The revised description, the original *draft* if the reviewer says
        "OK", or None if either review call fails unrecoverably.
    """
    if not draft or not draft.strip():
        return draft

    evidence = (evidence or "")[:max_evidence_chars]

    # ---- Review call ----
    review_user = _REVIEW_USER_TEMPLATE.format(evidence=evidence, draft=draft)
    review_raw = client.generate(_REVIEW_SYSTEM, review_user)
    if not review_raw:
        logger.debug("self_review: review call returned nothing; keeping draft")
        return draft

    review = extract_and_validate(
        review_raw,
        required_keys={"verdict"},
    )
    if review is None:
        logger.debug("self_review: review JSON unparseable; keeping draft")
        return draft

    verdict = str(review.get("verdict", "")).strip().upper()
    issues = review.get("issues") or []
    if verdict == "OK" or not issues:
        return draft

    # ---- Revise call ----
    issue_lines = "\n".join(f"  - {str(it).strip()}" for it in issues if str(it).strip())
    if not issue_lines:
        return draft

    revise_user = _REVISE_USER_TEMPLATE.format(
        evidence=evidence,
        draft=draft,
        issues=issue_lines,
    )
    revised = client.generate(_REVISE_SYSTEM, revise_user)
    if not revised or not revised.strip():
        logger.debug("self_review: revise call returned nothing; keeping draft")
        return draft

    # Strip accidental JSON or markdown fences
    cleaned = revised.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.lstrip("`")
        cleaned = cleaned.lstrip("json").lstrip()
        cleaned = cleaned.rstrip("`").strip()
    return cleaned or draft


# ---------------------------------------------------------------------------
# Ensemble (multi-temperature + synthesis)
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = (
    "You are a senior technical writer producing a single best version from "
    "several draft descriptions. The drafts were produced at different sampling "
    "temperatures. Your job is to reconcile them into one concise, accurate, "
    "well-voiced description that incorporates the strongest points of each."
)

_SYNTHESIS_USER_TEMPLATE = (
    "Here are {n} drafts of the same description.\n\n"
    "{drafts}\n\n"
    "Synthesise them into ONE description that:\n"
    "  - Keeps only facts that at least two drafts agree on (unless a single "
    "draft is clearly more specific and consistent with the others).\n"
    "  - Uses active voice and present tense.\n"
    "  - Stays within 1-3 sentences for functions, or 2-4 sentences for "
    "module/file/project summaries.\n"
    "  - Does not mention that this was produced from multiple drafts.\n\n"
    "Return ONLY the synthesised description. No preamble, no JSON, no quotes."
)


def ensemble_generate(
    client: LlmClient,
    *,
    system: str,
    user: str,
    temperatures: Optional[List[float]] = None,
) -> Optional[str]:
    """Generate at multiple temperatures then synthesise a single best version.

    Parameters
    ----------
    client : LlmClient
        Must support ``call(messages, temperature=)``.
    system : str
        System prompt for the initial draft calls.
    user : str
        User prompt for the initial draft calls.
    temperatures : list[float], optional
        Temperatures to sample at.  Defaults to ``[0.0, 0.3, 0.7]``.

    Returns
    -------
    str or None
        The synthesised description, or the first successful single draft
        as a fallback, or None if every call fails.
    """
    temps = temperatures if temperatures is not None else [0.0, 0.3, 0.7]

    base_messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    drafts: List[str] = []
    for t in temps:
        try:
            raw = client.call(base_messages, temperature=t)
        except Exception as exc:  # pragma: no cover — network/provider errors
            logger.debug("ensemble_generate: draft at T=%.1f failed: %s", t, exc)
            continue
        if raw and raw.strip():
            drafts.append(raw.strip())

    if not drafts:
        return None
    if len(drafts) == 1:
        return drafts[0]

    # Synthesis call — serialise drafts with separators
    draft_block = "\n\n".join(
        f"[Draft {i + 1}]\n{d}" for i, d in enumerate(drafts)
    )
    synth_user = _SYNTHESIS_USER_TEMPLATE.format(n=len(drafts), drafts=draft_block)

    try:
        synth = client.generate(_SYNTHESIS_SYSTEM, synth_user)
    except Exception as exc:  # pragma: no cover
        logger.debug("ensemble_generate: synthesis failed: %s", exc)
        return drafts[0]

    if not synth or not synth.strip():
        return drafts[0]
    return synth.strip()
