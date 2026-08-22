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
            A description of why a function is being called
        """
        # Try to use LLM for better descriptions if available
        llm_desc = self._get_llm_call_description(callerFn, calleeFn, get_function_name_func, functions_data)
        if llm_desc:
            return llm_desc

        # Fallback to simple description
        callerFnName = get_function_name_func(callerFn)
        calleeFnName = get_function_name_func(calleeFn)
        return f"{callerFnName} calls {calleeFnName}"

    def _is_llm_available(self) -> bool:
        """Check if LLM client is initialized and available."""
        if self._llm_available is not None:
            return self._llm_available

        if not self.config:
            self._llm_available = False
            return False

        try:
            from llm_client import _ollama_available, _openai_available
            if _ollama_available(self.config) or _openai_available(self.config):
                self._llm_available = True
                return True
        except ImportError:
            pass

        self._llm_available = False
        return False

    def _get_llm_call_description(self,
                                  callerFn: str,
                                  calleeFn: str,
                                  get_function_name_func: Callable[[str], str],
                                  functions_data: Dict) -> str:
        """
        Get a better description for a function call using LLM.

        Uses the function descriptions (if available) to generate a more
        meaningful description like "FunctionA calls FunctionB to get the sum of 2 numbers".

        Args:
            callerFn: The function that calls the callee
            calleeFn: The function that is being called
            get_function_name_func: Function to get display name from function key
            functions_data: The functions data dictionary

        Returns:
            LLM-generated description, or empty string if not available
        """
        if not self._is_llm_available():
            return ""

        context = self._build_call_context(callerFn, calleeFn, get_function_name_func, functions_data)
        if not context:
            return ""

        return self._query_llm_for_description(context)

    def _build_call_context(self,
                            callerFn: str,
                            calleeFn: str,
                            get_function_name_func: Callable[[str], str],
                            functions_data: Dict) -> str:
        """
        Build context string from function descriptions.

        Returns empty string if neither function has a description.
        """
        caller_data = functions_data.get(callerFn, {})
        callee_data = functions_data.get(calleeFn, {})

        caller_desc = caller_data.get("description") or caller_data.get("comment") or ""
        callee_desc = callee_data.get("description") or callee_data.get("comment") or ""

        if not caller_desc and not callee_desc:
            return ""

        caller_name = get_function_name_func(callerFn)
        callee_name = get_function_name_func(calleeFn)

        parts = []
        if caller_desc:
            parts.append(f"Caller ({caller_name}): {caller_desc}")
        if callee_desc:
            parts.append(f"Callee ({callee_name}): {callee_desc}")

        return "\n".join(parts)

    def _query_llm_for_description(self, context: str) -> str:
        """
        Query LLM to generate a human-readable call description.

        Args:
            context: Formatted context with caller/callee descriptions

        Returns:
            Generated description or empty string on failure
        """
        try:
            from llm_client import _call_llm

            prompt = (
                "Generate a short, human-readable description (1 line, max 20 words) "
                "explaining why the caller function calls the callee function.\n"
                "Use the provided function descriptions to make it meaningful.\n"
                "\n"
                f"{context}\n"
                "\n"
                "Generate a natural description like \"FunctionA calls FunctionB to get "
                "the sum of 2 numbers\" or \"FunctionA calls FunctionB to validate input\".\n"
                "\n"
                "Description:"
            )

            result = _call_llm(prompt, self.config, kind="call_description")
            return result.strip() if result else ""
        except ImportError:
            return ""
