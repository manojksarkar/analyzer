"""Unified LLM client package.

The single LlmClient supports both a corporate OpenAI-compatible gateway
and a local Ollama server. Both routes go through the same retry, think-
section stripping, and token tracking pipeline.

Public API:
    LlmClient            - the client class (legacy + new constructors)
    from_config          - build a client from a config dict
    strip_think_section  - response post-processor
    tokens               - process-wide token counter (record / format_report)
    TokenCounter         - token counting (tiktoken or char fallback)
    ContextBudget        - declarative per-section token budget allocator
    resolve_max_tokens   - derive max context tokens from config
    extract_and_validate - robust JSON extraction + schema validation
    self_review          - generate → review → revise cycle
    ensemble_generate    - multi-temperature + synthesis
"""

from . import tokens
from .budget import ContextBudget, resolve_max_tokens
from .client import LlmClient, from_config
from .review import ensemble_generate, self_review
from .structured_output import extract_and_validate, parse_label_response
from .think import strip_think_section
from .token_counter import TokenCounter, get_counter

__all__ = [
    "LlmClient",
    "from_config",
    "strip_think_section",
    "tokens",
    "TokenCounter",
    "get_counter",
    "ContextBudget",
    "resolve_max_tokens",
    "extract_and_validate",
    "parse_label_response",
    "self_review",
    "ensemble_generate",
]
