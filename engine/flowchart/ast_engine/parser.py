"""
Source extraction and libclang TranslationUnit management.

- SourceExtractor: reads and caches source files, extracts line ranges and
  cursor extents as raw text.
- TranslationUnitParser: creates and caches libclang TUs with the correct
  std and include args.
"""

import logging
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import clang.cindex as ci

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source extraction
# ---------------------------------------------------------------------------

class SourceExtractor:
    """Reads source files and provides text extraction helpers."""

    def __init__(self, base_path: str) -> None:
        self._base_path = Path(base_path)
        self._cache: Dict[str, List[str]] = {}

    def get_lines(self, relative_file: str) -> List[str]:
        """Return all lines for a source file (cached)."""
        if relative_file not in self._cache:
            abs_path = self._base_path / relative_file
            if not abs_path.exists():
                raise FileNotFoundError(f"Source file not found: {abs_path}")
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                self._cache[relative_file] = f.readlines()
        return self._cache[relative_file]

    def extract_by_lines(self, relative_file: str,
                         start_line: int, end_line: int) -> str:
        """Extract function source strictly by 1-indexed line range."""
        lines = self.get_lines(relative_file)
        return "".join(lines[start_line - 1: end_line])

    @staticmethod
    def get_extent_text(lines: List[str],
                        start_line: int, end_line: int,
                        start_col: int, end_col: int) -> str:
        """
        Extract text for a cursor extent.
        All line/column values are 1-indexed (as returned by libclang).
        """
        if not lines:
            return ""

        # Clamp to valid range
        start_line = max(1, min(start_line, len(lines)))
        end_line = max(start_line, min(end_line, len(lines)))

        if start_line == end_line:
            row = lines[start_line - 1]
            return row[start_col - 1: end_col - 1].strip()

        result: List[str] = []
        result.append(lines[start_line - 1][start_col - 1:].rstrip())
        for i in range(start_line, end_line - 1):
            result.append(lines[i].rstrip())
        result.append(lines[end_line - 1][: end_col - 1].rstrip())
        return "\n".join(result)

    def abs_path(self, relative_file: str) -> str:
        return str(self._base_path / relative_file)


# ---------------------------------------------------------------------------
# Translation Unit management
# ---------------------------------------------------------------------------

class TranslationUnitParser:
    """Creates and caches libclang TranslationUnits."""

    _PARSE_OPTIONS = (
        ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        | ci.TranslationUnit.PARSE_INCOMPLETE
        | ci.TranslationUnit.PARSE_SKIP_FUNCTION_BODIES
    )

    # How many parsed TUs to keep. Small on purpose: functions are processed grouped by
    # source file, so 1 would already hit most of the time; the margin covers the
    # header-resolution retry, which opens an *including* TU while the current one is live.
    # Each retained full-body TU can be tens to hundreds of MB on firmware-scale sources,
    # so this bound is what keeps peak memory flat instead of growing with file count.
    DEFAULT_TU_CACHE_SIZE = 4

    def __init__(self, std: str, extra_clang_args: List[str],
                 tu_cache_size: int = DEFAULT_TU_CACHE_SIZE) -> None:
        self._std = std
        self._extra_args = extra_clang_args
        self._index = ci.Index.create()
        self._tu_cache: "OrderedDict[str, ci.TranslationUnit]" = OrderedDict()
        self._tu_cache_size = max(1, int(tu_cache_size))

    def _build_args(self) -> List[str]:
        # Pull the shared default macro defines from core.config so this
        # re-parser inherits the same `-DPUBLIC=`, `-DPROTECTED=`, etc. that
        # Phase 1's parser uses. Without these, libclang reports
        # "unknown type name 'PUBLIC'" warnings on every project that hides
        # visibility behind macros, and the resulting AST is incomplete.
        try:
            from core.config import default_clang_macro_defs
            macro_defs = default_clang_macro_defs()
        except Exception:
            macro_defs = []
        args = [f"-std={self._std}", "-x", "c++"] + macro_defs
        for extra in self._extra_args:
            if extra not in args:
                args.append(extra)
        return args

    def _cached(self, key: str, build) -> ci.TranslationUnit:
        """LRU-bounded TU cache (doc 09, M1).

        The cache was unbounded and never cleared, so a run held one syntax tree per source
        file it touched for the whole phase — and `get_tu_full` deliberately parses WITH
        function bodies, which is the expensive kind. Peak memory therefore grew with FILE
        COUNT, not with change size: even a one-line incremental on a large codebase paid
        for every file it visited. Per job, so it multiplies by concurrency, and it is the
        first thing that exhausts a container on a big repo.

        A small bound is enough because the engine processes functions grouped by source
        file (`by_file` in flowchart_engine), so access has strong locality; the margin above
        1 is for the header-resolution retry, which reaches into an *including* TU while the
        current one is still in use.

        Evicting is safe. libclang's Python `Cursor` holds a `_tu` reference, so a TU stays
        alive as long as any cursor taken from it is still reachable — dropping our entry
        frees only the ones nobody is using. (That is the same mechanism `engine/parser.py`
        relies on when it assigns `oc._tu = c._tu` to keep a borrowed cursor valid.)
        """
        tu = self._tu_cache.get(key)
        if tu is not None:
            self._tu_cache.move_to_end(key)          # mark most-recently-used
            return tu
        tu = build()
        self._tu_cache[key] = tu
        while len(self._tu_cache) > self._tu_cache_size:
            evicted, _ = self._tu_cache.popitem(last=False)
            logger.debug("Evicted cached TU (cap %d): %s", self._tu_cache_size, evicted)
        return tu

    def get_tu(self, abs_path: str) -> ci.TranslationUnit:
        """Return (cached) TranslationUnit for a source file."""
        def _build():
            args = self._build_args()
            logger.debug("Parsing TU: %s", abs_path)
            tu = self._index.parse(abs_path, args=args,
                                   options=self._PARSE_OPTIONS)
            if tu is None:
                raise RuntimeError(f"libclang failed to parse: {abs_path}")
            self._log_diagnostics(tu, abs_path)
            return tu

        return self._cached(abs_path, _build)

    def get_tu_full(self, abs_path: str) -> ci.TranslationUnit:
        """
        Return a TranslationUnit parsed WITHOUT skipping function bodies.
        Used when we need to traverse the actual function body for CFG building.
        """
        def _build():
            args = self._build_args()
            logger.debug("Parsing full TU (with bodies): %s", abs_path)
            options = (
                ci.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
                | ci.TranslationUnit.PARSE_INCOMPLETE
            )
            tu = self._index.parse(abs_path, args=args, options=options)
            if tu is None:
                raise RuntimeError(f"libclang failed to parse: {abs_path}")
            self._log_diagnostics(tu, abs_path)
            return tu

        return self._cached(abs_path + "__full", _build)

    @staticmethod
    def _log_diagnostics(tu: ci.TranslationUnit, path: str) -> None:
        errors = [d for d in tu.diagnostics
                  if d.severity >= ci.Diagnostic.Error]
        if errors:
            logger.warning("%d error(s) in %s (AST may be incomplete)",
                           len(errors), path)
            # Log the first few errors at WARNING so the user can see which
            # headers are missing and add the appropriate --clang-arg=-I flags.
            for d in errors[:5]:
                logger.warning("  clang: %s", d.spelling)
            if len(errors) > 5:
                logger.warning("  ... and %d more (use --verbose for all)",
                               len(errors) - 5)
            if any("file not found" in (d.spelling or "").lower() for d in errors):
                logger.warning(
                    "  Hint: add missing include paths via "
                    "--clang-arg=-I/path/to/headers"
                )
