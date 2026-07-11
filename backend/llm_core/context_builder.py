"""Budget-aware context assembly with graceful degradation.

When the total context for an LLM prompt exceeds the token budget, rather
than silently dropping items (callees, callers, types), we *degrade* each
item through a ladder of decreasing detail levels:

    Level 0: Full source + description
    Level 1: Signature + 3-line description
    Level 2: Signature + 1-line purpose
    Level 3: Signature only
    Level 4: Qualified name only

Strategy: start all items at Level 0.  If the total exceeds budget, promote
the *lowest-priority* item one level.  Repeat until it fits.  This preserves
**breadth over depth** — the LLM always sees every callee even if some are
name-only.

Priority ranking (higher = kept at more detail):
  - Callees:  by call-site count in target function (most-called first)
  - Callers:  by public/exported status, then by total caller count
  - Types:    by usage frequency in target function source
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional

from .token_counter import TokenCounter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Degradation levels
# ---------------------------------------------------------------------------

class DetailLevel(IntEnum):
    """Degradation ladder — lower value = more detail."""
    FULL = 0       # Full source + description
    DETAILED = 1   # Signature + 3-line description
    BRIEF = 2      # Signature + 1-line purpose
    SIGNATURE = 3  # Signature only
    NAME = 4       # Qualified name only


# ---------------------------------------------------------------------------
# Context item — one entry in a context section
# ---------------------------------------------------------------------------

@dataclass
class ContextItem:
    """One item (callee, caller, type, global) to fit into a budget."""
    name: str
    signature: str = ""
    description: str = ""
    source: str = ""
    priority: float = 0.0  # higher = more important = degraded last

    # Pre-rendered text at each detail level.  Populated lazily.
    _rendered: Dict[DetailLevel, str] = field(default_factory=dict, repr=False)

    def render(self, level: DetailLevel) -> str:
        """Return the text representation at the given detail level."""
        if level in self._rendered:
            return self._rendered[level]

        if level == DetailLevel.FULL:
            parts = []
            if self.signature:
                parts.append(self.signature)
            if self.description:
                parts.append(self.description)
            if self.source:
                parts.append(self.source)
            text = "\n".join(parts) if parts else self.name

        elif level == DetailLevel.DETAILED:
            parts = [self.signature or self.name]
            if self.description:
                # Keep up to 3 lines of description
                lines = self.description.strip().splitlines()
                parts.append("\n".join(lines[:3]))
            text = "\n".join(parts)

        elif level == DetailLevel.BRIEF:
            parts = [self.signature or self.name]
            if self.description:
                first_line = self.description.strip().splitlines()[0]
                parts.append(first_line)
            text = "\n".join(parts)

        elif level == DetailLevel.SIGNATURE:
            text = self.signature or self.name

        else:  # NAME
            text = self.name

        self._rendered[level] = text
        return text


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------

class ContextBuilder:
    """Budget-aware assembly of context sections for LLM prompts."""

    def __init__(self, counter: TokenCounter) -> None:
        self._counter = counter

    def fit_items(
        self,
        items: List[ContextItem],
        budget: int,
        *,
        header: str = "",
        separator: str = "\n\n",
        min_level: DetailLevel = DetailLevel.NAME,
    ) -> str:
        """Fit a list of ContextItems into a token budget.

        Returns the assembled text.  Items are degraded from lowest-priority
        first until the total fits.  If even all items at NAME level don't
        fit, items are dropped from the lowest-priority end.

        Parameters
        ----------
        items : list[ContextItem]
            Items to fit, in any order (sorted by priority internally).
        budget : int
            Maximum tokens for the assembled output.
        header : str
            Optional header line prepended to the output.
        separator : str
            Separator between items.
        min_level : DetailLevel
            The coarsest level to degrade to before dropping items entirely.
        """
        if not items or budget <= 0:
            return ""

        # Sort by priority descending — highest priority first
        sorted_items = sorted(items, key=lambda x: x.priority, reverse=True)

        # Start all items at FULL detail
        levels: List[DetailLevel] = [DetailLevel.FULL] * len(sorted_items)

        header_tokens = self._counter.count(header) if header else 0
        sep_tokens = self._counter.count(separator)

        def _total_tokens() -> int:
            total = header_tokens
            for i, item in enumerate(sorted_items):
                if i > 0:
                    total += sep_tokens
                total += self._counter.count(item.render(levels[i]))
            return total

        # Degrade loop: promote lowest-priority items one level at a time
        while _total_tokens() > budget:
            # Find the lowest-priority item that can still be degraded
            degraded = False
            for i in range(len(sorted_items) - 1, -1, -1):
                if levels[i] < min_level:
                    levels[i] = DetailLevel(levels[i] + 1)
                    degraded = True
                    break
            if not degraded:
                # All items at min_level — start dropping from lowest priority
                break

        # If still over budget, drop items from lowest priority
        while len(sorted_items) > 0 and _total_tokens() > budget:
            sorted_items.pop()
            levels.pop()

        if not sorted_items:
            return ""

        # Assemble final text
        parts = []
        if header:
            parts.append(header)
        for i, item in enumerate(sorted_items):
            parts.append(item.render(levels[i]))

        result = separator.join(parts)

        # Log degradation stats
        level_counts = {}
        for lv in levels:
            level_counts[lv.name] = level_counts.get(lv.name, 0) + 1
        logger.debug(
            "ContextBuilder: fit %d/%d items into %d tokens — levels: %s",
            len(sorted_items), len(items), budget, level_counts,
        )

        return result

    # ------------------------------------------------------------------
    # Typed convenience methods
    # ------------------------------------------------------------------

    def fit_callees(
        self,
        callees: List[ContextItem],
        budget: int,
    ) -> str:
        """Fit callee context into budget.

        Priority: by call-site count (encoded in item.priority).
        """
        return self.fit_items(
            callees,
            budget,
            header="[Called Functions]",
            separator="\n\n",
        )

    def fit_callers(
        self,
        callers: List[ContextItem],
        budget: int,
    ) -> str:
        """Fit caller context into budget.

        Priority: by public/exported status, then caller count.
        """
        return self.fit_items(
            callers,
            budget,
            header="[Callers — who calls this function and why]",
            separator="\n\n",
        )

    def fit_types(
        self,
        types: List[ContextItem],
        budget: int,
    ) -> str:
        """Fit related type definitions into budget.

        Priority: by usage frequency in the target function.
        """
        return self.fit_items(
            types,
            budget,
            header="[Related Types]",
            separator="\n\n",
        )

    def fit_globals(
        self,
        globals_items: List[ContextItem],
        budget: int,
    ) -> str:
        """Fit global variable context into budget."""
        return self.fit_items(
            globals_items,
            budget,
            header="[Global Variables Accessed]",
            separator="\n",
        )

    def fit_siblings(
        self,
        siblings: List[ContextItem],
        budget: int,
    ) -> str:
        """Fit sibling function signatures into budget."""
        return self.fit_items(
            siblings,
            budget,
            header="[Other Functions in Same File]",
            separator="\n",
            min_level=DetailLevel.SIGNATURE,
        )
