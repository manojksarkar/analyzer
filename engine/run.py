#!/usr/bin/env python3
"""Entry: python engine/run.py [options] <project_path>

Options:
  -h, --help           Show this help and exit
  --clean              Delete output/ and model/ before running
  --config <path>      Use this config file instead of engine/config/config.json
                       (a per-project/per-version config carrying the project's
                       `layers`). Exported as ANALYZER_CONFIG so every phase
                       subprocess honors it. config.local.json is NOT merged on
                       top — the injected config is used as-is.
  --use-model          Skip Phase 1/2 and reuse existing model/ files
  --skip-model         Alias of --use-model
  --no-llm-summarize   Skip LLM phase/hierarchy summarization (faster, lower quality)
  --llm-summarize      Accepted for back-compat; no-op (summarization is the default)
  --selected-group <name>
                       Export only the named group (case-insensitive). Mutually
                       exclusive with --selected-layer / --selected-component.
  --selected-layer <name>
                       Parse only the named layer; emit one DOCX per group in it.
  --selected-component <name>
                       Export a DOCX for the named component only. Repeatable —
                       all named components must live in the same layer.
  --component-per-docx One DOCX per component instead of one per group. Cannot be
                       combined with --selected-component.
  --selected-unit <name>
                       Narrow Phase 3 to the named unit(s) — flowcharts are built
                       for those units only. Repeatable. A development aid: the
                       expensive per-function work is skipped for everything else,
                       while the model stays whole so derived content is unchanged.
  --filter-mode <mode> Override views.sequenceDiagrams.filterMode for this run.
                       Forwarded to Phase 3 (run_views), which writes it into the
                       in-memory config. NOTE: no view reads that key yet, so the
                       flag is currently inert — wire up a consumer before relying
                       on it. Any string is accepted (no fixed vocabulary yet).
  --from-phase N       Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export)
  --to-phase N         Stop after phase N (1-4). Lets the incremental engine run
                       parse+derive only (--to-phase 2), compute impact, then
                       resume views+export (--from-phase 3).
  --data-dictionary <path>
                       CSV file to merge into model/dataDictionary.json (overrides
                       auto-parsed entries). See engine/config/data_dictionary.csv for format.
  --project-name <name>
                       Override the project name used in metadata and
                       interfaceIds (default: basename of project_path).
  --output-name <name> Override the output subdirectory and DOCX basename
                       (default: the selected group / component name).
  --macros <path>      Macro file passed as -D flags to Clang, for every layer.
                       CSV (Name, Value) or JSON (toolchain dump, {"NAME":"VAL"}
                       map, ["NAME=VAL"] list, or {"Layer": {...}}). Rows with
                       Value="ne" are skipped. Empty Value → -DMACRONAME.
  --macros-layer <layer> <path>
                       Same file formats, but applied to the named layer only.
                       Repeatable — use once per layer. Overrides --macros for
                       that layer's parse. Samples in engine/config/. Example:
                         --macros-layer Layer1 engine/config/macros.layer1.example.json \\
                         --macros-layer Layer2 engine/config/macros.layer2.example.json
  --only-files <path>  Parse only the translation units listed in this file, one
                       path per line (narrowed parse, used by the incremental engine).
  --include-emulator   Parse emulator/stub files too. By default files whose
                       basename matches config `excludeNamePatterns` (default
                       ["emul"]) are skipped from the parse scope (3.1).
  --include-path <layer> <dir>
                       Add an extra -I include directory for the named layer.
                       Repeatable. Merged into clang_include_paths.json before
                       Phase 1, so layer-scoping in Phase 1 and Phase 3 is
                       automatic. Example:
                         --include-path Layer1 C:/ThirdParty/boost/include
  --verbose            Enable DEBUG logs (cache hits, budgets, few-shot picks)
  --quiet              Only log WARNINGs and above
  --trace-prompts      Print full LLM prompts (system + user) to stdout.
                       WARNING: large runs can emit tens of MB of prompt text.

Unknown options and extra positional arguments are rejected with exit code 1.

Examples:
  python engine/run.py test_cpp_project
  python engine/run.py --clean test_cpp_project
  python engine/run.py --no-llm-summarize test_cpp_project
  python engine/run.py --from-phase 3 test_cpp_project
  python engine/run.py --selected-group MyGroup test_cpp_project
  python engine/run.py --data-dictionary engine/config/data_dictionary.csv SampleCppProject
"""
import datetime as _dt
import difflib
import os
import shutil
import sys

# Force UTF-8 on stdout/stderr so non-ASCII source text (e.g. Korean/Chinese
# identifiers or comments) doesn't crash prints with UnicodeEncodeError on
# Windows (where the default code page is cp1252). Propagate via
# PYTHONIOENCODING so every Python subprocess we spawn inherits the same
# encoding. errors='replace' keeps the run alive even if one character is
# un-representable in the target encoding.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# --help / -h: print the option list and exit before any setup work — no log file,
# no chdir, no config load. Handled here so `--help` still answers when the config
# or environment is broken. The docstring above IS the help text.
if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
    print(__doc__ or "")
    sys.exit(0)

# run.py now lives in engine/; the repo root (holding engine/, model/, output/,
# workspaces/) is one level up. SCRIPT_DIR is kept pointing at the repo root so every
# repo-root-relative join below (chdir, model dir, SCRIPT_DIR/engine on sys.path,
# PhaseRunner root, --config / --data-dictionary / project-path resolution) is unchanged.
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "engine"))

# Bring up logging early so every subsequent log() call (and every subprocess
# this script spawns inheriting LOG_LEVEL) gets the same handlers.
from core.logging_setup import configure_logging
_quiet_flag = "--quiet" in sys.argv
_verbose_flag = "--verbose" in sys.argv
_trace_prompts_flag = "--trace-prompts" in sys.argv
if _verbose_flag:
    os.environ.setdefault("LOG_LEVEL", "DEBUG")
elif _quiet_flag:
    os.environ.setdefault("LOG_LEVEL", "WARNING")
if _trace_prompts_flag:
    os.environ.setdefault("LLM_TRACE_PROMPTS", "1")
# One id for the whole run, inherited by every phase subprocess, so their
# per-process LLM stats files land in the same directory and can be merged
# into a single report at the end (see the LLM report block at the bottom).
os.environ.setdefault("ANALYZER_RUN_ID", _dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
_log_path = configure_logging(project_root=SCRIPT_DIR, quiet=_quiet_flag, verbose=_verbose_flag)

# --config <path>: inject a per-project/per-version config (carries the project's
# `layers`). Resolve + validate and export ANALYZER_CONFIG *before* importing
# utils, which loads config at import time — so this process AND every phase
# subprocess (env inherited) honor the override. core.config.load_config reads
# ANALYZER_CONFIG. The flag is also consumed in the main argv loop below.
if "--config" in sys.argv:
    _ci = sys.argv.index("--config")
    _cv = sys.argv[_ci + 1] if _ci + 1 < len(sys.argv) else None
    if not _cv:
        sys.stderr.write("--config requires a file path\n")
        sys.exit(1)
    _cfg_abs = _cv if os.path.isabs(_cv) else os.path.join(SCRIPT_DIR, _cv)
    if not os.path.isfile(_cfg_abs):
        sys.stderr.write(f"--config file not found: {_cfg_abs}\n")
        sys.exit(1)
    os.environ["ANALYZER_CONFIG"] = _cfg_abs

from utils import log, load_config
from core import PhaseRunner, plan_runs
from core.model_io import model_file_path as _mfp, FUNCTIONS, GLOBALS, UNITS, COMPONENTS

# ---------------------------------------------------------------------------
# Parse flags
# ---------------------------------------------------------------------------

# Every option the loop below accepts. Held as data (rather than derived from the
# branches) so an unrecognised option can be rejected with a "did you mean" hint.
# tests/unit/test_cli.py asserts this stays in sync with the branches — add a flag
# here whenever you add a branch, or the test fails.
_KNOWN_FLAGS = (
    "--help", "-h",
    "--clean", "--config",
    "--use-model", "--skip-model",
    "--no-llm-summarize", "--llm-summarize",
    "--selected-group", "--selected-layer", "--selected-component", "--selected-unit",
    "--component-per-docx", "--filter-mode",
    "--from-phase", "--to-phase",
    "--data-dictionary", "--project-name", "--output-name",
    "--macros", "--macros-layer", "--include-path",
    "--only-files", "--include-emulator",
    "--quiet", "--verbose", "--trace-prompts",
)

clean_all               = False
use_model               = False
no_llm_summarize        = False
from_phase              = 1
to_phase                = None   # stop after this phase (1-4); None = run through phase 4
selected_group_arg      = None
selected_layer_arg      = None
selected_components_arg = []
selected_units_arg      = []   # dev aid: narrow Phase 3 to these unit(s)
component_per_docx      = False
filter_mode_arg         = None
data_dictionary_arg     = None
macros_arg              = None
macros_layer_args       = []   # list of (layer_name, path) tuples
project_name_arg        = None
output_name_arg         = None
only_files_arg          = None   # narrowed parse (M4.4): file listing the TUs to parse
include_emulator_arg    = False  # opt out of the default *emul* file exclusion (3.1)
include_path_args       = []   # list of (layer_name, abs_dir) tuples
raw_args                = []

i = 1
while i < len(sys.argv):
    a = sys.argv[i]
    if a == "--clean":
        clean_all = True
    elif a in ("--quiet", "--verbose", "--trace-prompts", "--help", "-h"):
        pass  # consumed at top of file (help / configure_logging / env vars)
    elif a == "--config":
        # Value already resolved + applied to ANALYZER_CONFIG above; just consume it.
        i += 1
        if i >= len(sys.argv):
            log("--config requires a file path", component="run", err=True)
            sys.exit(1)
    elif a in ("--use-model", "--skip-model"):
        use_model = True
    elif a == "--no-llm-summarize":
        no_llm_summarize = True
    elif a == "--llm-summarize":
        # Accepted for backwards-compatibility; summarization is ON by default.
        pass
    elif a == "--selected-group":
        i += 1
        if i >= len(sys.argv):
            log("--selected-group requires a group name", component="run", err=True)
            sys.exit(1)
        selected_group_arg = sys.argv[i]
    elif a == "--selected-layer":
        i += 1
        if i >= len(sys.argv):
            log("--selected-layer requires a layer name", component="run", err=True)
            sys.exit(1)
        selected_layer_arg = sys.argv[i]
    elif a == "--selected-component":
        i += 1
        if i >= len(sys.argv):
            log("--selected-component requires a component name", component="run", err=True)
            sys.exit(1)
        selected_components_arg.append(sys.argv[i].replace(" ", "-"))
    elif a == "--selected-unit":
        i += 1
        if i >= len(sys.argv):
            log("--selected-unit requires a unit name", component="run", err=True)
            sys.exit(1)
        selected_units_arg.append(sys.argv[i])
    elif a == "--component-per-docx":
        component_per_docx = True
    elif a == "--filter-mode":
        i += 1
        if i >= len(sys.argv):
            log("--filter-mode requires a mode argument", component="run", err=True)
            sys.exit(1)
        filter_mode_arg = sys.argv[i]
    elif a == "--data-dictionary":
        i += 1
        if i >= len(sys.argv):
            log("--data-dictionary requires a file path", component="run", err=True)
            sys.exit(1)
        data_dictionary_arg = sys.argv[i]
    elif a == "--macros":
        i += 1
        if i >= len(sys.argv):
            log("--macros requires a file path", component="run", err=True)
            sys.exit(1)
        macros_arg = sys.argv[i]
    elif a == "--macros-layer":
        if i + 2 >= len(sys.argv):
            log("--macros-layer requires two arguments: <layer> <path>", component="run", err=True)
            sys.exit(1)
        macros_layer_args.append((sys.argv[i + 1], sys.argv[i + 2]))
        i += 2
    elif a == "--only-files":
        i += 1
        if i >= len(sys.argv):
            log("--only-files requires a file path", component="run", err=True)
            sys.exit(1)
        only_files_arg = sys.argv[i]
    elif a == "--include-emulator":
        include_emulator_arg = True
    elif a == "--project-name":
        i += 1
        if i >= len(sys.argv):
            log("--project-name requires a name argument", component="run", err=True)
            sys.exit(1)
        project_name_arg = sys.argv[i]
    elif a == "--output-name":
        i += 1
        if i >= len(sys.argv):
            log("--output-name requires a name argument", component="run", err=True)
            sys.exit(1)
        output_name_arg = sys.argv[i]
    elif a == "--include-path":
        if i + 2 >= len(sys.argv):
            log("--include-path requires two arguments: <layer> <dir>", component="run", err=True)
            sys.exit(1)
        include_path_args.append((sys.argv[i + 1], sys.argv[i + 2]))
        i += 2
    elif a == "--from-phase":
        i += 1
        if i >= len(sys.argv):
            log("--from-phase requires an integer argument (1-4)", component="run", err=True)
            sys.exit(1)
        try:
            from_phase = int(sys.argv[i])
            if from_phase < 1 or from_phase > 4:
                raise ValueError
        except ValueError:
            log(f"--from-phase must be 1, 2, 3, or 4 (got: {sys.argv[i]})", component="run", err=True)
            sys.exit(1)
    elif a == "--to-phase":
        i += 1
        if i >= len(sys.argv):
            log("--to-phase requires an integer argument (1-4)", component="run", err=True)
            sys.exit(1)
        try:
            to_phase = int(sys.argv[i])
            if to_phase < 1 or to_phase > 4:
                raise ValueError
        except ValueError:
            log(f"--to-phase must be 1, 2, 3, or 4 (got: {sys.argv[i]})", component="run", err=True)
            sys.exit(1)
    elif a.startswith("-"):
        # Anything dash-prefixed that reached here is a typo or a flag that no
        # longer exists. Silently ignoring it used to let a whole run proceed with
        # the wrong settings (e.g. `--phase 3` was dropped and the run restarted
        # from Phase 1), so refuse to start instead.
        log(f"Unknown option: {a}", component="run", err=True)
        # cutoff 0.7, not the 0.6 default: 0.6 pairs `--phase` with `--help` and
        # `--verbos` with `--macros`, which reads as noise next to the real match.
        _near = difflib.get_close_matches(a, _KNOWN_FLAGS, n=3, cutoff=0.7)
        if _near:
            log(f"  did you mean: {', '.join(_near)}", component="run", err=True)
        log("Run `python engine/run.py --help` to see all options.", component="run", err=True)
        sys.exit(1)
    else:
        raw_args.append(a)
    i += 1

def _resolve_group_name(groups: dict, requested: str | None) -> str | None:
    """Resolve requested group name against config.layer, case-insensitive."""
    if not requested:
        return None
    if not isinstance(groups, dict) or not groups:
        return None
    if requested in groups:
        return requested
    req_key = requested.casefold()
    for k in groups.keys():
        if isinstance(k, str) and k.casefold() == req_key:
            return k
    return None

if sum(bool(x) for x in [selected_group_arg, selected_layer_arg, selected_components_arg]) > 1:
    log("--selected-group, --selected-layer, and --selected-component are mutually exclusive", component="run", err=True)
    sys.exit(1)
if component_per_docx and selected_components_arg:
    log("--component-per-docx cannot be combined with --selected-component", component="run", err=True)
    sys.exit(1)

if len(raw_args) < 1:
    print("Usage: python engine/run.py [--clean] [--use-model|--skip-model] [--selected-group <name>]")
    print("                     [--selected-layer <name>] [--no-llm-summarize] [--from-phase N]")
    print("                     [--selected-component <name> [--selected-component <name> ...]]")
    print("                     [--quiet|--verbose] [--trace-prompts] [--filter-mode MODE]")
    print("                     <project_path>")
    print("Example: python engine/run.py test_cpp_project")
    print("Example: python engine/run.py --selected-component Gpio SampleCppProject")
    print("Run `python engine/run.py --help` to see all options.")
    sys.exit(1)

# Exactly one positional is expected. A second one is almost always a flag value
# that lost its flag (`--phase 3` leaves a stray `3`) or a second path — both mean
# the command line does not say what the user thinks it says.
if len(raw_args) > 1:
    log(f"Unexpected extra argument(s): {', '.join(raw_args[1:])}", component="run", err=True)
    log(f"Only one <project_path> is accepted (got: {raw_args[0]}).", component="run", err=True)
    log("Run `python engine/run.py --help` to see all options.", component="run", err=True)
    sys.exit(1)

project_path = raw_args[0]
resolved = os.path.abspath(project_path) if os.path.isabs(project_path) else os.path.join(SCRIPT_DIR, project_path)
if not os.path.isdir(resolved):
    log(f"Project path not found: {resolved}", component="run", err=True)
    sys.exit(1)

# --clean runs only AFTER the project path is known good. It used to run first, so
# a typo'd path wiped model/ and output/ and *then* aborted — leaving nothing to
# fall back on and forcing a full re-parse.
if clean_all:
    for d in ("output", "model"):
        path = os.path.join(SCRIPT_DIR, d)
        if os.path.isdir(path):
            shutil.rmtree(path)
            log(f"Removed {d}/", component="run")

# ---------------------------------------------------------------------------
# When --use-model is set, refuse early if model files are missing.
# ---------------------------------------------------------------------------
if use_model:
    MODEL_FILES = (_mfp(FUNCTIONS), _mfp(GLOBALS), _mfp(UNITS), _mfp(COMPONENTS))
    missing = [p for p in MODEL_FILES if not os.path.isfile(p)]
    if missing:
        log(f"--use-model set but model files missing: {missing[0]}", component="run", err=True)
        sys.exit(2)
    log("Using existing model/ (skipping Phase 1/2).", component="run")

# ---------------------------------------------------------------------------
# Plan and run
# ---------------------------------------------------------------------------
if os.environ.get("ANALYZER_CONFIG"):
    log(f"Using injected config (--config): {os.environ['ANALYZER_CONFIG']}", component="run")
cfg = load_config(os.path.join(SCRIPT_DIR, "engine"))
if not (cfg.get("llm") or {}).get("summarize", True):
    no_llm_summarize = True

data_dictionary_path = data_dictionary_arg or None
if data_dictionary_path:
    _dd_abs = data_dictionary_path if os.path.isabs(data_dictionary_path) \
              else os.path.join(SCRIPT_DIR, data_dictionary_path)
    if not os.path.isfile(_dd_abs):
        log(f"--data-dictionary file not found: {_dd_abs}", component="run", err=True)
        sys.exit(2)
    data_dictionary_path = _dd_abs

macros_path = macros_arg or None
if macros_path:
    _m_abs = macros_path if os.path.isabs(macros_path) \
             else os.path.join(SCRIPT_DIR, macros_path)
    if not os.path.isfile(_m_abs):
        log(f"--macros file not found: {_m_abs}", component="run", err=True)
        sys.exit(2)
    macros_path = _m_abs

# Layer names are validated further down, once the config is loaded.
macros_layer_paths = []
for _ml_layer, _ml_path in macros_layer_args:
    _ml_abs = _ml_path if os.path.isabs(_ml_path) else os.path.join(SCRIPT_DIR, _ml_path)
    if not os.path.isfile(_ml_abs):
        log(f"--macros-layer file not found: {_ml_abs}", component="run", err=True)
        sys.exit(2)
    macros_layer_paths.append((_ml_layer, _ml_abs))


# ---------------------------------------------------------------------------
# Collect layer include paths before any phase runs.
# Written to model/clang_include_paths.json so Phase 1 (parser) and Phase 3
# (flowchart engine) can read them without re-walking the filesystem.
# ---------------------------------------------------------------------------
import json as _json
from core.config import (get_flat_groups as _get_flat_groups,
                         get_group_layer_name as _get_group_layer_name,
                         get_component_layer_name as _get_component_layer_name)
_model_dir = os.path.join(SCRIPT_DIR, "model")
os.makedirs(_model_dir, exist_ok=True)
_all_groups = _get_flat_groups(cfg)
_resolved_group = _resolve_group_name(_all_groups, selected_group_arg)

# Validate --selected-component: all must exist and be in the same layer.
if selected_components_arg:
    _all_comp_names: set = set()
    for _g in _all_groups.values():
        if isinstance(_g, dict):
            _all_comp_names.update(_g.keys())
    # Normalize to identifier form for comparison (spaces -> -)
    _all_comp_names_norm = {c.replace(" ", "-") for c in _all_comp_names}
    for _c in selected_components_arg:  # already normalized at collection
        if _c not in _all_comp_names_norm:
            log(f"Unknown component {_c!r}. Valid components: {', '.join(sorted(_all_comp_names_norm))}", component="run", err=True)
            sys.exit(1)
    _comp_layers = {_c: _get_component_layer_name(cfg, _c) for _c in selected_components_arg}
    _unique_layers = set(_comp_layers.values())
    if len(_unique_layers) > 1:
        _detail = ", ".join(f"{c!r}->{l}" for c, l in _comp_layers.items())
        log(f"All --selected-component names must be in the same layer ({_detail})", component="run", err=True)
        sys.exit(1)
    _derived_layer_for_components = next(iter(_unique_layers))
else:
    _derived_layer_for_components = None

if selected_layer_arg:
    _selected_layer = selected_layer_arg
elif _resolved_group:
    _selected_layer = _get_group_layer_name(cfg, _resolved_group)
elif _derived_layer_for_components:
    _selected_layer = _derived_layer_for_components
else:
    _selected_layer = None
_layer_inc: dict = {}
for _lname, _layer in (cfg.get("layers") or {}).items():
    if _selected_layer and _lname != _selected_layer:
        continue
    if not isinstance(_layer, dict):
        continue
    _layer_rel = _layer.get("path") or _lname
    _layer_abs = os.path.join(resolved, _layer_rel)
    if not os.path.isdir(_layer_abs):
        continue
    _dirs: list = []
    for _dirpath, _dirnames, _ in os.walk(_layer_abs):
        _dirnames[:] = [d for d in _dirnames if not d.startswith(".")]
        _dirs.append(_dirpath)
    _layer_inc[_lname] = _dirs

# Validate and merge --include-path <layer> <dir> entries.
_known_layers = set((cfg.get("layers") or {}).keys())
for _ml_layer, _ in macros_layer_paths:
    if _ml_layer not in _known_layers:
        log(f"--macros-layer: unknown layer {_ml_layer!r}. Valid layers: {', '.join(sorted(_known_layers))}", component="run", err=True)
        sys.exit(1)
for _ip_layer, _ip_dir in include_path_args:
    if _ip_layer not in _known_layers:
        log(f"--include-path: unknown layer {_ip_layer!r}. Valid layers: {', '.join(sorted(_known_layers))}", component="run", err=True)
        sys.exit(1)
    _ip_abs = _ip_dir if os.path.isabs(_ip_dir) else os.path.join(SCRIPT_DIR, _ip_dir)
    if not os.path.isdir(_ip_abs):
        log(f"--include-path: directory not found: {_ip_abs}", component="run", err=True)
        sys.exit(1)
    _layer_inc.setdefault(_ip_layer, [])
    if _ip_abs not in _layer_inc[_ip_layer]:
        _layer_inc[_ip_layer].append(_ip_abs)

_clang_paths_file = os.path.join(_model_dir, "clang_include_paths.json")
with open(_clang_paths_file, "w", encoding="utf-8") as _f:
    _json.dump(_layer_inc, _f, indent=2)
log("Layer include paths collected.", component="run")

# Prerequisite preflight: fail fast (before a long run) if a REQUIRED external
# dependency for THIS run's enabled views is missing — a clear message beats a
# cryptic subprocess error deep in a phase. View-gated so a parse-only run is not
# blocked by a missing browser/mmdc. Wrapped so the check itself can never abort a
# run; use `python tools/doctor.py` for the full report.
try:
    sys.path.insert(0, os.path.join(SCRIPT_DIR, "tools"))
    import doctor as _doctor  # noqa: WPS433
    _views = cfg.get("views") or {}
    _blocking = _doctor.preflight(
        need_flowchart=bool(_views.get("flowcharts")),
        need_mermaid=bool(_views.get("behaviourDiagram") or _views.get("unitDiagrams")),
    )
    if _blocking:
        log("Missing prerequisites for this run:", component="run", err=True)
        for _c in _blocking:
            log(f"  [FAIL] {_c.name}: {_c.detail}", component="run", err=True)
            if _c.fix:
                log(f"         -> {_c.fix}", component="run", err=True)
        log("Run `python tools/doctor.py` for the full report.", component="run", err=True)
        sys.exit(2)
except SystemExit:
    raise
except Exception as _pf_err:  # noqa: BLE001
    log(f"prerequisite preflight skipped ({_pf_err})", component="run")

# Resolve and display the LLM config up-front so the user sees exactly which
# provider, endpoint, model, and token budget the run will use. Fails loud
# (LlmConfigError) if any required field is missing or invalid — better to
# stop here than half-way through a long run.
from core.config import load_llm_config, format_llm_config_banner, LlmConfigError
try:
    _resolved_llm_cfg = load_llm_config(cfg)
    for _line in format_llm_config_banner(_resolved_llm_cfg).splitlines():
        log(_line, component="run")
except LlmConfigError as e:
    log(f"Invalid LLM config: {e}", component="run", err=True)
    sys.exit(2)

try:
    plans = plan_runs(
        cfg,
        project_path=resolved,
        selected_group=selected_group_arg,
        selected_layer=selected_layer_arg,
        selected_components=selected_components_arg,
        component_per_docx=component_per_docx,
        use_model=use_model,
        no_llm_summarize=no_llm_summarize,
        from_phase=from_phase,
        filter_mode=filter_mode_arg,
        data_dictionary_path=data_dictionary_path,
        macros_path=macros_path,
        macros_layer=macros_layer_paths,
        project_name=project_name_arg,
        output_name=output_name_arg,
        only_files=only_files_arg,
        include_emulator=include_emulator_arg,
        selected_units=selected_units_arg,
    )
except ValueError as e:
    log(str(e), component="run", err=True)
    sys.exit(2)

# --to-phase N: stop after global phase N. Drop phases mapped above N from every
# plan (and any plan left empty). Lets the incremental engine Phase-split (run
# parse+derive, compute impact, then resume views+export). Additive: when
# to_phase is None, plans are untouched.
if to_phase is not None:
    from core.group_planner import RunPlan as _RunPlan
    _SCRIPT_PHASE = {"parser.py": 1, "model_deriver.py": 2, "run_views.py": 3, "docx_exporter.py": 4}
    _filtered = []
    for _plan in plans:
        _kept = [ph for ph in _plan.phases
                 if _SCRIPT_PHASE.get(os.path.basename(ph.script), 99) <= to_phase]
        if _kept and _plan.runner_from_phase <= len(_kept):
            _filtered.append(_RunPlan(label=_plan.label, phases=_kept,
                                      runner_from_phase=_plan.runner_from_phase))
    plans = _filtered
    log(f"--to-phase {to_phase}: running {len(plans)} plan(s) up to phase {to_phase}.", component="run")

runner = PhaseRunner(project_root=SCRIPT_DIR)
total_time = 0.0
for plan in plans:
    log(plan.label, component="run")
    total_time += runner.run(plan.phases, from_phase=plan.runner_from_phase)

print(flush=True)
log(f"Done. Total: {total_time:.2f}s", component="run")

# LLM report for the whole run. Each phase subprocess wrote its own stats file
# on exit (core.logging_setup._emit_token_report); merge them into one table
# plus one JSON. Silent when the run made no LLM calls.
try:
    from core.logging_setup import llm_stats_dir as _stats_dir
    from llm_core import tokens as _tokens
    _merged = _tokens.merge_dir(_stats_dir())
    if (_merged.get("totals") or {}).get("calls"):
        _merged["totals"]["runSeconds"] = round(total_time, 2)
        _out = os.path.join(SCRIPT_DIR, "logs",
                            f"llm_stats_{os.environ.get('ANALYZER_RUN_ID', 'adhoc')}.json")
        with open(_out, "w", encoding="utf-8") as _fh:
            _json_mod = __import__("json")
            _json_mod.dump(_merged, _fh, indent=2)
        print(flush=True)
        print(_tokens.format_merged(_merged), flush=True)
        _llm_total = _merged["totals"]["totalSeconds"]
        _share = (100.0 * _llm_total / total_time) if total_time else 0.0
        log(f"LLM was {_llm_total:.1f}s of {total_time:.1f}s ({_share:.0f}% of the run). "
            f"Details: {_out}", component="run")
except Exception as _exc:  # pragma: no cover — reporting must never fail a run
    log(f"LLM report unavailable: {_exc}", component="run")

if _log_path:
    log(f"Full log: {_log_path}", component="run")
