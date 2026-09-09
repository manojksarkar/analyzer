"""Include paths for Clang, read from build-system `compile_commands.json`.

The build is the only place that knows the real `-I` set: a firmware tree
compiles the same headers under several roots (`04_FIL`, `05_CTRL`,
`00_SRC/03_EXT_LIB`, ...) with 50-100+ include dirs per translation unit, and
`run.py`'s directory walk can only guess at it. A compilation database records
what the compiler was actually given, so reading it turns that guess into
ground truth.

Scope of this module: **include paths only**. A real entry also carries `-D`,
`--target`, `-mcpu` and friends; those are deliberately ignored here (see
`_INCLUDE_FLAGS`) so the first integration cannot regress a parse through a
flag libclang rejects. Macros keep coming from `core.macro_input` - a build
database cannot see header-defined macros, so it supplements that file rather
than replacing it.

One database per **core**, declared in the top-level `cores` section beside that
core's `macros` and `dataDictionary`; a layer names the cores it is built from
(`layers.<Layer>.cores`). Today a layer has at most one core
(`config.MAX_CORES_PER_LAYER`) - this module already merges several per layer,
concatenating their dirs in first-seen order, so lifting that limit needs no
change here.

The path problem
----------------
Entries are recorded on the build machine, so every path in them is rooted
somewhere that does not exist locally::

    directory  D:\\workspace\\BA190_0\\01_SRC\\02_HIL\\01_BUILD\\SAVONA\\DS5
    -I         ..\\..\\..\\..\\04_FIL\\02_Src_Product\\03_Ucf\\FlashDriver\\Driver\\Io

Resolving the second against the first yields an absolute `D:/...` path that is
useless on the analysis machine. `derive_root_prefix` recovers the mapping
instead of requiring it to be configured: it strips leading components off a
foreign path until the remainder exists under the local project root, and the
prefix that wins a majority vote across all dirs becomes the substitution. The
deepest remainder wins per path, because `04_FIL/02_Src_Product/03_Ucf/...`
matching by coincidence is far less likely than `04_FIL` alone.

Derivation touches the filesystem, so what it concluded is reported and logged
rather than applied silently - "why did this TU lose its headers" has to stay
answerable after the fact.
"""
import json
import logging
import os
import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("compile_commands")

# Flags that introduce an include directory. Both spellings occur in the wild:
# joined (`-I../foo`) and separate (`-I ../foo`).
_INCLUDE_FLAGS = ("-I", "-isystem", "-iquote")

# `D:/foo`, `/foo` or `//server/share` - already rooted, do not join to `directory`.
_ABS_RE = re.compile(r"^(?:[A-Za-z]:/|/)")

# A derived prefix backed by fewer than this share of the dirs is reported as
# suspect: it usually means a multi-root build or a partial checkout, and
# parsing the rest against missing headers silently is the worst outcome.
_MIN_VOTE_SHARE = 0.75


@dataclass
class CoreSource:
    """One `compile_commands.json` and the layer its include dirs belong to."""
    core: str
    path: str
    layer: str
    # Set to skip derivation: the foreign prefix to strip before re-anchoring.
    root_prefix: Optional[str] = None


@dataclass
class RootPrefix:
    """The foreign prefix `derive_root_prefix` settled on, and how sure it is."""
    prefix: str
    votes: int
    total: int
    derived: bool = True

    @property
    def share(self) -> float:
        return (self.votes / self.total) if self.total else 0.0


@dataclass
class LoadReport:
    """What one core contributed, and what it could not."""
    core: str
    layer: str
    entries: int = 0
    raw_dirs: int = 0
    kept_dirs: int = 0
    root_prefix: Optional[RootPrefix] = None
    unmapped: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


def normalize(path: str) -> str:
    """A path in one comparable form: `/` separators, `..` collapsed.

    `posixpath` rather than `os.path` on purpose - a database written on Windows
    must resolve identically wherever the analyzer runs, and `os.path.normpath`
    would flip separators back on a Windows host.
    """
    return posixpath.normpath(str(path).replace("\\", "/"))


def _is_absolute(path: str) -> bool:
    return bool(_ABS_RE.match(path))


def _resolve(directory: str, path: str) -> str:
    """Resolve one recorded path against its entry's own `directory` field."""
    p = str(path).replace("\\", "/")
    if _is_absolute(p):
        return normalize(p)
    return normalize(posixpath.join(directory, p))


def include_args(arguments: Sequence[str]) -> List[str]:
    """The include-dir operands of one `arguments` array, in command-line order.

    Everything else is dropped here: `-D`, `-o`, `-c`, `-W*`, `--target`,
    response files (`@file`). Include flags only, per this module's scope.
    """
    out: List[str] = []
    args = [str(a) for a in (arguments or [])]
    i = 0
    while i < len(args):
        arg = args[i]
        for flag in _INCLUDE_FLAGS:
            if arg == flag:
                # Separate form: the directory is the next argument. A trailing
                # flag with nothing after it is malformed; skip rather than raise.
                if i + 1 < len(args):
                    out.append(args[i + 1])
                    i += 1
                break
            if arg.startswith(flag) and len(arg) > len(flag):
                out.append(arg[len(flag):])
                break
        i += 1
    return out


def read_entries(path: str) -> List[Dict[str, Any]]:
    """Load one compilation database, keeping only usable entries."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array of entries")
    return [e for e in data if isinstance(e, dict) and e.get("directory")]


def entry_include_dirs(entries: Iterable[Dict[str, Any]]) -> List[str]:
    """Every include dir across `entries`, resolved and deduped, order kept.

    Order is first-seen rather than sorted: `-I` is order-sensitive, and the
    build's own ordering is the one known to compile.
    """
    seen: set = set()
    out: List[str] = []
    for entry in entries:
        directory = normalize(entry.get("directory") or "")
        # `arguments` is the array form; `command` is the legacy single string.
        args = entry.get("arguments")
        if args is None and entry.get("command"):
            args = str(entry["command"]).split()
        for raw in include_args(args or []):
            resolved = _resolve(directory, raw)
            if resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
    return out


def derive_root_prefix(dirs: Sequence[str], project_root: str) -> Optional[RootPrefix]:
    """Recover the foreign prefix to strip so `dirs` land under `project_root`.

    For each dir, drop leading components until the remainder exists locally;
    the **deepest** surviving remainder wins for that dir, since a long tail
    matching by accident is far less likely than a short one. Each dir then
    votes for the prefix it implies, and the modal prefix is returned.

    Returns None when nothing matched - the caller decides whether that is fatal.
    """
    local_root = normalize(project_root)
    votes: Counter = Counter()
    for d in dirs:
        parts = d.split("/")
        # i is the split point: parts[:i] is the foreign prefix, parts[i:] the
        # remainder tested locally. Ascending i => longest remainder first.
        for i in range(1, len(parts)):
            if not any(parts[i:]):
                continue
            if os.path.isdir(os.path.join(local_root, *parts[i:])):
                votes["/".join(parts[:i])] += 1
                break
    if not votes:
        return None
    # Ties break on the longer prefix, then lexicographically: a run must reach
    # the same conclusion twice on the same inputs.
    best = max(votes.items(), key=lambda kv: (kv[1], len(kv[0]), kv[0]))
    return RootPrefix(prefix=best[0], votes=best[1], total=len(dirs))


def apply_root_prefix(dirs: Sequence[str], prefix: str,
                      project_root: str) -> Tuple[List[str], List[str], List[str]]:
    """Re-anchor `dirs` from `prefix` onto `project_root`.

    Returns `(kept, unmapped, missing)` - kept exist locally, unmapped never
    started with `prefix`, missing mapped cleanly but are not on disk.
    """
    local_root = normalize(project_root)
    pref = normalize(prefix).rstrip("/")
    kept: List[str] = []
    unmapped: List[str] = []
    missing: List[str] = []
    for d in dirs:
        if d == pref or d.startswith(pref + "/"):
            remainder = d[len(pref):].lstrip("/")
            mapped = normalize(posixpath.join(local_root, remainder)) if remainder else local_root
        elif not _is_absolute(d):
            # Already relative to the project: nothing foreign to strip.
            mapped = normalize(posixpath.join(local_root, d))
        else:
            unmapped.append(d)
            continue
        if os.path.isdir(mapped):
            kept.append(mapped)
        else:
            missing.append(mapped)
    return kept, unmapped, missing


def load_sources(sources: Sequence[CoreSource],
                 project_root: str) -> Tuple[Dict[str, List[str]], List[LoadReport]]:
    """Read every core's database into `{layer: [include dir, ...]}` + reports.

    Cores sharing a layer concatenate into it, first-seen order preserved and
    deduped across cores.
    """
    by_layer: Dict[str, List[str]] = {}
    seen_by_layer: Dict[str, set] = {}
    reports: List[LoadReport] = []

    for src in sources:
        report = LoadReport(core=src.core, layer=src.layer)
        try:
            entries = read_entries(src.path)
        except (OSError, ValueError) as exc:
            logger.warning("compile_commands: %s unreadable (%s) - skipped", src.path, exc)
            reports.append(report)
            continue

        report.entries = len(entries)
        dirs = entry_include_dirs(entries)
        report.raw_dirs = len(dirs)

        if src.root_prefix:
            root = RootPrefix(prefix=normalize(src.root_prefix), votes=0,
                              total=len(dirs), derived=False)
        else:
            root = derive_root_prefix(dirs, project_root)
        report.root_prefix = root

        if root is None:
            logger.warning(
                "compile_commands: %s - no include dir from %s resolves under %s; "
                "set clang.compileCommands.%s.rootPrefix",
                src.core, src.path, project_root, src.core)
            reports.append(report)
            continue

        kept, unmapped, missing = apply_root_prefix(dirs, root.prefix, project_root)
        report.kept_dirs = len(kept)
        report.unmapped = unmapped
        report.missing = missing

        bucket = by_layer.setdefault(src.layer, [])
        seen = seen_by_layer.setdefault(src.layer, set())
        for d in kept:
            if d not in seen:
                seen.add(d)
                bucket.append(d)
        reports.append(report)

    return by_layer, reports


def sources_from_layers(cfg: Dict[str, Any], base_dir: str) -> List[CoreSource]:
    """Resolve each layer's cores into `CoreSource`s.

        "cores": {
          "Core1": {
            "dataDictionary": "...csv",
            "macros": "...json",
            "compileCommands": "build/core1/compile_commands.json"
          }
        },
        "layers": {
          "Layer1": {"path": "Layer1", "cores": ["Core1"], "groups": {...}}
        }

    A core owns its build inputs - one macro set, one dictionary, one compilation
    database - and a layer names the cores it is built from. The layer a database
    feeds is therefore never written twice, and an include dir cannot be declared
    without one.

    `compileCommands` is a path string, or an object (`file` + optional
    `rootPrefix`) when derivation has to be overridden. A relative path resolves
    against `base_dir`. Cores are emitted in layer order, then in the order the
    layer lists them, so the merged include list is reproducible.
    """
    from .config import core_source, get_layer_cores  # local: avoids an import cycle

    out: List[CoreSource] = []
    for layer_name in ((cfg or {}).get("layers") or {}):
        for core in get_layer_cores(cfg, layer_name):
            spec = ((cfg.get("cores") or {}).get(core) or {}).get("compileCommands")
            if isinstance(spec, dict):
                file_path = spec.get("file") or spec.get("path")
                root_prefix = spec.get("rootPrefix")
            elif isinstance(spec, str) or spec is None:
                file_path, root_prefix = core_source(cfg, core, "compileCommands"), None
            else:
                logger.warning("compile_commands: cores.%s.compileCommands must be a path "
                               "or an object - skipped", core)
                continue
            if not file_path:
                continue          # a core need not have a database
            abs_path = file_path if os.path.isabs(file_path) else os.path.join(base_dir, file_path)
            out.append(CoreSource(core=core, path=normalize(abs_path), layer=layer_name,
                                  root_prefix=root_prefix))
    return out


def format_report(report: LoadReport) -> List[str]:
    """Human-readable lines for one core - logged by `run.py`."""
    lines = [f"  {report.core} -> {report.layer}: "
             f"{report.entries} entries, {report.kept_dirs}/{report.raw_dirs} include dirs"]
    root = report.root_prefix
    if root is None:
        lines.append("    root prefix   : NOT DERIVED (no dir resolved locally)")
        return lines
    how = "derived" if root.derived else "configured"
    detail = f" ({root.votes}/{root.total} dirs)" if root.derived else ""
    lines.append(f"    root prefix   : {root.prefix} [{how}]{detail}")
    if root.derived and root.total and root.share < _MIN_VOTE_SHARE:
        lines.append(f"    WARNING       : only {root.share:.0%} of dirs agree on that prefix "
                     "- multi-root build or partial checkout?")
    if report.unmapped:
        lines.append(f"    unmapped      : {len(report.unmapped)} (e.g. {report.unmapped[0]})")
    if report.missing:
        lines.append(f"    not on disk   : {len(report.missing)} (e.g. {report.missing[0]})")
    return lines
