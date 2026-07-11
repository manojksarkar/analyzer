#!/usr/bin/env python3
"""LLM integration for generating call descriptions in behavior diagrams."""

from typing import Callable, Dict, Optional


class CallDescriptionGenerator:
    """Generates descriptions for function calls using LLM when available."""

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the call description generator.

        Args:
            config: Optional configuration dictionary for LLM calls
        """
        self.config = config
        self._llm_available = None
        self._llm_client = None

    def _is_llm_available(self) -> bool:
        """Return True only when an LLM has been explicitly configured.

        Kept lazy and offline-safe: with no config we never attempt a network
        call, so diagram generation works in tests and air-gapped runs.
        """
        if self._llm_available is not None:
            return self._llm_available
        self._llm_available = bool(self.config and self.config.get("llm"))
        return self._llm_available

    def get_call_description(self,
                             callerFn: str,
                             calleeFn: str,
                             get_function_name_func: Callable[[str], str],
                             functions_data: Dict) -> str:
        """
        Get the description for a function call.

        Args:
            callerFn: The function that calls the callee
            calleeFn: The function that is being called
            get_function_name_func: Function to get display name from function key
            functions_data: The functions data dictionary

        Returns:
            A short human-readable description of the call.
        """
        caller_name = get_function_name_func(callerFn)
        callee_name = get_function_name_func(calleeFn)

        # Prefer an existing description authored on the callee function.
        existing = (functions_data.get(calleeFn, {}) or {}).get("description") or ""
        if existing.strip():
            return existing.strip()

        # Optionally enrich via LLM when configured (disabled by default).
        if self._is_llm_available():
            try:
                described = self._describe_with_llm(caller_name, callee_name)
                if described:
                    return described
            except Exception:
                pass

        return f"{caller_name} calls {callee_name}"

    def _describe_with_llm(self, caller_name: str, callee_name: str) -> Optional[str]:
        """Placeholder hook for LLM-backed descriptions.

        Returns None unless a client is wired up; callers fall back to the
        deterministic description above.
        """
        return None
