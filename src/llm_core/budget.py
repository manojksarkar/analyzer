"""Declarative context-budget allocation for LLM prompts.

Every LLM call in the project flows through a ContextBudget that
partitions the available token window into named sections.  Changing
``max_context_tokens`` in the config rescales every section automatically.

Usage:
    counter = TokenCounter(model="gpt-oss-120b")
    budget  = ContextBudget(max_tokens=128000, task="function_description", counter=counter)
    callee_budget = budget.allocate("callees")   # e.g. 18 000 tokens
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict

from .token_counter import TokenCounter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-task section ratios.  Must sum to 1.0 (enforced by assertion).
#
# Adding a new task type means adding an entry here — no other code changes.
# ---------------------------------------------------------------------------

TASK_RATIOS: Dict[str, Dict[str, float]] = {

    # Phase 2 — function descriptions (llm_enrichment.py)
    "function_description": {
        "system_prompt":    0.05,
        "few_shot":         0.12,
        "repo_map":         0.10,
        "function_source":  0.20,
        "callees":          0.18,
        "callers":          0.10,
        "types_globals":    0.08,
        "siblings":         0.05,
        "instructions":     0.05,
        "output_reserve":   0.07,
    },

    # Phase 2 — refined (Pass 2) function descriptions
    "function_description_refined": {
        "system_prompt":    0.05,
        "few_shot":         0.10,
        "repo_map":         0.08,
        "function_source":  0.15,
        "prior_description": 0.05,
        "callees":          0.18,
        "callers":          0.15,
        "types_globals":    0.08,
        "instructions":     0.05,
        "output_reserve":   0.11,
    },

    # Phase 2 — global variable descriptions
    "variable_description": {
        "system_prompt":    0.05,
        "few_shot":         0.10,
        "declaration":      0.05,
        "write_sites":      0.25,
        "read_sites":       0.25,
        "containing_file":  0.15,
        "related_functions": 0.08,
        "instructions":     0.02,
        "output_reserve":   0.05,
    },

    # Phase 2 — behaviour input/output names
    "behaviour_names": {
        "system_prompt":    0.05,
        "few_shot":         0.10,
        "function_source":  0.35,
        "params_globals":   0.20,
        "abbreviations":    0.10,
        "instructions":     0.10,
        "output_reserve":   0.10,
    },

    # Phase 2 hierarchy summarizer — function summaries (batched)
    "function_summary": {
        "system_prompt":    0.08,
        "function_batch":   0.70,
        "instructions":     0.07,
        "output_reserve":   0.15,
    },

    # Phase 2 hierarchy summarizer — file summaries
    "file_summary": {
        "system_prompt":    0.05,
        "few_shot":         0.08,
        "repo_map":         0.10,
        "file_source":      0.40,
        "function_descriptions": 0.15,
        "module_context":   0.10,
        "instructions":     0.05,
        "output_reserve":   0.07,
    },

    # Phase 2 hierarchy summarizer — module summaries
    "module_summary": {
        "system_prompt":    0.05,
        "few_shot":         0.07,
        "repo_map":         0.12,
        "file_summaries":   0.45,
        "key_functions":    0.13,
        "instructions":     0.05,
        "output_reserve":   0.13,
    },

    # Phase 2 hierarchy summarizer — project summary
    "project_summary": {
        "system_prompt":    0.05,
        "few_shot":         0.05,
        "project_structure": 0.10,
        "module_summaries": 0.60,
        "entry_points":     0.10,
        "instructions":     0.05,
        "output_reserve":   0.05,
    },

    # Phase 3 — flowchart CFG node labeling (per batch)
    "cfg_node_labeling": {
        "system_prompt":    0.12,
        "few_shot":         0.08,
        "context_packet":   0.25,
        "function_source":  0.12,
        "nodes_batch":      0.25,
        "callee_context":   0.08,
        "output_reserve":   0.10,
    },

    # Phase 3 — flowchart coherence pass (all labels)
    "cfg_coherence": {
        "system_prompt":    0.08,
        "function_purpose": 0.10,
        "all_labels":       0.55,
        "instructions":     0.10,
        "output_reserve":   0.17,
    },

    # Phase 3 — CFG simplification pass
    "cfg_simplification": {
        "system_prompt":    0.08,
        "function_description": 0.10,
        "function_source":  0.25,
        "cfg_structure":    0.35,
        "instructions":     0.07,
        "output_reserve":   0.15,
    },

    # Self-review (applies to any task output)
    "self_review": {
        "system_prompt":    0.05,
        "original_output":  0.15,
        "source_evidence":  0.55,
        "review_criteria":  0.10,
        "instructions":     0.05,
        "output_reserve":   0.10,
    },

    # Ensemble synthesis (module/project summaries)
    "ensemble_synthesis": {
        "system_prompt":    0.05,
        "candidates":       0.40,
        "source_evidence":  0.40,
        "instructions":     0.05,
        "output_reserve":   0.10,
    },
}


# ---------------------------------------------------------------------------
# Safety margin — fraction of the total context window reserved as headroom
# for tokenizer drift between our count and the server's count.
# ---------------------------------------------------------------------------

DEFAULT_SAFETY_MARGIN = 0.10   # 10%


# ---------------------------------------------------------------------------
# ContextBudget
# ---------------------------------------------------------------------------

@dataclass
class ContextBudget:
    """Partition a token window into named sections for one task type.

    Parameters
    ----------
    max_tokens : int
        Total context window (e.g. ``numCtx`` for Ollama, 128000 for OpenAI).
    task : str
        Task type key into ``TASK_RATIOS``.
    counter : TokenCounter
        Used by callers for measuring actual content against the allocation.
    safety_margin : float
        Fraction of *max_tokens* reserved as headroom (default 10 %).
    """

    max_tokens: int
    task: str
    counter: TokenCounter
    safety_margin: float = DEFAULT_SAFETY_MARGIN
    _allocations: Dict[str, int] = field(init=False, repr=False, default_factory=dict)

    def __post_init__(self) -> None:
        ratios = TASK_RATIOS.get(self.task)
        if ratios is None:
            raise ValueError(
                f"Unknown task type {self.task!r}. "
                f"Available: {sorted(TASK_RATIOS)}"
            )
        total_ratio = sum(ratios.values())
        assert abs(total_ratio - 1.0) < 0.02, (
            f"Ratios for {self.task!r} sum to {total_ratio:.3f}, expected ~1.0"
        )

        effective = int(self.max_tokens * (1 - self.safety_margin))
        self._allocations = {
            section: int(effective * ratio)
            for section, ratio in ratios.items()
        }
        logger.debug(
            "ContextBudget(%s): %d effective tokens from %d total (%.0f%% margin)",
            self.task, effective, self.max_tokens, self.safety_margin * 100,
        )

    def allocate(self, section: str) -> int:
        """Return the token budget for *section*.

        Raises KeyError if *section* is not defined for this task type.
        """
        if section not in self._allocations:
            raise KeyError(
                f"Section {section!r} not in task {self.task!r}. "
                f"Available: {sorted(self._allocations)}"
            )
        return self._allocations[section]

    def effective_input(self) -> int:
        """Total tokens available for prompt content (after safety margin)."""
        return int(self.max_tokens * (1 - self.safety_margin))

    def sections(self) -> Dict[str, int]:
        """Return a copy of all section → budget mappings."""
        return dict(self._allocations)

    def remaining(self, used: Dict[str, int]) -> int:
        """Tokens remaining after subtracting *used* section counts."""
        total_used = sum(used.values())
        return max(0, self.effective_input() - total_used)


# ---------------------------------------------------------------------------
# Convenience: derive max_context_tokens from config
# ---------------------------------------------------------------------------

def resolve_max_tokens(llm_cfg: Dict) -> int:
    """Derive max_context_tokens from the LLM config.

    Expects *llm_cfg* to come from ``core.config.load_llm_config`` so the
    required fields (``provider``, ``numCtx``) are already validated — this
    function does NOT silently default them.

    Priority:
      1. Explicit ``maxContextTokens`` in config (int) — used as-is
      2. ``numCtx - 512`` for Ollama (reserve headroom for output)
      3. 127488 for OpenAI (128K - 512 reserve)
    """
    explicit = llm_cfg.get("maxContextTokens")
    if explicit is not None:
        return int(explicit)

    provider = llm_cfg["provider"].lower()
    if provider == "openai":
        return 127488
    return max(1024, int(llm_cfg["numCtx"]) - 512)
