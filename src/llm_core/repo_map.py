"""Scoped repo map — compact signature-level view for LLM grounding.

Provides the LLM with a "map" of the project so it knows what symbols
exist and where they live.  This drastically reduces hallucinated function
names and helps the LLM understand the neighborhood around the function
being described or labeled.

Built entirely from ProjectKnowledge (no extra parsing needed).

Tiers (tried from most specific to most general until one fits budget):
  1. Function neighborhood — callees + callers + same-file functions
  2. File level — all functions in the target file
  3. Module level — all files in the module with function counts
  4. Project level — module names with file counts

Example output (tier 1):
    ## Module: math/
    ### File: math/utils.cpp [4 functions, 1 global]
      fn add(int, int) -> int
      fn subtract(int, int) -> int          ← callee
      fn multiply(int, int) -> int          ← callee
      global g_utilsCounter : int
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Dict, List, Optional, Set

from .token_counter import TokenCounter

logger = logging.getLogger(__name__)


class RepoMap:
    """Build a budget-aware repo map for a specific function."""

    def __init__(self, knowledge) -> None:
        """Initialize from a ProjectKnowledge instance.

        Parameters
        ----------
        knowledge : ProjectKnowledge
            The loaded project knowledge (functions, globals, etc.).
        """
        self._k = knowledge
        # Pre-build file → functions index
        self._file_funcs: Dict[str, List[str]] = defaultdict(list)
        for qn, fk in self._k.functions.items():
            if fk.file:
                self._file_funcs[fk.file].append(qn)
        # Pre-build module → files index
        self._module_files: Dict[str, Set[str]] = defaultdict(set)
        for file_path in self._file_funcs:
            module = os.path.dirname(file_path) or "."
            self._module_files[module].add(file_path)

    def for_function(
        self,
        qualified_name: str,
        budget: int,
        counter: TokenCounter,
    ) -> str:
        """Build the best repo map for *qualified_name* that fits in *budget* tokens.

        Tries tiers from most specific (neighborhood) to most general (project).
        Returns the most detailed tier that fits, or empty string if nothing fits.
        """
        fk = self._k.functions.get(qualified_name)
        if not fk:
            return ""

        # Try tiers in order — return the first that fits
        for tier_fn in (self._tier_neighborhood, self._tier_file, self._tier_module, self._tier_project):
            text = tier_fn(fk, qualified_name)
            if text and counter.fits(text, budget):
                return text

        # Nothing fits — try to truncate the project tier
        text = self._tier_project(fk, qualified_name)
        if text:
            return counter.truncate_to_budget(text, budget)
        return ""

    # ------------------------------------------------------------------
    # Tier 1: Function neighborhood
    # ------------------------------------------------------------------

    def _tier_neighborhood(self, fk, qualified_name: str) -> str:
        """Callees + callers + same-file functions with signatures."""
        relevant_qns: Set[str] = set()
        relevant_qns.update(fk.calls or [])
        relevant_qns.update(fk.called_by or [])

        # Same-file functions
        if fk.file:
            relevant_qns.update(self._file_funcs.get(fk.file, []))
        relevant_qns.discard(qualified_name)

        # Group by file
        file_entries: Dict[str, List[str]] = defaultdict(list)
        for qn in relevant_qns:
            other = self._k.functions.get(qn)
            if other:
                f = other.file or "unknown"
                role = ""
                if qn in (fk.calls or []):
                    role = "callee"
                elif qn in (fk.called_by or []):
                    role = "caller"
                line = self._format_function_line(other, role)
                file_entries[f].append(line)

        # Add target function's own file entry
        target_line = self._format_function_line(fk, "target")
        file_entries.setdefault(fk.file or "unknown", []).insert(0, target_line)

        return self._format_file_groups(file_entries, "Neighborhood")

    # ------------------------------------------------------------------
    # Tier 2: File level
    # ------------------------------------------------------------------

    def _tier_file(self, fk, qualified_name: str) -> str:
        """All functions in the target function's file."""
        if not fk.file:
            return ""
        file_qns = self._file_funcs.get(fk.file, [])
        if not file_qns:
            return ""

        lines = []
        for qn in file_qns:
            other = self._k.functions.get(qn)
            if other:
                role = "target" if qn == qualified_name else ""
                lines.append(self._format_function_line(other, role))

        # Add globals in this file
        for gn, gk in self._k.globals.items():
            if gk.file == fk.file:
                lines.append(f"  global {gk.qualified_name} : {gk.var_type}")

        file_entries = {fk.file: lines}
        return self._format_file_groups(file_entries, "File")

    # ------------------------------------------------------------------
    # Tier 3: Module level
    # ------------------------------------------------------------------

    def _tier_module(self, fk, qualified_name: str) -> str:
        """All files in the target module with function counts."""
        if not fk.file:
            return ""
        module = os.path.dirname(fk.file) or "."
        files = sorted(self._module_files.get(module, set()))
        if not files:
            return ""

        lines = [f"## Module: {module}/"]
        for f in files:
            func_count = len(self._file_funcs.get(f, []))
            globals_count = sum(1 for gk in self._k.globals.values() if gk.file == f)
            fname = os.path.basename(f)
            parts = [f"{func_count} functions"]
            if globals_count:
                parts.append(f"{globals_count} globals")
            lines.append(f"  {fname} [{', '.join(parts)}]")
            # Include signatures for target file, counts for others
            if f == fk.file:
                for qn in self._file_funcs.get(f, []):
                    other = self._k.functions.get(qn)
                    if other:
                        role = "target" if qn == qualified_name else ""
                        lines.append(f"    {self._format_function_line(other, role)}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tier 4: Project level
    # ------------------------------------------------------------------

    def _tier_project(self, fk, qualified_name: str) -> str:
        """Module names with file and function counts."""
        lines = [f"# Project: {self._k.project_name or 'unknown'}"]
        for module in sorted(self._module_files):
            files = self._module_files[module]
            func_count = sum(len(self._file_funcs.get(f, [])) for f in files)
            lines.append(f"  {module}/ [{len(files)} files, {func_count} functions]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_function_line(fk, role: str = "") -> str:
        """Format one function as a compact signature line."""
        sig = fk.signature or fk.qualified_name
        ret = f" -> {fk.return_type}" if fk.return_type else ""
        desc = ""
        if fk.description:
            # Take first sentence, max 60 chars
            first = fk.description.split(".")[0].strip()
            if len(first) > 60:
                first = first[:57] + "..."
            desc = f"  // {first}"
        role_tag = f"  [{role}]" if role else ""
        return f"  fn {sig}{ret}{desc}{role_tag}"

    @staticmethod
    def _format_file_groups(file_entries: Dict[str, List[str]], tier_name: str) -> str:
        """Format grouped file entries into a repo map string."""
        lines = []
        for file_path in sorted(file_entries):
            module = os.path.dirname(file_path) or "."
            fname = os.path.basename(file_path)
            func_count = len(file_entries[file_path])
            lines.append(f"## {module}/{fname} [{func_count} entries]")
            lines.extend(file_entries[file_path])
        return "\n".join(lines)
