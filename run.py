#!/usr/bin/env python3
"""Entry: python run.py [options] <project_path>

Options:
  --clean              Delete output/ and model/ before running
  --selected-group <name>
                       Export only the named modulesGroup
  --config <path>      Use this config file instead of config/config.json
                       (a per-project/per-version config carrying the project's
                       `layers`). Exported as ANALYZER_CONFIG so every phase
                       subprocess honors it. config.local.json is NOT merged on
                       top — the injected config is used as-is.
  --use-model          Skip Phase 1/2 and reuse existing model/ files
  --skip-model         Alias of --use-model
  --no-llm-summarize   Skip LLM phase/hierarchy summarization (faster, lower quality)
  --from-phase N       Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export)
  --to-phase N         Stop after phase N (1-4). Lets the incremental engine run
                       parse+derive only (--to-phase 2), compute impact, then
                       resume views+export (--from-phase 3).
  --data-dictionary <path>
                       CSV file to merge into model/dataDictionary.json (overrides
                       auto-parsed entries). See config/data_dictionary.csv for format.
  --project-name <name>
                       Override the project name used in metadata and
                       interfaceIds (default: basename of project_path).
  --macros <path>      CSV file (Name, Value) passed as -D flags to Clang. Rows
                       with Value="ne" are skipped. Empty Value → -DMACRONAME.
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

Examples:
  python run.py test_cpp_project
  python run.py --clean test_cpp_project
  python run.py --no-llm-summarize test_cpp_project
  python run.py --from-phase 3 test_cpp_project
  python run.py --selected-group MyGroup test_cpp_project
  python run.py --filter-mode single_per_function test_cpp_project
  python run.py --data-dictionary config/data_dictionary.csv SampleCppProject
"""
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "src"))

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

clean_all               = False
use_model               = False
no_llm_summarize        = False
from_phase              = 1
to_phase                = None   # stop after this phase (1-4); None = run through phase 4
selected_group_arg      = None
selected_layer_arg      = None
selected_components_arg = []
component_per_docx      = False
filter_mode_arg         = None
data_dictionary_arg     = None
macros_arg              = None
project_name_arg        = None
output_name_arg         = None
include_path_args       = []   # list of (layer_name, abs_dir) tuples
raw_args                = []

i = 1
while i < len(sys.argv):
    a = sys.argv[i]
    if a == "--clean":
        clean_all = True
    elif a in ("--quiet", "--verbose", "--trace-prompts"):
        pass  # consumed at top of file (configure_logging / env vars)
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
    elif a == "--component-per-docx":
        component_per_docx = True
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
    print("Usage: python run.py [--clean] [--use-model|--skip-model] [--selected-group <name>]")
    print("                     [--selected-layer <name>] [--no-llm-summarize] [--from-phase N]")
    print("                     [--selected-component <name> [--selected-component <name> ...]]")
    print("                     [--quiet|--verbose] [--trace-prompts] [--filter-mode MODE]")
    print("                     <project_path>")
    print("Example: python run.py test_cpp_project")
    print("Example: python run.py --selected-component Gpio SampleCppProject")
    sys.exit(1)

if clean_all:
    for d in ("output", "model"):
        path = os.path.join(SCRIPT_DIR, d)
        if os.path.isdir(path):
            shutil.rmtree(path)
            log(f"Removed {d}/", component="run")

project_path = raw_args[0]
resolved = os.path.abspath(project_path) if os.path.isabs(project_path) else os.path.join(SCRIPT_DIR, project_path)
if not os.path.isdir(resolved):
    log(f"Project path not found: {resolved}", component="run", err=True)
    sys.exit(1)

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
cfg = load_config(SCRIPT_DIR)
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
        project_name=project_name_arg,
        output_name=output_name_arg,
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
if _log_path:
    log(f"Full log: {_log_path}", component="run")
