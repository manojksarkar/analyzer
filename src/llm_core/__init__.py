"""Unified LLM client package.

The single LlmClient supports both a corporate OpenAI-compatible gateway
and a local Ollama server. Both routes go through the same retry, think-
section stripping, and token tracking pipeline.

Public API:
    LlmClient            - the client class (legacy + new constructors)
    from_config          - build a client from a config dict
    strip_think_section  - response post-processor
    tokens               - process-wide token counter (record / format_report)
"""

from . import tokens
from .client import LlmClient, from_config
from .think import strip_think_section

__all__ = ["LlmClient", "from_config", "strip_think_section", "tokens"]
