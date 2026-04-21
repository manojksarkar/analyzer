"""Unit tests for src/llm_core/budget.py — ContextBudget and resolve_max_tokens."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from llm_core.budget import TASK_RATIOS, DEFAULT_SAFETY_MARGIN, ContextBudget, resolve_max_tokens
from llm_core.token_counter import TokenCounter


def _budget(task="function_description", max_tokens=10_000):
    return ContextBudget(max_tokens=max_tokens, task=task, counter=TokenCounter())


class TestTaskRatios:
    def test_all_tasks_sum_to_one(self):
        for task, ratios in TASK_RATIOS.items():
            total = sum(ratios.values())
            assert abs(total - 1.0) < 0.02, f"{task!r} ratios sum to {total:.4f}"

    def test_every_task_has_output_reserve(self):
        for task in TASK_RATIOS:
            assert "output_reserve" in TASK_RATIOS[task], f"{task!r} missing output_reserve"


class TestContextBudget:
    def test_unknown_task_raises(self):
        with pytest.raises(ValueError, match="Unknown task"):
            ContextBudget(max_tokens=10_000, task="bogus", counter=TokenCounter())

    def test_safety_margin_reduces_effective_input(self):
        b = _budget(max_tokens=10_000)
        assert b.effective_input() == int(10_000 * (1 - DEFAULT_SAFETY_MARGIN))

    def test_allocate_proportional_to_ratio(self):
        b = _budget(max_tokens=10_000)
        for section, ratio in TASK_RATIOS["function_description"].items():
            assert b.allocate(section) == int(b.effective_input() * ratio)

    def test_allocate_unknown_section_raises(self):
        with pytest.raises(KeyError):
            _budget().allocate("nosuchsection")

    def test_sections_returns_independent_copy(self):
        b = _budget()
        s = b.sections()
        s["callees"] = 0
        assert b.allocate("callees") != 0

    def test_remaining_subtracts_used(self):
        b = _budget(max_tokens=10_000)
        assert b.remaining({"callees": 500}) == b.effective_input() - 500

    def test_remaining_clamps_to_zero(self):
        assert _budget(max_tokens=1_000).remaining({"callees": 999_999}) == 0


class TestResolveMaxTokens:
    def test_ollama_auto_is_num_ctx_minus_512(self):
        assert resolve_max_tokens({"provider": "ollama", "numCtx": 8192, "maxContextTokens": None}) == 8192 - 512

    def test_openai_auto_is_127488(self):
        assert resolve_max_tokens({"provider": "openai", "numCtx": 8192, "maxContextTokens": None}) == 127_488

    def test_explicit_openai_returned_as_is(self):
        assert resolve_max_tokens({"provider": "openai", "numCtx": 8192, "maxContextTokens": 50_000}) == 50_000

    def test_explicit_ollama_clamped_when_exceeds_num_ctx(self):
        result = resolve_max_tokens({"provider": "ollama", "numCtx": 4096, "maxContextTokens": 99_999})
        assert result == max(1024, 4096 - 256)
