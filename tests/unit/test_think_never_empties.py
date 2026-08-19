"""`strip_think_section` must never turn a real answer into nothing.

This destroyed a production run. A reasoning model (`openai/gpt-oss-120b`) replies with a
"Thinking: …" preamble; when that preamble contained no blank line, the leading-prefix pattern
matched to the END of the string via `\Z` and deleted the entire response.

What the pipeline then saw was an empty string, so it logged "returned empty response", retried,
split the batch and retried again — every attempt destroyed identically. One commit took 2062
seconds and produced mechanical fallback labels, while `tools/check_llm.py` showed the gateway
answering every request correctly. Nothing was broken except this function.

The rule: stripping is a CLEANUP, not a filter. If the patterns consume everything, the reply
did not match our assumptions and the honest result is the original text.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

_ENGINE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "engine")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from llm_core.think import strip_think_section as strip   # noqa: E402


class TestNothingIsEverDestroyed:
    @pytest.mark.parametrize("text,why", [
        ("Thinking: it adds two numbers and returns the sum.", "preamble, no blank line"),
        ("Think: analysing...\nThe function computes a checksum.", "preamble then answer"),
        ("<think>reasoning here</think>", "the whole reply is a think block"),
        ("```think\njust reasoning\n```", "the whole reply is a think fence"),
        ("thinking: lowercase and unterminated", "case-insensitive, no terminator"),
    ])
    def test_a_non_empty_reply_never_becomes_empty(self, text, why):
        out = strip(text)
        assert out, f"the entire response was destroyed ({why})"


class TestRealStrippingStillWorks:
    """The guard must not turn the function into a no-op — the reasoning still has to go, or it
    leaks into descriptions and DOCX cells."""

    def test_a_think_block_followed_by_an_answer_is_removed(self):
        assert strip("<think>internal reasoning</think>\nThe answer.") == "The answer."

    def test_a_preamble_ending_in_a_blank_line_is_removed(self):
        assert strip("Thinking: step one.\n\nThe function computes a checksum.") == \
            "The function computes a checksum."

    def test_a_fenced_think_block_before_an_answer_is_removed(self):
        assert strip("```think\nreasoning\n```\nThe answer.") == "The answer."

    def test_plain_answers_pass_through_untouched(self):
        for text in ('{"n1": "Reads input"}', "Adds two numbers.", "Returns the checksum."):
            assert strip(text) == text

    def test_the_word_thinking_mid_sentence_is_not_a_preamble(self):
        text = "The function is thinking: no, it just adds numbers."
        assert strip(text) == text


class TestEdges:
    def test_empty_and_none_are_returned_as_is(self):
        assert strip("") == ""
        assert strip(None) is None

    def test_whitespace_only_stays_falsy(self):
        """Not a real answer, so there is nothing to preserve."""
        assert not strip("   \n  ")
