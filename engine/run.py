#!/usr/bin/env python3
"""Entry: python engine/run.py [options] <project_path>

Options:
  -h, --help           Show this help and exit
  --clean              Delete output/ and model/ before running
  --selected-group <name>
                       Export only the named modulesGroup
  --config <path>      Use this config file instead of engine/config/config.defaults.json
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
                       in-memory config; behaviourDiagram's SequenceDiagramGenerator
                       reads it to pick a diagram selector. One of:
                       single_per_function, single_per_external_component,
                       all_callers, multi_unit_functions, skip_within_unit
                       (default). Unknown values silently fall back to the default.
  --from-phase N       Resume from phase N (1=Parse, 2=Derive, 3=Views, 4=Export)
  --to-phase N         Stop after phase N (1-4). Lets the incremental engine run
                       parse+derive only (--to-phase 2), compute impact, then
                       resume views+export (--from-phase 3).
  --data-dictionary <path>
                       CSV file to merge into model/dataDictionary.json (overrides
                       auto-parsed entries). See engine/config/data_dictionary.csv for format.
                       Project-wide: its entries answer for every layer.
  --data-dictionary-layer <layer> <path>
                       Same format, scoped to one layer. Repeatable, once per layer.
                       Unknown layer -> exit 1, missing file -> exit 2. A layer's
                       entries answer only for that layer; another layer's dictionary
                       is never consulted. Config equivalent: layers.<name>.dataDictionary.
                       The PROJECT-WIDE dictionary is CLI-only (--data-dictionary above);
                       it has no config key by design.
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
  --include-path-layer <layer> <dir>
                       Add an extra -I include directory for the named layer.
                       Repeatable. Merged into clang_include_paths.json before
                       Phase 1, so layer-scoping in Phase 1 and Phase 3 is
                       automatic. There is no project-wide form: an include dir
                       always belongs to a layer. Example:
                         --include-path-layer Layer1 C:/ThirdParty/boost/include
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
    "--data-dictionary", "--data-dictionary-layer",
    "--project-name", "--output-name",
    "--macros", "--macros-layer", "--include-path-layer",
    "--only-files", "--include-emulator",
    "--quiet", "--verbose", "--trace-prompts",
)

clean_all               = False
use_model               = False
no_llm_summarize        = False
from_phase              = 1
to_phase                = None   # stop after this phase (1-4); None = run through phase 4
selected_group_arg      = None   # first, for messages
selected_groups_arg     = []     # ALL: --selected-group is repeatable (--scope group:A,B)
selected_layer_arg      = None   # first, for messages
selected_layers_arg     = []     # ALL: repeatable, same reason as --selected-group
selected_components_arg = []
selected_units_arg      = []   # dev aid: narrow Phase 3 to these unit(s)
component_per_docx      = False
filter_mode_arg         = None
data_dictionary_arg     = None
data_dictionary_layer_args = []   # list of (layer_name, path) tuples
macros_arg              = None
macros_layer_args       = []   # list of (layer_name, path) tuples
project_name_arg        = None
output_name_arg         = None
output_root_arg         = None   # B1: this run's own output dir (versions/<ver…>/output)
model_root_arg          = None   # C11b: this run's own model dir (versions/<ver…>/model)
model_store_arg         = None   # doc 10: "files" (default) | "db" — where phases read the model
dump_model_files_arg    = None   # doc 10 H6: debug-only mirror of the model, for parity checks
version_id_arg          = None   # C11a: persist the model to Postgres at each phase boundary
project_id_arg          = None   # C11a: owning project (the store is project-scoped)
only_files_arg          = None   # narrowed parse (M4.4): file listing the TUs to parse
baseline_version_id_arg = None   # narrowed parse: the version whose func-key map resolves
                                 # calls into files this run did not re-parse
include_emulator_arg    = False  # opt out of the default *emul* file exclusion (3.1)
include_path_layer_args = []   # list of (layer_name, abs_dir) tuples
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
        selected_groups_arg.append(sys.argv[i])
        selected_group_arg = selected_groups_arg[0]
    elif a == "--selected-layer":
        i += 1
        if i >= len(sys.argv):
            log("--selected-layer requires a layer name", component="run", err=True)
            sys.exit(1)
        selected_layers_arg.append(sys.argv[i])
        selected_layer_arg = selected_layers_arg[0]
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
    elif a == "--data-dictionary-layer":
        if i + 2 >= len(sys.argv):
            log("--data-dictionary-layer requires two arguments: <layer> <path>",
                component="run", err=True)
            sys.exit(1)
        data_dictionary_layer_args.append((sys.argv[i + 1], sys.argv[i + 2]))
        i += 2
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
    elif a == "--baseline-version-id":
        i += 1
        if i >= len(sys.argv):
            log("--baseline-version-id requires a version id", component="run", err=True)
            sys.exit(1)
        baseline_version_id_arg = sys.argv[i]
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
    elif a == "--version-id":
        # Which version this run is producing (doc 09, C11a). With it, each phase persists
        # its model to Postgres at its own boundary instead of the whole model landing once
        # at the end of the run. A flag, not an env var, for the same reasons as
        # --output-root: the run's command line then records what it produced.
        i += 1
        if i >= len(sys.argv):
            log("--version-id requires a value", component="run", err=True)
            sys.exit(1)
        version_id_arg = sys.argv[i]
    elif a == "--project-id":
        i += 1
        if i >= len(sys.argv):
            log("--project-id requires a value", component="run", err=True)
            sys.exit(1)
        project_id_arg = sys.argv[i]
    elif a == "--dump-model-files":
        # doc 10 H6 — DEBUG ONLY. Writes the run's model out as JSON to <dir> so
        # tools/verify_model_parity.py still has something to compare the database against once
        # the files are gone. Never used by a job; not a fallback; nothing reads it back.
        i += 1
        if i >= len(sys.argv):
            log("--dump-model-files requires a directory argument", component="run", err=True)
            sys.exit(1)
        dump_model_files_arg = sys.argv[i]
    elif a == "--model-store":
        # doc 10 step 3: which backing the phases use for the model. Default "files", so this
        # flag is the only thing that turns the database path on.
        i += 1
        if i >= len(sys.argv):
            log("--model-store requires 'files' or 'db'", component="run", err=True)
            sys.exit(1)
        model_store_arg = sys.argv[i]
        if model_store_arg not in ("files", "db"):
            log(f"--model-store must be 'files' or 'db' (got {model_store_arg!r})",
                component="run", err=True)
            sys.exit(1)
    elif a == "--model-root":
        # This run's own model dir (doc 09, C11b). Unlike --output-root this must also be
        # forwarded to every PHASE: group_planner bakes absolute output paths into each
        # phase's args, but model_dir is read from paths() inside each phase process.
        i += 1
        if i >= len(sys.argv):
            log("--model-root requires a directory argument", component="run", err=True)
            sys.exit(1)
        model_root_arg = sys.argv[i]
    elif a == "--output-root":
        # Where this run's rendered output goes (doc 09, B1). The orchestrator points it at
        # versions/<ver…>/output so a job never writes a shared dir another job can wipe.
        # A flag rather than an env var: the run's own command line then records where its
        # output went, and a per-version CONFIG would be wrong — that config is stored in
        # versions.resolved_config, and a machine-specific absolute path must never go there
        # (the mistake C3 exists to undo).
        i += 1
        if i >= len(sys.argv):
            log("--output-root requires a directory argument", component="run", err=True)
            sys.exit(1)
        output_root_arg = sys.argv[i]
    elif a == "--include-path-layer":
        if i + 2 >= len(sys.argv):
            log("--include-path-layer requires two arguments: <layer> <dir>", component="run", err=True)
            sys.exit(1)
        include_path_layer_args.append((sys.argv[i + 1], sys.argv[i + 2]))
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

# Applied right after argv parsing and BEFORE anything reads paths(): group_planner builds
# every phase's output path from paths().output_dir, and paths() memoises on first use.
if output_root_arg:
    from core.paths import set_output_dir
    set_output_dir(output_root_arg)
if model_root_arg:
    from core.paths import set_model_dir
    set_model_dir(model_root_arg)
# The run identity, forwarded to every phase by Phase.command() (doc 10, step 3). Recorded
# even in file mode: a phase being told which version it belongs to is useful regardless, and
# it is what makes --from-phase N unambiguous.
from core.run_context import (set_run_context as _set_run_context,
                              install_model_repository as _install_model_repo)
_set_run_context(version=version_id_arg, project=project_id_arg, model_store=model_store_arg)
# run.py itself reads the model for --dump-model-files (H6), and set_run_context only RECORDS
# the choice — installing the repository is separate. Without this the orchestrator kept the
# file default and the dump wrote whatever few files happened to be on disk.
_install_model_repo()

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

# Exactly one positional is expected. A second one is almost always a flag value that lost
# its flag (`--phase 3` leaves a stray `3`) or a second path — both mean the command line does
# not say what the user thinks it says. Checked BEFORE --clean: a command line this ambiguous
# should not delete anything.
if len(raw_args) > 1:
    log(f"Unexpected extra argument(s): {', '.join(raw_args[1:])}", component="run", err=True)
    log(f"Only one <project_path> is accepted (got: {raw_args[0]}).", component="run", err=True)
    log("Run `python engine/run.py --help` to see all options.", component="run", err=True)
    sys.exit(1)

if clean_all:
    for d in ("output", "model"):
        path = os.path.join(SCRIPT_DIR, d)
        if os.path.isdir(path):
            shutil.rmtree(path)
            log(f"Removed {d}/", component="run")
    # Say what it does NOT do (doc 10, H4). --clean removes DIRECTORIES; with the model in the
    # database, deleting model/ leaves the rows untouched, so "clean" would read as a fresh
    # start while the next run still resolves a stored model. Deleting a version's rows is the
    # API's job (it owns the versions row and its cascade), not a CLI flag's, so this warns
    # rather than reaching into the database.
    if model_store_arg == "db":
        log("--clean removed the directories only: the model for this version is in the "
            "database and is NOT deleted. Remove the version through the API to clear it.",
            component="run")

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
    # Ask the REPOSITORY, not the filesystem (doc 10, step 8). "--use-model" means "reuse the
    # model that already exists", and since step 2 that may be rows in the database rather than
    # files — checking os.path.isfile refused a perfectly good stored model and exited 2.
    from core.model_io import model_files_present as _present
    missing = _present(FUNCTIONS, GLOBALS, UNITS, COMPONENTS)
    if missing:
        _where = "the database" if model_store_arg == "db" else "model/"
        log(f"--use-model set but the model is missing from {_where}: {missing[0]}",
            component="run", err=True)
        sys.exit(2)
    log(f"Reusing the existing model from "
        f"{'the database' if model_store_arg == 'db' else 'model/'} (skipping Phase 1/2).",
        component="run")

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

data_dictionary_layer_paths = []
for _dl_layer, _dl_path in data_dictionary_layer_args:
    _dl_abs = _dl_path if os.path.isabs(_dl_path) else os.path.join(SCRIPT_DIR, _dl_path)
    if not os.path.isfile(_dl_abs):
        log(f"--data-dictionary-layer file not found: {_dl_abs}", component="run", err=True)
        sys.exit(2)
    data_dictionary_layer_paths.append((_dl_layer, _dl_abs))


# ---------------------------------------------------------------------------
# Collect layer include paths before any phase runs.
# Written to model/clang_include_paths.json so Phase 1 (parser) and Phase 3
# (flowchart engine) can read them without re-walking the filesystem.
# ---------------------------------------------------------------------------
import json as _json
from core.config import (get_flat_groups as _get_flat_groups,
                         get_group_layer_name as _get_group_layer_name,
                         get_component_layer_name as _get_component_layer_name)
# paths().model_dir, not SCRIPT_DIR: this hardcode ignored BOTH --model-root and
# ANALYZER_DATA_ROOT, so clang_include_paths.json always landed in the repo model dir —
# shared state two concurrent jobs with different layer configs would overwrite.
# (C3 removes this file entirely; until then it must at least follow the run.)
from core.paths import paths as _paths_now
_model_dir = _paths_now().model_dir
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

# Validate and merge --include-path-layer <layer> <dir> entries.
_known_layers = set((cfg.get("layers") or {}).keys())
for _ml_layer, _ in macros_layer_paths:
    if _ml_layer not in _known_layers:
        log(f"--macros-layer: unknown layer {_ml_layer!r}. Valid layers: {', '.join(sorted(_known_layers))}", component="run", err=True)
        sys.exit(1)
for _dl_layer, _ in data_dictionary_layer_paths:
    if _dl_layer not in _known_layers:
        log(f"--data-dictionary-layer: unknown layer {_dl_layer!r}. Valid layers: {', '.join(sorted(_known_layers))}", component="run", err=True)
        sys.exit(1)
for _ip_layer, _ip_dir in include_path_layer_args:
    if _ip_layer not in _known_layers:
        log(f"--include-path-layer: unknown layer {_ip_layer!r}. Valid layers: {', '.join(sorted(_known_layers))}", component="run", err=True)
        sys.exit(1)
    _ip_abs = _ip_dir if os.path.isabs(_ip_dir) else os.path.join(SCRIPT_DIR, _ip_dir)
    if not os.path.isdir(_ip_abs):
        log(f"--include-path-layer: directory not found: {_ip_abs}", component="run", err=True)
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

# --selected-unit: fail before Phase 1 rather than in Phase 3. The unit names come
# from model/units.json, so this is only possible when a model is already on disk —
# which is the case for the runs the flag exists for (--use-model / --from-phase 3).
# A cold run has nothing to check against yet, so validation falls through to
# Phase 3, where the model has just been built.
if selected_units_arg:
    _units_path = _mfp(UNITS)
    if os.path.isfile(_units_path):
        import json as _json
        try:
            with open(_units_path, encoding="utf-8") as _uf:
                _unit_model = {UNITS: _json.load(_uf)}
        except (OSError, ValueError):
            _unit_model = None
        if _unit_model:
            from core.config import get_flat_groups as _gfg
            _groups = _gfg(cfg) or {}
            _grp = _groups.get(selected_group_arg) if selected_group_arg else None
            if not isinstance(_grp, dict) and selected_group_arg:
                _sk = selected_group_arg.casefold()
                _grp = next((v for k, v in _groups.items()
                             if isinstance(k, str) and k.casefold() == _sk), None)
            if selected_components_arg:
                _allowed = sorted(selected_components_arg)
            elif isinstance(_grp, dict):
                _allowed = sorted(k.replace(" ", "-") for k in _grp.keys())
            else:
                _allowed = None      # whole model in scope
            import run_views as _rv
            selected_units_arg = _rv._resolve_units(
                _unit_model, selected_units_arg, _allowed)
    else:
        log("--selected-unit will be validated in Phase 3 (no model on disk yet)",
            component="run")

try:
    plans = plan_runs(
        cfg,
        project_path=resolved,
        selected_group=selected_groups_arg or selected_group_arg,
        selected_layer=selected_layers_arg or selected_layer_arg,
        selected_components=selected_components_arg,
        component_per_docx=component_per_docx,
        use_model=use_model,
        no_llm_summarize=no_llm_summarize,
        from_phase=from_phase,
        filter_mode=filter_mode_arg,
        data_dictionary_path=data_dictionary_path,
        data_dictionary_layer=data_dictionary_layer_paths,
        macros_path=macros_path,
        macros_layer=macros_layer_paths,
        project_name=project_name_arg,
        output_name=output_name_arg,
        only_files=only_files_arg,
        baseline_version_id=baseline_version_id_arg,
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

def _make_phase_persist(project_id, version_id):
    """A post-phase hook that persists the model to Postgres (doc 09, C11a).

    Returns None when this run is not producing a version (a plain CLI run) or when no
    database is configured — both are normal, and neither should change behaviour.

    Only the phases that CHANGE the model are persisted: Phase 1 writes the parsed skeleton,
    Phase 2 the enriched model. Phases 3-4 only read it, so re-persisting after them would be
    identical rows written twice.

    This is the DUAL-WRITE stage: `model/*.json` is still written and still authoritative.
    Nothing reads from the database yet — that is C11b, and it is gated on
    `tools/verify_model_parity.py` agreeing after every phase.
    """
    from core.db import is_database_configured
    if not version_id or not is_database_configured():
        return None
    # Not in DB mode. This hook persists by reading model FILES
    # (write_model -> persist_model_from_dir -> clear_version + persist). In DB mode the phase
    # writes to the database itself and there are no files, so this would clear the version and
    # persist an EMPTY model over what the phase just flushed. The phase's own flush is
    # authoritative there.
    from core.run_context import model_store_kind
    if model_store_kind() == "db":
        return None
    writes_model = {"parser.py", "model_deriver.py"}

    def _persist(phase):
        if phase.script not in writes_model:
            return
        from core.paths import paths as _p
        from incremental.store import make_store
        store = make_store(project_id or "")
        store.write_model(version_id, _p().model_dir)      # one transaction, idempotent
        log(f"persisted model to the database after {phase.name}", component="run")

    return _persist


def _dump_model_files(target_dir: str) -> None:
    """Mirror the run's model to `target_dir` as JSON (doc 10, H6). Debug/verification only.

    `verify_model_parity` compares the DATABASE against the FILES, and it is the check that
    caught a dropped global `description` and a dropped `syntheticFromVarDecl`. Once the files
    stop being written it has nothing to compare, exactly when it is most wanted — so the
    WRITER survives behind this flag while the pipeline itself stops depending on files.

    Not a second pipeline path: it writes the same dicts the repository just returned, after the
    run, and nothing ever reads them back.
    """
    from core.model_io import read_model_file, ALL_MODEL_NAMES
    import json as _json
    os.makedirs(target_dir, exist_ok=True)
    written = 0
    for _name in ALL_MODEL_NAMES:
        try:
            _data = read_model_file(_name, required=False, default=None)
        except Exception:
            continue
        if _data is None:
            continue
        with open(os.path.join(target_dir, f"{_name}.json"), "w", encoding="utf-8") as _fh:
            _json.dump(_data, _fh, indent=2, ensure_ascii=False)
        written += 1
    log(f"--dump-model-files: wrote {written} model file(s) to {target_dir} "
        f"(verification only)", component="run")


_phase_persist = _make_phase_persist(project_id_arg, version_id_arg)

runner = PhaseRunner(project_root=SCRIPT_DIR)
total_time = 0.0
for plan in plans:
    log(plan.label, component="run")
    total_time += runner.run(plan.phases, from_phase=plan.runner_from_phase,
                             on_phase_done=_phase_persist)

print(flush=True)
# doc 10 H6 — debug-only mirror, AFTER the run so it reflects the finished model.
if dump_model_files_arg:
    _dump_model_files(dump_model_files_arg)

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
