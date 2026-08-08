"""Macro definitions for Clang, read from CSV or JSON, scoped per layer.

`--macros` historically accepted one 2-column CSV (Name,Value) applied to every
layer. Real inputs are neither: clients hand over toolchain dumps (armclang /
`fromelf` JSON, keyed by compilation unit), the web wizard stores a JSON list of
`NAME=VALUE` strings, and macros differ **per layer**. This module is the single
reader for every accepted shape so Phase 1 and Phase 3 can never disagree.

Shapes are detected by **content**, not by file extension:

    CSV       Name,Value                        legacy 2-column form
    list      ["NAME=VALUE", "-DNAME"]          web wizard, manual mode
    map       {"NAME": "VALUE"}
    scoped    {"Layer1": {"NAME": "VALUE"}}     keys are layer names
    dump      {"metadata": {...},               toolchain export
               "macros_by_cu": {"<cu>": {"<NAME>": {"raw_value": ...}}}}

Rules shared by every shape: a value of ``ne`` (any case) skips the entry, an
empty value means a bare ``-DNAME``, and function-like names (``MAX(a,b)``) are
skipped — a `-D` for those is fragile and a toolchain dump is the wrong source
for them.

Definitions are returned scope-keyed (``"*"`` = every layer). Callers turn them
into `-D` flags with `scoped_args` / `args_for_scope`.

A **scope is an opaque key**, deliberately not the word "layer": today the
pipeline uses one macro list per layer, but the same layer may later need
parsing under several macro sets (build variants). When that lands, only the
scope *resolution* changes — the readers, the stored file and `args_for_scope`
already carry an arbitrary key.
"""
import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("macro_input")

# Scope applied to every layer. Also the key a flat (pre-scope) file loads under.
GLOBAL_SCOPE = "*"

# Value that means "not exported / do not define" in the client's CSV.
_SKIP_VALUE = "ne"

# NAME(a,b) — a parameter list in the *name* marks a function-like macro.
_FUNC_LIKE_RE = re.compile(r"^\s*\w+\s*\(")

# Keys that identify a toolchain-dump entry (vs. a plain name->value mapping).
_ENTRY_KEYS = frozenset(
    ("raw_value", "expanded_value", "computed_value", "is_fully_resolved", "dependency_chain")
)

# How many unresolved macro names to name in the report before truncating.
_REPORT_NAME_LIMIT = 10

# Scope-keyed definitions: {scope: {NAME: value-or-None}}
MacroDefs = Dict[str, Dict[str, Optional[str]]]


class MacroInputError(ValueError):
    """Unreadable macro file — callers exit with a message rather than parse on."""


@dataclass
class MacroLoadReport:
    """What actually landed, so a mis-read file is visible instead of silent."""

    path: str = ""
    kind: str = ""                          # csv | list | map | scoped | entries | toolchain
    toolchain: str = ""                     # metadata.toolchain, when present
    emitted: int = 0
    skipped_ne: int = 0
    skipped_function_like: int = 0
    unresolved: int = 0                     # text value that still names macros it depends on
    unresolved_names: List[str] = field(default_factory=list)
    text_valued: int = 0                    # non-numeric but self-contained (strings, identifiers)
    declared_total: Optional[int] = None     # metadata.total_macros
    declared_resolved: Optional[int] = None  # metadata.fully_resolved
    scopes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def lines(self) -> List[str]:
        """Report lines, in the style of the parser's CSV merge report."""
        scope_note = "all layers" if self.scopes == [GLOBAL_SCOPE] else ", ".join(self.scopes)
        head = f"  macros: {self.emitted} define(s) from {self.path} [{self.kind}]"
        if self.toolchain:
            head += f", toolchain {self.toolchain}"
        out = [head, f"    scope: {scope_note or '(none)'}"]
        if self.unresolved:
            shown = ", ".join(self.unresolved_names[:_REPORT_NAME_LIMIT])
            if self.unresolved > len(self.unresolved_names[:_REPORT_NAME_LIMIT]):
                shown += f", +{self.unresolved - _REPORT_NAME_LIMIT} more"
            out.append(
                f"    {self.unresolved} defined from text that still names other macros — "
                f"they resolve only if those are defined too: {shown}"
            )
        if self.text_valued:
            out.append(
                f"    {self.text_valued} non-numeric value(s) passed through as text "
                "(strings, identifiers) — self-contained, nothing to chase"
            )
        if self.skipped_function_like:
            out.append(f"    {self.skipped_function_like} function-like macro(s) skipped")
        if self.skipped_ne:
            out.append(f"    {self.skipped_ne} skipped (value '{_SKIP_VALUE}')")
        out.extend(f"    WARNING: {w}" for w in self.warnings)
        return out


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_macro_defs(
    path: str,
    *,
    scope_map: Optional[Dict[str, str]] = None,
    default_scope: Optional[str] = None,
) -> Tuple[MacroDefs, MacroLoadReport]:
    """Read one macro file and return (scope-keyed defs, report).

    `scope_map` maps a dump's compilation-unit key to a layer name (config
    `clang.macroScopes`). `default_scope` forces every entry into one layer and
    overrides any scope found in the file — that is how an explicit
    `--macros-layer <layer> <path>` beats whatever the file claims.
    """
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            text = fh.read()
    except OSError as exc:
        raise MacroInputError(f"{path}: cannot be read ({exc})") from exc

    report = MacroLoadReport(path=path)
    if text.lstrip()[:1] in ("{", "["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MacroInputError(f"{path}: invalid JSON ({exc})") from exc
        defs = _from_json(data, report, scope_map or {})
    else:
        defs = _from_csv(text, report)

    if default_scope:
        # Explicit CLI scope wins: collapse everything into the named layer.
        flat: Dict[str, Optional[str]] = {}
        for entries in defs.values():
            flat.update(entries)
        defs = {default_scope: flat} if flat else {}

    defs = {scope: entries for scope, entries in defs.items() if entries}
    report.scopes = list(defs)
    report.emitted = sum(len(entries) for entries in defs.values())
    _check_declared_counts(report)
    for warning in report.warnings:
        logger.warning("%s: %s", path, warning)
    return defs, report


def _check_declared_counts(report: MacroLoadReport) -> None:
    """A dump states its own totals — a mismatch means we misread the file."""
    if report.declared_total is None:
        return
    seen = report.emitted + report.skipped_ne + report.skipped_function_like
    if seen != report.declared_total:
        report.warnings.append(
            f"metadata.total_macros={report.declared_total} but {seen} entries were found"
        )


def _from_csv(text: str, report: MacroLoadReport) -> MacroDefs:
    """Legacy 2-column CSV (Name, Value) — always global."""
    report.kind = "csv"
    out: MacroDefs = {}
    for row in csv.DictReader(io.StringIO(text)):
        _add(out, GLOBAL_SCOPE, row.get("Name"), row.get("Value"), report)
    return out


def _from_json(data: Any, report: MacroLoadReport, scope_map: Dict[str, str]) -> MacroDefs:
    if isinstance(data, list):
        return _from_list(data, report)
    if not isinstance(data, dict):
        raise MacroInputError("macro JSON must be an object or an array")
    if isinstance(data.get("macros_by_cu"), dict):
        return _from_toolchain(data, report, scope_map)

    values = list(data.values())
    if values and all(isinstance(v, dict) for v in values):
        if all(_is_entry(v) for v in values):
            # name -> entry dict: a dump's inner table handed over without its wrapper.
            report.kind = "entries"
            return _add_entries({}, GLOBAL_SCOPE, data, report)
        return _from_scoped(data, report)
    return _from_map(data, report)


def _from_list(items: List[Any], report: MacroLoadReport) -> MacroDefs:
    """["NAME=VALUE", "-DNAME"] — the shape the web wizard stores."""
    report.kind = "list"
    out: MacroDefs = {}
    for item in items:
        text = str(item if item is not None else "").strip()
        if text.startswith("-D"):
            text = text[2:]
        if not text:
            continue
        name, sep, value = text.partition("=")
        _add(out, GLOBAL_SCOPE, name, value if sep else None, report)
    return out


def _from_map(data: Dict[str, Any], report: MacroLoadReport) -> MacroDefs:
    report.kind = "map"
    out: MacroDefs = {}
    for name, value in data.items():
        _add(out, GLOBAL_SCOPE, name, value, report)
    return out


def _from_scoped(data: Dict[str, Any], report: MacroLoadReport) -> MacroDefs:
    """{"Layer1": {...}} — keys are layer names, so they are used verbatim."""
    report.kind = "scoped"
    out: MacroDefs = {}
    for scope, entries in data.items():
        scope = str(scope or "").strip() or GLOBAL_SCOPE
        entries = entries or {}
        if entries and all(isinstance(v, dict) for v in entries.values()):
            _add_entries(out, scope, entries, report)
            continue
        for name, value in entries.items():
            _add(out, scope, name, value, report)
    return out


def _from_toolchain(
    data: Dict[str, Any], report: MacroLoadReport, scope_map: Dict[str, str]
) -> MacroDefs:
    """{"metadata": {...}, "macros_by_cu": {...}} — an armclang/fromelf export."""
    report.kind = "toolchain"
    meta = data.get("metadata")
    if isinstance(meta, dict):
        report.toolchain = str(meta.get("toolchain") or "")
        report.declared_total = _as_int(meta.get("total_macros"))
        report.declared_resolved = _as_int(meta.get("fully_resolved"))

    cus = data["macros_by_cu"]
    single_cu = len(cus) == 1
    out: MacroDefs = {}
    for cu, entries in cus.items():
        if not isinstance(entries, dict):
            report.warnings.append(f"compilation unit {cu!r} is not an object — skipped")
            continue
        if single_cu:
            # One CU per file is the observed shape: the file *is* the scope, and
            # --macros-layer (default_scope) is what pins it to a layer.
            scope = GLOBAL_SCOPE
        else:
            scope = (scope_map or {}).get(cu) or GLOBAL_SCOPE
            if scope == GLOBAL_SCOPE:
                report.warnings.append(
                    f"compilation unit {cu!r} is not mapped to a layer "
                    "(clang.macroScopes) — applied to all layers"
                )
        _add_entries(out, scope, entries, report)
    return out


def _add_entries(
    out: MacroDefs, scope: str, entries: Dict[str, Any], report: MacroLoadReport
) -> MacroDefs:
    """Add a name -> entry-dict table (dump form) under one scope."""
    for name, entry in entries.items():
        value, from_text = _entry_value(entry)
        if not _add(out, scope, name, value, report) or not from_text:
            continue
        # Only a text value that names OTHER macros is a risk worth flagging; a
        # string or an identifier is self-contained and needs no chasing.
        if isinstance(entry, dict) and (entry.get("dependency_chain") or []):
            report.unresolved += 1
            if len(report.unresolved_names) < _REPORT_NAME_LIMIT:
                report.unresolved_names.append(str(name))
        else:
            report.text_valued += 1
    return out


def _entry_value(entry: Any) -> Tuple[Optional[str], bool]:
    """Pick the value to define, and say whether it came from unresolved text.

    A resolved `computed_value` is preferred: it is a plain number, so it cannot
    half-resolve the way `raw_value` does when the macros it depends on are not
    in the same file. Otherwise fall back to the expanded text, then the raw
    text — an unresolved name is often defined by the project's own headers,
    which libclang does see, so passing the text through beats dropping the
    define and silently flipping an `#ifdef` branch.
    """
    if not isinstance(entry, dict):
        return _norm_value(entry), False
    computed = entry.get("computed_value")
    if entry.get("is_fully_resolved") and computed is not None:
        return _norm_value(computed), False
    for key in ("expanded_value", "raw_value"):
        value = entry.get(key)
        if value is not None and str(value).strip():
            return _norm_value(value), True
    return None, False


def _add(
    out: MacroDefs, scope: str, name: Any, value: Any, report: MacroLoadReport
) -> bool:
    """Apply the shared skip rules and record one definition. True if it landed."""
    name = str(name if name is not None else "").strip()
    if not name:
        return False
    if _FUNC_LIKE_RE.match(name):
        report.skipped_function_like += 1
        return False
    normalized = _norm_value(value)
    if normalized is not None and normalized.lower() == _SKIP_VALUE:
        report.skipped_ne += 1
        return False
    out.setdefault(scope, {})[name] = normalized
    return True


def _norm_value(value: Any) -> Optional[str]:
    """Normalize a value to a string, or None for a bare `-DNAME`."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    text = str(value).strip()
    return text or None


def _is_entry(value: Any) -> bool:
    return isinstance(value, dict) and bool(_ENTRY_KEYS & set(value))


def _as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Merging and `-D` flags
# ---------------------------------------------------------------------------

def merge_macro_defs(base: MacroDefs, extra: MacroDefs) -> MacroDefs:
    """Merge scope-keyed defs; `extra` wins per (scope, name)."""
    out: MacroDefs = {scope: dict(entries) for scope, entries in base.items()}
    for scope, entries in extra.items():
        out.setdefault(scope, {}).update(entries)
    return out


def find_conflicts(
    base: MacroDefs, extra: MacroDefs
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    """Names defined twice **in the same scope** with different values.

    Merging is last-wins, but the precedence strategy across several macro lists
    is still an open question — so collisions are reported (caller logs them)
    instead of being resolved silently. A global-vs-layer override is deliberate
    precedence, not a collision, and is not reported here.

    Returns (scope, name, existing value, new value) tuples.
    """
    out: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    for scope, entries in extra.items():
        current = base.get(scope) or {}
        for name, value in entries.items():
            if name in current and current[name] != value:
                out.append((scope, name, current[name], value))
    return out


def to_clang_args(entries: Dict[str, Optional[str]]) -> List[str]:
    """`-D` flags for one scope, in file order (deterministic per input)."""
    return [
        f"-D{name}={value}" if value is not None else f"-D{name}"
        for name, value in entries.items()
    ]


def scoped_args(defs: MacroDefs) -> Dict[str, List[str]]:
    """Scope-keyed `-D` flags — the shape written to model/clang_macros.json."""
    return {scope: to_clang_args(entries) for scope, entries in defs.items()}


def normalize_scoped_args(data: Any) -> Dict[str, List[str]]:
    """Accept the stored shape, or the flat pre-scope list, as scope-keyed args."""
    if isinstance(data, list):
        return {GLOBAL_SCOPE: [str(a) for a in data if a]}
    if isinstance(data, dict):
        return {
            str(scope): [str(a) for a in (args or []) if a]
            for scope, args in data.items()
            if isinstance(args, (list, tuple))
        }
    return {}


def args_for_scope(scoped: Dict[str, List[str]], scope: Optional[str]) -> List[str]:
    """Flags for one layer: global first, then the layer's own.

    Order matters rather than de-duplication: Clang honours the **last** `-D` for
    a repeated macro, so a layer's value overrides the global one by position.
    """
    args = list(scoped.get(GLOBAL_SCOPE) or [])
    if scope and scope != GLOBAL_SCOPE:
        args.extend(scoped.get(scope) or [])
    return args
