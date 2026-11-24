#!/usr/bin/env python3
"""LLM integration for generating call descriptions in behavior diagrams."""

import time
from collections import Counter
from typing import Callable, Dict, List, Optional, Tuple

# Why a call's bullet was written without the LLM (review SWE3-030). Only the first is a
# choice; the others are counted, logged, and asked again at the end of the step.
LLM_OFF = "the LLM is off (llm.descriptions)"
NO_SERVER = "the LLM server did not answer"
NO_CONTEXT = "neither function has a description or code to read"
FAILED = "the LLM call failed"


class CallDescriptionGenerator:
    """Generates descriptions for function calls using LLM when available.

    A bullet is `A calls B to <reason>` when the LLM answers and `A calls B` when it does not
    (SWE3-DB-03.2). It used to fall back silently and for good: one failed server check marked
    the LLM unavailable for the whole run, and a failed call was swallowed. Now a call is tried
    up to TRIES times, the server is checked again RECHECK_SECONDS after it last failed, every
    call that fell back is asked once more at the end of the step (`retry_fallbacks`), and the
    view logs how many were written each way (`summary`).
    """

    TRIES = 3
    WAIT_SECONDS = 2.0
    RECHECK_SECONDS = 30.0
    # The second round stops after this many failures in a row: a server that is down for it
    # stays down, and each try can cost a timeout.
    STOP_AFTER = 3
    CODE_LINES = 40

    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the call description generator.

        Args:
            config: Optional configuration dictionary for LLM calls
        """
        self.config = config
        self._llm_available = None
        self._llm_client = None
        self._checked_at = 0.0
        self._base_path = None
        # (callerFn, calleeFn, reason) of each call written without the LLM, but for LLM_OFF.
        self.fell_back: List[Tuple[str, str, str]] = []
        self.counts: Counter = Counter()

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
        text, reason = self._describe(callerFn, calleeFn, get_function_name_func, functions_data)
        if text:
            self.counts["written"] += 1
            return text
        self.counts[reason] += 1
        if reason != LLM_OFF:
            self.fell_back.append((callerFn, calleeFn, reason))
        return self.fallback_text(callerFn, calleeFn, get_function_name_func)

    @staticmethod
    def fallback_text(callerFn: str, calleeFn: str, get_function_name_func: Callable[[str], str]) -> str:
        """The bullet without the LLM: `A calls B`."""
        return f"{get_function_name_func(callerFn)} calls {get_function_name_func(calleeFn)}"

    def _describe(self, callerFn, calleeFn, get_function_name_func, functions_data) -> Tuple[str, str]:
        """(text, "") when the LLM wrote it, else ("", the reason it did not)."""
        if not self._is_llm_available():
            return "", (NO_SERVER if self._llm_wanted() else LLM_OFF)
        context = (self._build_call_context(callerFn, calleeFn, get_function_name_func, functions_data)
                   or self._code_context(callerFn, calleeFn, get_function_name_func, functions_data))
        if not context:
            return "", NO_CONTEXT
        for attempt in range(self.TRIES):
            text = self._query_llm_for_description(context)
            if text:
                return text, ""
            if attempt + 1 < self.TRIES and self.WAIT_SECONDS:
                time.sleep(self.WAIT_SECONDS)
        # Rest the server: the next calls fall back at once until it is checked again, and the
        # end-of-step round asks them once more.
        self._llm_available = False
        self._checked_at = time.monotonic()
        return "", FAILED

    def retry_fallbacks(self, get_function_name_func: Callable[[str], str],
                        functions_data: Dict) -> Dict[Tuple[str, str], str]:
        """The second round: ask once more for every call written without the LLM because the
        server did not answer or the call failed. {(callerFn, calleeFn): text} for the ones the
        LLM now wrote. Stops after STOP_AFTER failures in a row."""
        pending = list(dict.fromkeys((c, e) for c, e, r in self.fell_back if r in (NO_SERVER, FAILED)))
        if not pending:
            return {}
        self._llm_available = None                 # check the server again, now
        done: Dict[Tuple[str, str], str] = {}
        misses = 0
        for caller, callee in pending:
            text, _reason = self._describe(caller, callee, get_function_name_func, functions_data)
            if text:
                done[(caller, callee)] = text
                misses = 0
            else:
                misses += 1
                if misses >= self.STOP_AFTER:
                    break
        resolved = sum(1 for f in self.fell_back if (f[0], f[1]) in done)   # bullets, not pairs
        self.fell_back = [f for f in self.fell_back if (f[0], f[1]) not in done]
        self.counts["written"] += resolved
        self.counts["written again"] += resolved
        return done

    def summary(self) -> Tuple[str, bool]:
        """(one line on how the bullets were written, True when some fell back unexpectedly)."""
        written = self.counts.get("written", 0)
        if self.counts.get(LLM_OFF):
            return ("behaviour descriptions: %d call bullet(s) written without the LLM -- %s"
                    % (self.counts[LLM_OFF], LLM_OFF), False)
        without = Counter(r for _c, _e, r in self.fell_back)
        if not written and not without:
            return "", False
        line = "behaviour descriptions: %d call bullet(s) written by the LLM" % written
        if self.counts.get("written again"):
            line += " (%d of them in a second round)" % self.counts["written again"]
        if without:
            line += ", %d without it: %s" % (
                sum(without.values()), "; ".join(f"{n} {r}" for r, n in without.most_common()))
        return line, bool(without)

    def _llm_wanted(self) -> bool:
        return bool(self.config) and bool((self.config.get("llm") or {}).get("descriptions", True))

    def _is_llm_available(self) -> bool:
        """Check if LLM client is initialized and available.

        A failed check is not final: the server is checked again RECHECK_SECONDS later."""
        if self._llm_available:
            return True
        if (self._llm_available is False
                and time.monotonic() - self._checked_at < self.RECHECK_SECONDS):
            return False

        if not self.config:
            self._llm_available = False
            return False

        self._checked_at = time.monotonic()
        try:
            from core.config import load_llm_config
            from llm_core.client import from_config
            from llm_enrichment import llm_provider_reachable

            if self._llm_wanted() and llm_provider_reachable(self.config):
                if self._llm_client is None:
                    self._llm_client = from_config(load_llm_config(self.config))
                self._llm_available = self._llm_client is not None
                return self._llm_available
        except Exception:
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

        Returns:
            LLM-generated description, or empty string if not available
        """
        text, _reason = self._describe(callerFn, calleeFn, get_function_name_func, functions_data)
        return text

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

    def _code_context(self, callerFn: str, calleeFn: str,
                      get_function_name_func: Callable[[str], str], functions_data: Dict) -> str:
        """The two functions' code, for a call neither of whose ends has a description (the
        caller in a component outside the run, a run whose descriptions failed): the LLM still
        has something true to say why. Empty when the source cannot be read."""
        parts = []
        for role, fn in (("Caller", callerFn), ("Callee", calleeFn)):
            code = self._source_of(functions_data.get(fn) or {})
            if code:
                parts.append(f"{role} ({get_function_name_func(fn)}) code:\n{code}")
        return "\n".join(parts)

    def _source_of(self, f: Dict) -> str:
        loc = f.get("location") or {}
        rel, start = loc.get("file") or "", int(loc.get("line") or 0)
        if not rel or not start:
            return ""
        end = min(int(loc.get("endLine") or start), start + self.CODE_LINES - 1)
        base = self._project_base()
        if not base:
            return ""
        import os
        try:
            with open(os.path.join(base, rel), encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            return ""
        return "\n".join(lines[start - 1:end]).strip()

    def _project_base(self) -> str:
        """The project's source root, from the run's metadata (as the unit header view reads it)."""
        if self._base_path is None:
            self._base_path = ""
            try:
                from core.model_io import read_model_file
                meta = read_model_file("metadata", required=False, default={}) or {}
                self._base_path = (meta.get("basePath") or "").strip()
            except Exception:
                pass
        return self._base_path

    def _query_llm_for_description(self, context: str) -> str:
        """
        Query LLM to generate a human-readable call description.

        Args:
            context: Formatted context with caller/callee descriptions

        Returns:
            Generated description or empty string on failure
        """
        if not self._is_llm_available():
            return ""

        try:
            from llm_core import tokens

            system, prompt = self._prompt(context)

            def _ask() -> str:
                with tokens.stage("behaviour.call_description"):
                    result = self._llm_client.generate(system, prompt)
                return _one_line(result) if result else ""

            # Cached by the whole prompt, as unit descriptions and input/output names are
            # (`llm_enrichment._cached_desc`: the model and `llm.cacheVersion` are in the key).
            # Asked again on every Phase 3, every row was re-worded each run -- rows nobody
            # corrected changed under a reviewer -- and each paid the LLM and the gateway's pause.
            # A corrected caller or callee description is IN the prompt, so exactly the rows
            # written from it are asked again (FAST_WORD_FILE_UPDATES P4, decided with the user).
            from llm_enrichment import _cached_desc
            return _cached_desc(self.config, self.cache_material(context), _ask)
        except Exception:
            return ""

    def _prompt(self, context: str):
        """(system, prompt) the LLM is asked for one call's description."""
        from llm_enrichment import _get_domain_context
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
        # Anchor the model to the project's real domain (Task 3.14) so it
        # stops inventing unrelated vocabulary in call descriptions.
        return _get_domain_context(self.config), prompt

    def cache_material(self, context: str) -> str:
        """What one call's description is cached by (`llm_enrichment._cached_desc`): the whole
        prompt. A rewrite seeds it with a row's stored words for a call whose prompt did not
        move (`review.rewrite`), so they are kept, not asked again."""
        system, prompt = self._prompt(context)
        return "behaviour_call|%s|%s" % (system, prompt)


def _one_line(text: str) -> str:
    """Collapse a description onto a single line.

    The prompt asks for one line of at most twenty words and a model may ignore both. A stray
    newline inside a bullet is a formatting fault in the DOCX on its own, and it also breaks the
    storage of a reviewer's correction: the bullets of one behaviour row are stored joined by
    newline, so a bullet containing one would come back as two (REQ-ED-02). Normalising here
    makes the separator safe by construction rather than by a rule someone must remember.
    """
    return " ".join((text or "").split())
