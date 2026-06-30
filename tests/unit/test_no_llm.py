"""Unit tests for the true `--no-llm` kill switch (M-D)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.generate import apply_no_llm  # noqa: E402


def test_apply_no_llm_disables_descriptions_and_behaviour():
    cfg = {"llm": {"descriptions": True, "behaviourNames": True, "defaultModel": "m"}}
    apply_no_llm(cfg)
    assert cfg["llm"]["descriptions"] is False
    assert cfg["llm"]["behaviourNames"] is False
    assert cfg["llm"]["defaultModel"] == "m"        # leaves other settings intact


def test_apply_no_llm_creates_llm_section_when_missing():
    cfg = {}
    apply_no_llm(cfg)
    assert cfg["llm"]["descriptions"] is False
    assert cfg["llm"]["behaviourNames"] is False
