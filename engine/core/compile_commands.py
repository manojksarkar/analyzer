"""Include paths for Clang, read from build-system `compile_commands.json`.

The build is the only place that knows the real `-I` set: a firmware tree
compiles the same headers under several roots (`04_FIL`, `05_CTRL`,
`00_SRC/03_EXT_LIB`, ...) with 50-100+ include dirs per translation unit, and
`run.py`'s directory walk can only guess at it. A compilation database records
what the compiler was actually given, so reading it turns that guess into
ground truth.

Scope of this module: **include paths, `-D` macros and the target flags**. The `-D`
flags (review SWE3-017) are each layer's first macro source; the project's macros file
(`core.macro_input`) is loaded after them and wins on a name - a build database cannot
see header-defined macros, so it supplements that file rather than replacing it. The
target flags (`--target`, `-mcpu`, `-fshort-enums`, ... - `target_args`) and `-include`
files are read since 2026-11-25; every other flag is ignored, and the parser checks the
ones read with libclang before it uses them, so a flag libclang rejects cannot stop a parse.

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


# Review SWE3-017: code under an `#if` on a macro the build defines was missing, because
# the parse defined only what the project's macros file names. The build's `-D` flags are
# now read too -- they become each layer's FIRST macro source, so a project's own macros
# file still wins on a name. `-U` is counted, not applied.
_DEFINE_FLAGS = ("-D", "/D")


def define_args(arguments: Sequence[str]) -> List[Tuple[str, Optional[str]]]:
    """The `-D` operands of one `arguments` array as (name, value or None), in order."""
    out: List[Tuple[str, Optional[str]]] = []
    args = [str(a) for a in (arguments or [])]
    i = 0
    while i < len(args):
        arg, operand = args[i], None
        for flag in _DEFINE_FLAGS:
            if arg == flag:
                if i + 1 < len(args):
                    operand = args[i + 1]
                    i += 1
                break
            if arg.startswith(flag) and len(arg) > len(flag):
                operand = arg[len(flag):]
                break
        if operand:
            name, eq, value = operand.partition("=")
            if name and "(" not in name:            # function-like: fragile as a -D
                out.append((name, value if eq else None))
        i += 1
    return out


def entry_defines(entries: Iterable[Dict[str, Any]]) -> Tuple[Dict[str, Optional[str]], List[str]]:
    """Every `-D` across `entries`: {name: value}, and the names whose value differs between
    files. One value per name, the one most files use (the first seen on a tie): one parse
    defines one set per layer."""
    seen: Dict[str, Counter] = {}
    for entry in entries:
        args = entry.get("arguments")
        if args is None and entry.get("command"):
            args = str(entry["command"]).split()
        for name, value in dict(define_args(args or [])).items():
            seen.setdefault(name, Counter())[value] += 1
    defines = {name: counts.most_common(1)[0][0] for name, counts in seen.items()}
    differ = sorted(name for name, counts in seen.items() if len(counts) > 1)
    return defines, differ


def load_defines(sources: Sequence["CoreSource"]) -> Tuple[Dict[str, Dict[str, Optional[str]]],
                                                           List[str]]:
    """Each layer's `-D` flags from its cores' databases: ({layer: {name: value}}, log lines).
    Cores sharing a layer: the first core's value wins on a name."""
    by_layer: Dict[str, Dict[str, Optional[str]]] = {}
    lines: List[str] = []
    for src in sources:
        try:
            entries = read_entries(src.path)
        except (OSError, ValueError):
            continue                                # load_sources already said so
        defines, differ = entry_defines(entries)
        if not defines:
            continue
        bucket = by_layer.setdefault(src.layer, {})
        for name, value in defines.items():
            bucket.setdefault(name, value)
        line = f"  {src.layer} ({src.core}): {len(defines)} macro(s) from compile_commands"
        if differ:
            line += (f"; {len(differ)} differ between files, the most used value kept: "
                     + ", ".join(differ[:10]) + (" ..." if len(differ) > 10 else ""))
        lines.append(line)
    return by_layer, lines


# How the code READS depends on more than -I and -D: the CPU sets `__ARM_ARCH` and friends,
# `-fshort-enums` the size of an enum, `-ffreestanding` whether <stdint.h> reaches the C
# library (2026-11-25). Measured one by one on libclang 21: these change its predefined macros
# or what it accepts. Not taken: `-O` and position independence (code generation),
# `-fno-rtti` / `-fno-exceptions` (they reject `typeid` / `try` rather than change how code
# reads, and code built with them has none), `-std` / `-x` (the parser reads every file as
# C++14), warnings, outputs, response files.
_TARGET_VALUE_FLAGS = ("--target=", "-mcpu=", "-march=", "-mfpu=", "-mfloat-abi=")
_TARGET_SWITCHES = frozenset((
    "-mthumb", "-marm", "-mbig-endian", "-mlittle-endian", "-mno-unaligned-access",
    "-munaligned-access", "-mcmse",
    "-fshort-enums", "-fno-short-enums", "-fshort-wchar", "-fno-short-wchar",
    "-funsigned-char", "-fno-unsigned-char", "-fsigned-char", "-fno-signed-char",
    "-ffreestanding", "-fms-extensions", "-fno-ms-extensions", "-fdeclspec", "-fno-declspec",
))


def target_args(arguments: Sequence[str]) -> List[str]:
    """The flags of one `arguments` array that change how the code reads, in order; the
    separate `-target X` as `--target=X`, so every flag is one argument."""
    out: List[str] = []
    args = [str(a) for a in (arguments or [])]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-target", "--target"):
            if i + 1 < len(args):
                out.append("--target=" + args[i + 1])
                i += 1
        elif arg.startswith(_TARGET_VALUE_FLAGS) or arg in _TARGET_SWITCHES:
            out.append(arg)
        i += 1
    return out


def include_file_args(arguments: Sequence[str]) -> List[str]:
    """The `-include <file>` operands (a file the build reads before the source), in order."""
    out: List[str] = []
    args = [str(a) for a in (arguments or [])]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-include":
            if i + 1 < len(args):
                out.append(args[i + 1])
                i += 1
        elif arg.startswith("-include") and len(arg) > len("-include"):
            out.append(arg[len("-include"):])
        i += 1
    return out


def _entry_args(entry: Dict[str, Any]) -> List[str]:
    args = entry.get("arguments")
    if args is None and entry.get("command"):
        args = str(entry["command"]).split()
    return [str(a) for a in (args or [])]


def compiler_name(sources: Sequence["CoreSource"]) -> str:
    """The compiler the build runs, as the first argument of its databases names it
    (`armclang`, or a path on the build machine); "" when none names one."""
    for src in sources:
        try:
            entries = read_entries(src.path)
        except (OSError, ValueError):
            continue
        for entry in entries:
            args = _entry_args(entry)
            if args and not args[0].startswith("-"):
                return args[0]
    return ""


def _map_file(path: str, prefix: Optional[str], project_root: str) -> Optional[str]:
    """A file of the build machine, on this one: under the derived prefix, moved onto
    `project_root`; relative, joined to it. None when it is elsewhere or not here."""
    local_root = normalize(project_root)
    if prefix:
        pref = normalize(prefix).rstrip("/")
        if path == pref or path.startswith(pref + "/"):
            mapped = normalize(posixpath.join(local_root, path[len(pref):].lstrip("/")))
            return mapped if os.path.isfile(mapped) else None
    if not _is_absolute(path):
        mapped = normalize(posixpath.join(local_root, path))
        return mapped if os.path.isfile(mapped) else None
    return None


def load_flags(sources: Sequence["CoreSource"],
               project_root: str) -> Tuple[Dict[str, List[str]], List[str]]:
    """Each layer's target flags (`target_args`) and `-include` files from its cores' databases:
    ({layer: [arg, ...]}, log lines). One set per layer, as one parse takes one: the set most
    files use (the first seen on a tie), the files with another named in the log. Cores sharing
    a layer: the first core's set. A `-include` file moves onto `project_root` like an include
    dir; one that is not here is left out and named."""
    by_layer: Dict[str, List[str]] = {}
    lines: List[str] = []
    for src in sources:
        try:
            entries = read_entries(src.path)
        except (OSError, ValueError):
            continue                                # load_sources already said so
        root = src.root_prefix
        if root is None and any(include_file_args(_entry_args(e)) for e in entries):
            derived = derive_root_prefix(entry_include_dirs(entries), project_root)
            root = derived.prefix if derived else None
        sets: Counter = Counter()
        first_file: Dict[Tuple[str, ...], str] = {}
        not_here: List[str] = []
        for entry in entries:
            args = _entry_args(entry)
            flags = target_args(args)
            directory = normalize(entry.get("directory") or "")
            for raw in include_file_args(args):
                build_path = _resolve(directory, raw)
                mapped = _map_file(build_path, root, project_root)
                if mapped:
                    flags.append("-include" + mapped)
                elif build_path not in not_here:
                    not_here.append(build_path)
            key = tuple(flags)
            sets[key] += 1
            first_file.setdefault(key, str(entry.get("file") or ""))
        if not sets or not any(sets):
            continue
        chosen = max(sets, key=lambda k: (sets[k], -list(sets).index(k)))
        if not chosen:
            continue
        if src.layer in by_layer:
            if list(chosen) != by_layer[src.layer]:
                lines.append(f"  {src.layer} ({src.core}): other flags than the layer's first core "
                             f"-- not used: {' '.join(chosen)}")
            continue
        by_layer[src.layer] = list(chosen)
        line = (f"  {src.layer} ({src.core}): {' '.join(chosen)} "
                f"({sets[chosen]} of {sum(sets.values())} files)")
        others = [k for k in sets if k != chosen]
        if others:
            line += "; other flags in: " + ", ".join(
                f"{first_file[k] or '?'} ({' '.join(k) or 'none'})" for k in others[:3])
            line += " ..." if len(others) > 3 else ""
        lines.append(line)
        for path in not_here:
            lines.append(f"    -include not found here, left out: {path}")
    return by_layer, lines


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
