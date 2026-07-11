"""Few-shot example pool for LLM prompts.

Hand-curated examples teach the LLM output format and style.  Each example
is a JSON file with tags, an input context snippet, and an ideal output.

The pool ranks examples by keyword overlap with the current target and
greedily fills the budget.

Directory layout:
    few_shot_examples/
      descriptions/          # function description examples
        01_state_machine.json
        02_io_wrapper.json
        ...
      labels/                # flowchart node labeling examples
      globals/               # global variable description examples
      behaviour_names/       # behaviour I/O name examples

Each JSON file:
    {
        "tags": ["init", "struct", "logging"],
        "input_context": "...",     // the prompt snippet
        "ideal_output": "..."       // the gold-standard output
    }
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional, Set

from .token_counter import TokenCounter

logger = logging.getLogger(__name__)


class FewShotPool:
    """Load, rank, and inject few-shot examples into prompts."""

    def __init__(self, examples_dir: str) -> None:
        self._base = examples_dir
        self._cache: Dict[str, List[Dict]] = {}  # task → loaded examples

    def select(
        self,
        task: str,
        target_keywords: Set[str],
        budget: int,
        counter: TokenCounter,
    ) -> str:
        """Select few-shot examples that fit in *budget* tokens.

        Parameters
        ----------
        task : str
            Task type: "descriptions", "labels", "globals", "behaviour_names".
        target_keywords : set[str]
            Keywords extracted from the current target (callee names, param
            types, etc.) used to rank examples by relevance.
        budget : int
            Maximum tokens for the few-shot block.
        counter : TokenCounter
            Token counter for measuring.

        Returns
        -------
        str
            Formatted few-shot examples block, or "" if none fit.
        """
        examples = self._load_task(task)
        if not examples:
            return ""

        # Rank by keyword overlap (higher = more relevant)
        scored = []
        for ex in examples:
            tags = set(ex.get("tags", []))
            overlap = len(tags & target_keywords)
            scored.append((overlap, ex))
        scored.sort(key=lambda x: x[0], reverse=True)

        # Greedy fill: add examples until budget is exhausted
        parts = []
        total_tokens = 0
        header = "=== FEW-SHOT EXAMPLES ==="
        header_tokens = counter.count(header)

        for _, ex in scored:
            block = self._format_example(ex)
            block_tokens = counter.count(block)
            if total_tokens + block_tokens + header_tokens > budget:
                break
            parts.append(block)
            total_tokens += block_tokens

        if not parts:
            return ""

        return header + "\n\n" + "\n\n---\n\n".join(parts)

    def _load_task(self, task: str) -> List[Dict]:
        """Load all example files for a task (cached)."""
        if task in self._cache:
            return self._cache[task]

        task_dir = os.path.join(self._base, task)
        examples = []
        if not os.path.isdir(task_dir):
            logger.debug("No few-shot examples dir: %s", task_dir)
            self._cache[task] = examples
            return examples

        for fname in sorted(os.listdir(task_dir)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(task_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("input_context") and data.get("ideal_output"):
                    examples.append(data)
            except (json.JSONDecodeError, IOError) as exc:
                logger.warning("Failed to load few-shot example %s: %s", path, exc)

        logger.debug("Loaded %d few-shot examples for task %r", len(examples), task)
        self._cache[task] = examples
        return examples

    @staticmethod
    def _format_example(ex: Dict) -> str:
        """Format one example as an input/output pair."""
        lines = []
        lines.append("Input:")
        lines.append(ex["input_context"])
        lines.append("")
        lines.append("Output:")
        lines.append(ex["ideal_output"])
        return "\n".join(lines)
