"""FastAPI entry point for the analyzer backend.

Run with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

The UI (Vite dev server) is at http://localhost:5173 — that's the only
origin currently whitelisted by CORS. Widen the list when staging hosts
come online.

The structure mirrors the team's `main.py` (12 routes total). Routes are
filled in batch-by-batch against real CPP project data:

  Batch 1 (this commit): APIs 1-3   — repository, components, component-by-id
  Batch 2: APIs 4-6   — modules, function detail, function patch
  Batch 3: APIs 7-9   — flowchart, prepare job, prepare logs
  Batch 4: APIs 10-12 — job status, cancel, export job

Stubbed routes return HTTP 501 with a clear message so the UI surfaces
"not yet wired" rather than a confusing payload.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# Locate the analyzer root regardless of how deeply backend/ is nested.
# Layouts we want to support:
#   <root>/backend/main.py            (flat — historical)
#   <root>/fast-app/backend/main.py   (nested under fast-app/)
#   <root>/anything/.../backend/main.py
# Walk upward looking for a directory that has BOTH src/core/ and config/ —
# those two markers together uniquely identify the analyzer root.
def _detect_analyzer_root(start: str) -> str:
    cur = os.path.abspath(start)
    for _ in range(10):  # safety bound — never recurse to filesystem root
        if (
            os.path.isdir(os.path.join(cur, "src", "core"))
            and os.path.isdir(os.path.join(cur, "config"))
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # Fallback: parent of backend/ — preserves the old behaviour for the
    # flat layout when the markers happen to be missing (e.g. first run
    # before any pipeline has populated config/).
    return os.path.dirname(os.path.abspath(start))


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = _detect_analyzer_root(_BACKEND_DIR)
_SRC_DIR = os.path.join(_REPO_ROOT, "src")

# sys.path setup. Two reasons to add both dirs explicitly:
#   - _SRC_DIR makes `from core.config import load_config` resolve regardless
#     of cwd, so importing src/core/config.py works from any launch dir.
#   - _BACKEND_DIR makes `from models import ...` resolve regardless of
#     whether uvicorn is launched as `uvicorn backend.main:app` (from one
#     dir above) or `uvicorn main:app` (from inside backend/). Otherwise
#     only one of those two invocations puts backend/ on sys.path.
for _p in (_SRC_DIR, _BACKEND_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.config import load_config  # noqa: E402

from models import (  # noqa: E402
    Component,
    ComponentSummary,
    ExportJobRequest,
    ExportProgress,
    Flowchart,
    FunctionCaller,
    FunctionDetailWithHidden,
    JobStartResult,
    Module,
    ModuleSummary,
    PatchFunctionBody,
    PatchFunctionResult,
    PrepLog,
    PrepareJobRequest,
    Repository,
    TreeNode,
    UpdateConfigRequest,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Single hardcoded component for now. When config grows a "components" key
# this becomes a lookup keyed off that block.
_COMPONENT_ID = "FTL"
_COMPONENT_NAME = "FTL"
_COMPONENT_CODE = "FTL"
_COMPONENT_DESC = ""

# Files counted as "source files" for the per-module count and tree leaves.
_SOURCE_EXTS = (".cpp", ".c", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx")


# ---------------------------------------------------------------------------
# In-memory stores (populated by later batches)
# ---------------------------------------------------------------------------

# Persisted patches from PATCH /functions/{fn_id} (batch 2).
_db: Dict[str, Dict[str, object]] = {
    "descriptions": {},
    "hidden_functions": {},
}

# Background-job state keyed by job_id (batches 3 & 4).
_jobs: Dict[str, Dict] = {}


# ---------------------------------------------------------------------------
# Real-data helpers (used by APIs 1-3)
# ---------------------------------------------------------------------------


def _project_base_path() -> Optional[str]:
    """Return basePath last recorded by the parser, or None if unknown.

    File/tree views are anchored to this directory. When no run has happened
    yet (model/metadata.json missing), the tree endpoints return empty
    children instead of guessing a path.
    """
    p = os.path.join(_REPO_ROOT, "model", "metadata.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    base = data.get("basePath") or ""
    return base or None


def _load_modules_groups() -> Dict[str, Dict[str, object]]:
    """Return config.json :: modulesGroups, or {} when missing/invalid."""
    cfg = load_config(_REPO_ROOT)
    groups = cfg.get("modulesGroups") or {}
    return groups if isinstance(groups, dict) else {}


def _load_functions() -> Dict[str, dict]:
    """Load model/functions.json — {} when missing or malformed."""
    p = os.path.join(_REPO_ROOT, "model", "functions.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_dirs(spec) -> List[str]:
    """A logical-group's dirs may be a string or a list of strings.

    Empty/non-string entries are dropped so a malformed config never crashes
    the API — it just yields a thinner tree.
    """
    if not spec:
        return []
    if isinstance(spec, str):
        return [spec.replace("\\", "/").strip("/")] if spec.strip() else []
    if isinstance(spec, list):
        out: List[str] = []
        for s in spec:
            if isinstance(s, str) and s.strip():
                out.append(s.replace("\\", "/").strip("/"))
        return out
    return []


def _collect_module_dirs(inner: dict) -> List[str]:
    """Flatten every logical group's dirs into one ordered, deduped list."""
    if not isinstance(inner, dict):
        return []
    seen: set = set()
    out: List[str] = []
    for _group, spec in inner.items():
        for d in _normalize_dirs(spec):
            if d not in seen:
                seen.add(d)
                out.append(d)
    return out


def _count_source_files(base_path: str, rel_dirs: List[str]) -> int:
    """Recursively count C/C++ source files under any of rel_dirs."""
    if not base_path or not os.path.isdir(base_path):
        return 0
    total = 0
    for rel in rel_dirs:
        full = os.path.join(base_path, rel)
        if not os.path.isdir(full):
            continue
        for _root, _subdirs, files in os.walk(full):
            for f in files:
                if f.lower().endswith(_SOURCE_EXTS):
                    total += 1
    return total


def _functions_by_file(functions_data: Dict[str, dict]) -> Dict[str, List[dict]]:
    """Group {fn_id: info} by normalized location.file."""
    by_file: Dict[str, List[dict]] = {}
    for fid, info in functions_data.items():
        if not isinstance(info, dict):
            continue
        loc = info.get("location") or {}
        rel = (loc.get("file") or "").replace("\\", "/").strip("/")
        if not rel:
            continue
        by_file.setdefault(rel, []).append({"id": fid, "info": info})
    return by_file


def _fn_node(fid: str, info: dict) -> TreeNode:
    qname = info.get("qualifiedName") or fid
    return TreeNode(id=fid, type="fn", name=str(qname))


def _file_node(file_rel: str, by_file: Dict[str, List[dict]]) -> TreeNode:
    fns = by_file.get(file_rel, [])
    fns_sorted = sorted(
        fns, key=lambda x: int(((x.get("info") or {}).get("location") or {}).get("line") or 0)
    )
    fn_children = [_fn_node(fn["id"], fn["info"]) for fn in fns_sorted]
    return TreeNode(
        id=file_rel,
        type="submodule",
        name=os.path.basename(file_rel),
        children=fn_children or None,
    )


def _dir_node(base_path: str, rel_dir: str, by_file: Dict[str, List[dict]]) -> Optional[TreeNode]:
    """Build a submodule node for rel_dir, recursing into subdirectories and
    listing source files. Returns None if the dir doesn't exist on disk."""
    full = os.path.join(base_path, rel_dir)
    if not os.path.isdir(full):
        return None

    try:
        entries = sorted(os.listdir(full))
    except OSError:
        entries = []

    sub_dirs = [e for e in entries if os.path.isdir(os.path.join(full, e))]
    sub_files = [
        e for e in entries
        if not os.path.isdir(os.path.join(full, e)) and e.lower().endswith(_SOURCE_EXTS)
    ]

    children: List[TreeNode] = []
    for sub_dir in sub_dirs:
        child_rel = (rel_dir + "/" + sub_dir).strip("/")
        node = _dir_node(base_path, child_rel, by_file)
        if node is not None:
            children.append(node)
    for sub_file in sub_files:
        file_rel = (rel_dir + "/" + sub_file).strip("/")
        children.append(_file_node(file_rel, by_file))

    return TreeNode(
        id=rel_dir,
        type="submodule",
        name=os.path.basename(rel_dir) or rel_dir,
        children=children or None,
    )


def _logical_group_node(
    group_name: str,
    spec,
    base_path: str,
    by_file: Dict[str, List[dict]],
) -> TreeNode:
    """One inner-key (logical group) of modulesGroups → submodule node."""
    children: List[TreeNode] = []
    for rel in _normalize_dirs(spec):
        node = _dir_node(base_path, rel, by_file)
        if node is not None:
            children.append(node)
    return TreeNode(
        id=group_name,
        type="submodule",
        name=group_name,
        children=children or None,
    )


def _description_of(record: dict) -> str:
    """Return the description text for a functions/knowledge_base record.

    Reads `description` first, falls back to legacy `comment`. The analyzer
    pipeline is mid-migration to a single canonical `description` field
    (see src/model_deriver.py) and on-disk JSON still carries either name
    depending on when it was last written; this helper hides the difference
    from API responses.
    """
    if not isinstance(record, dict):
        return ""
    return str(record.get("description") or record.get("comment") or "")


def _safe_write_json(path: str, data) -> None:
    """Atomically rewrite `path` with `data`.

    Writes to a sibling temp file then os.replace()s onto the target so an
    interrupted save can't leave a half-written file in place. Caller is
    responsible for catching exceptions.
    """
    dir_ = os.path.dirname(path) or "."
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=dir_, suffix=".tmp"
    )
    try:
        json.dump(data, tmp, indent=2, ensure_ascii=False)
        tmp.flush()
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def _safe_filename(name: str) -> str:
    """Replicates src/utils.py::safe_filename for the small set of chars that
    can't appear in a filename. Matches the per-group filename produced by
    src/views/flowcharts.py so reads/writes hit the same file the pipeline
    wrote."""
    return re.sub(r'[<>:"/\\|?*]', "_", name or "")


def _module_file_for_fn(fn_id: str) -> Optional[str]:
    """Return the path to the per-module functions JSON that owns this fn_id,
    or None if the mapping can't be resolved.

    fn_id format is `<inner_group>|<unit>|<qname>|<params>`. The inner_group
    segment (e.g. `tests_a`) appears under one OUTER group in modulesGroups
    (e.g. `tests` -> {tests_a: [...], tests_b: [...]}). The pipeline writes
    the per-group file as functions_<outer>.json (see flowcharts.py line
    288), so we look up the outer key the same way.

    Returning a path doesn't mean the file exists on disk — the caller
    should check.
    """
    if not fn_id or "|" not in fn_id:
        return None
    inner_prefix = fn_id.split("|", 1)[0]
    groups = _load_modules_groups()
    for outer_key, inner in groups.items():
        if isinstance(inner, dict) and inner_prefix in inner:
            return os.path.join(
                _REPO_ROOT, "model", f"functions_{_safe_filename(outer_key)}.json"
            )
    # Fallback: maybe the unit prefix IS the outer key (single-group module
    # like `core` where inner_prefix == outer_key already matched above —
    # this branch is a defensive no-op).
    return None


def _read_description_override(fn_id: str) -> Optional[str]:
    """Return the description stored in the per-module file for fn_id, or
    None when the file doesn't exist / doesn't carry this entry / can't be
    parsed.

    A None result tells callers "no per-module override exists — fall back
    to the master functions.json value." An empty-string result is a real
    answer (the file exists and says the description is blank) and is NOT
    treated as a miss.
    """
    path = _module_file_for_fn(fn_id)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get(fn_id)
    if not isinstance(entry, dict):
        return None
    return _description_of(entry)


def _persist_description(fn_id: str, description: str, functions_data: dict) -> None:
    """Write `description` to the per-module file (functions_<group>.json)
    and knowledge_base.json. Never touches the master functions.json — per
    team contract, descriptions are canonical in the per-module files.

    Canonicalises onto `description` and removes any legacy `comment` so
    consumers reading the older name don't see stale text. Failures on one
    file don't roll back the other — best-effort. If the per-module file
    doesn't exist yet (the pipeline hasn't generated one for this group),
    the write is skipped silently — the UI's PATCH still returns 200, and
    the next pipeline run will produce the file fresh.
    """
    # Per-module functions_<group>.json — the canonical store for descriptions
    module_path = _module_file_for_fn(fn_id)
    if module_path and os.path.isfile(module_path):
        try:
            with open(module_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entry = data.get(fn_id) if isinstance(data, dict) else None
            if isinstance(entry, dict):
                entry["description"] = description
                entry.pop("comment", None)
                _safe_write_json(module_path, data)
        except (json.JSONDecodeError, OSError):
            pass

    # knowledge_base.json — keyed by qualifiedName
    qname = (functions_data.get(fn_id) or {}).get("qualifiedName") or ""
    if not qname:
        return
    kb_path = os.path.join(_REPO_ROOT, "model", "knowledge_base.json")
    if not os.path.isfile(kb_path):
        return
    try:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        if not isinstance(kb, dict):
            return
        kb_funcs = kb.get("functions") or {}
        entry = kb_funcs.get(qname)
        if isinstance(entry, dict):
            entry["description"] = description
            entry.pop("comment", None)
            _safe_write_json(kb_path, kb)
    except (json.JSONDecodeError, OSError):
        pass


def _find_flowchart_entry(fn_id: str) -> Optional[dict]:
    """Scan output/flowcharts/*.json for the entry whose functionKey matches
    `fn_id` and return the whole {functionKey, name, flowchart} dict, or
    None when no match exists (flowcharts not yet rendered, function
    filtered out). Skips `_summary.json` and any file starting with `_`."""
    flowcharts_dir = os.path.join(_REPO_ROOT, "output", "flowcharts")
    if not os.path.isdir(flowcharts_dir):
        return None
    try:
        names = os.listdir(flowcharts_dir)
    except OSError:
        return None
    for name in names:
        if not name.endswith(".json") or name.startswith("_"):
            continue
        path = os.path.join(flowcharts_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(arr, list):
            continue
        for entry in arr:
            if isinstance(entry, dict) and entry.get("functionKey") == fn_id:
                return entry
    return None


def _find_flowchart_for_fn(fn_id: str) -> str:
    """Convenience wrapper — return just the Mermaid script string, or ''."""
    entry = _find_flowchart_entry(fn_id)
    return str(entry.get("flowchart") or "") if entry else ""


# ---------------------------------------------------------------------------
# Prepare-job helpers (used by APIs 8 / 9 / 10 / 11)
# ---------------------------------------------------------------------------

# Log-line format from src/core/logging_setup.py:
#   "[%(asctime)s] %(levelname)s %(name)s: %(message)s"  with datefmt %H:%M:%S
_LOG_LINE_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\] (\w+) ([\w.]+): (.*)$")

# Default tail size for the prepare-logs endpoint. Most recent N lines are
# returned; client polls every couple of seconds.
_LOG_TAIL_LIMIT = 200


def _expected_log_file_path() -> str:
    """Path the analyzer's configure_logging() will write into for today's
    run. UTC date matches logging_setup.py:101.

    A jitter window exists between API 8 spawning run.py and run.py calling
    configure_logging(), so the file may not exist yet when we return; the
    log reader handles that case by treating it as "no lines so far"."""
    today_utc = datetime.now(timezone.utc).strftime("%Y%m%d")
    return os.path.join(_REPO_ROOT, "logs", f"run_{today_utc}.log")


def _new_job_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _expected_docx_path(selected_group: Optional[str]) -> str:
    """Return the absolute path the analyzer would write its docx to for a
    given --selected-group, mirroring docx_exporter.py:933-938:

        group_name = selected_group or "all"
        raw  = config.export.docxPath  (default: output/software_detailed_design.docx)
        path = <repo>/{raw with {group} -> group_name}

    Computed at job-creation time and stashed on the job so the download
    endpoint doesn't have to re-derive it later.
    """
    cfg = load_config(_REPO_ROOT)
    export_cfg = cfg.get("export") or {}
    raw = (export_cfg.get("docxPath") or "output/software_detailed_design.docx").strip()
    group_name = selected_group or "all"
    rel = raw.replace("{group}", group_name)
    return os.path.normpath(os.path.join(_REPO_ROOT, rel))


def _resolve_group_name(requested: Optional[str]) -> Optional[str]:
    """Validate moduleId against the OUTER keys of config.modulesGroups
    (case-insensitive). Returns the canonical key when matched, None when
    `requested` is empty/None. Raises HTTPException(400) when non-empty
    but unknown — saves an unattended run.py from silently processing the
    full project when the UI sent a typo.

    Mirrors src/utils.py's resolver behaviour so the API answers exactly
    the same set of names that the CLI's --selected-group accepts.
    """
    if not requested or not requested.strip():
        return None
    req = requested.strip()
    groups = _load_modules_groups()
    if req in groups:
        return req
    fold = req.casefold()
    for k in groups.keys():
        if isinstance(k, str) and k.casefold() == fold:
            return k
    valid = sorted(k for k in groups.keys() if isinstance(k, str))
    raise HTTPException(
        status_code=400,
        detail=f"moduleId {requested!r} not in modulesGroups; valid: {valid}",
    )


def _level_normalize(raw: str) -> str:
    """Map Python logging level names to the UI's four-token vocabulary."""
    low = (raw or "").lower()
    if low in ("error", "critical", "fatal"):
        return "error"
    if low in ("warning", "warn"):
        return "warn"
    if low == "debug":
        return "debug"
    return "info"


def _read_log_tail(
    log_file: str,
    start_offset: int,
    limit: int,
    end_offset: Optional[int] = None,
) -> List[PrepLog]:
    """Return up to `limit` most recent PrepLog entries from log_file,
    sliced to [start_offset, end_offset).

    The watcher records end_offset when a subprocess exits so a completed
    job's response is bounded to lines actually emitted by THAT job, even
    if other jobs have since appended more lines to the shared rolling
    log file. For a still-running job (end_offset is None) we read up to
    the current EOF.

    Lines that don't match the standard `[HH:MM:SS] LEVEL name: msg` format
    are attached to the previously-seen timestamp/level — these are usually
    multi-line traceback continuations. Blank lines are dropped."""
    if not log_file or not os.path.isfile(log_file):
        return []
    try:
        with open(log_file, "rb") as f:
            f.seek(start_offset)
            if end_offset is not None and end_offset > start_offset:
                raw = f.read(end_offset - start_offset)
            else:
                raw = f.read()
        text = raw.decode("utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if not lines:
        return []

    entries: List[PrepLog] = []
    last_t = ""
    last_level = "info"
    for raw in lines:
        m = _LOG_LINE_RE.match(raw)
        if m:
            ts, lvl, _name, msg = m.groups()
            last_t = ts
            last_level = _level_normalize(lvl)
            entries.append(PrepLog(id=str(len(entries)), t=ts, level=last_level, msg=msg))
        elif raw.strip():
            entries.append(PrepLog(id=str(len(entries)), t=last_t, level=last_level, msg=raw))
    return entries[-limit:]


def _format_command_line(project_path: str, extra_args: Optional[List[str]]) -> str:
    """Render the literal argv that _spawn_run_py builds, as a single
    human-readable string. Surfaced on the status response so the UI can
    verify exactly which run.py invocation is being tracked — useful for
    confirming `--selected-group <name>` was passed through.
    """
    parts: List[str] = [os.path.basename(sys.executable) or "python", "run.py", project_path]
    if extra_args:
        parts.extend(extra_args)
    return " ".join(parts)


# Matches the orchestration phase-start line written by
# src/core/orchestration.py:  `[<idx>/<total>] === <phase name> ===`
_PHASE_START_RE = re.compile(r"\[(\d+)/(\d+)\] === (.+?) ===")

# `Phase 2: Derive model` -> `Derive model` (strip the human-prefix the
# analyzer uses so the UI shows just the phase name).
_PHASE_LABEL_PREFIX_RE = re.compile(r"^Phase\s+\d+\s*:\s*", re.IGNORECASE)


# Canonical 4-phase pipeline that the UI thinks in terms of, matching the
# constants in src/core/group_planner.py (PHASE_PARSE/DERIVE/VIEWS/EXPORT).
# The analyzer may split this into multiple `RunPlan`s under the hood —
# e.g. a multi-group run emits Phase 3 and 4 once per group — but every
# phase still has one of these canonical names and that's what we surface
# to the UI so phaseNumber stays a clean 1..4.
_CANONICAL_PHASES = [
    "Parse C++ source",
    "Derive model",
    "Generate views",
    "Export to DOCX",
]
_PHASE_NAME_TO_NUMBER = {name.casefold(): i + 1 for i, name in enumerate(_CANONICAL_PHASES)}
_CANONICAL_TOTAL = 4


def _expected_phase_markers(selected_group: Optional[str], from_phase: int) -> int:
    """Predict how many `[N/M] === Phase ... ===` markers the spawned
    run.py will log, based on the plan_runs branching in
    src/core/group_planner.py:87 (kept in sync deliberately — when that
    file changes this helper must follow).

    Used to compute monotonically-increasing overall progress for
    multi-group runs where phases 3 and 4 repeat once per group. Without
    this, my code would see the latest [N/2] marker and divide by 2 —
    progress would oscillate as each new group restarted at [1/2].
    """
    cfg = load_config(_REPO_ROOT)
    groups_cfg = cfg.get("modulesGroups") or {}
    num_groups = len(groups_cfg) if isinstance(groups_cfg, dict) else 0

    # Branch 1 of plan_runs: no modulesGroups -> single flat plan.
    if num_groups == 0:
        # The single plan has 4 phases; --from-phase skips the first N-1.
        # Floor at 1 so we never divide by zero.
        return max(1, 5 - max(1, from_phase))

    # Branch 2: modulesGroups present.
    effective_groups = 1 if selected_group else num_groups
    # Build-model plan covers canonical phases 1+2. Skipped entirely when
    # from_phase > 2 (use existing model on disk).
    if from_phase <= 1:
        build_markers = 2
    elif from_phase == 2:
        build_markers = 1
    else:
        build_markers = 0
    # Per-group plan covers canonical phases 3+4. local_from in the planner
    # is max(1, from_phase - 2): from_phase 3 -> 1, 4 -> 2.
    if from_phase >= 4:
        per_group = 1  # just Export
    else:
        per_group = 2  # Views + Export
    return build_markers + effective_groups * per_group


def _compute_progress_and_phase(
    output_file: str,
    total_expected_markers: int = 0,
) -> Tuple[int, str, int, int, int]:
    """Compute (per_phase_pct, phase_label, phase_number, total_phase, overall_pct)
    from the per-job stdout/stderr capture, treating the analyzer's
    underlying multi-plan layout as a single canonical 4-phase pipeline
    (Parse / Derive / Views / Export).

      per_phase_pct  Within-phase percent. The analyzer only logs phase
                     BOUNDARIES, not within-phase progress, so we report
                     a constant 50 while a phase is running (rough
                     midpoint). _finalize_job overrides this to 100 on
                     terminal exit.
      phase_label    Latest phase name with the `Phase N: ` prefix
                     stripped — current truth, so the UI can show
                     "Currently: Generate views" even when the same
                     phase has been seen before for another group.
      phase_number   Canonical 1-4 mapping of the LATEST phase name. May
                     bounce between 3 and 4 across groups for multi-
                     group runs; pair with overall_pct (which is always
                     monotonic) for a stable progress bar.
      total_phase    Always 4 (the canonical pipeline length). UI never
                     sees the inner [N/M] denominators that change per
                     plan.
      overall_pct    Marker-count progress: `(markers_seen - 0.5) /
                     total_expected_markers * 100`, capped at 99 — so
                     it climbs monotonically through every phase of
                     every plan. _finalize_job sets the true 100 on
                     exit. Falls back to canonical_max/4 when no
                     total_expected was supplied (transitional callers).

    All-zero return means "still warming up" (file unreadable or no
    markers seen yet).
    """
    if not output_file or not os.path.isfile(output_file):
        return (0, "", 0, _CANONICAL_TOTAL, 0)
    try:
        with open(output_file, "rb") as f:
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return (0, "", 0, _CANONICAL_TOTAL, 0)

    matches = _PHASE_START_RE.findall(text)
    if not matches:
        return (0, "", 0, _CANONICAL_TOTAL, 0)

    # Walk every marker so we can:
    #   - count them (for overall progress against the expected total)
    #   - find the latest canonical phase (for phase label / phaseNumber)
    #   - find the max canonical seen (fallback overall calc)
    max_canonical = 0
    latest_canonical = 0
    latest_label = ""
    for _n_s, _total_s, name in matches:
        clean = _PHASE_LABEL_PREFIX_RE.sub("", name.strip())
        canonical = _PHASE_NAME_TO_NUMBER.get(clean.casefold(), 0)
        if canonical > max_canonical:
            max_canonical = canonical
        latest_canonical = canonical or latest_canonical
        latest_label = clean

    if latest_canonical == 0:
        # Phase names didn't map to the canonical 4-phase pipeline (e.g.
        # someone running a custom plan). Fall back to a literal [N/M]
        # reading so we still surface something sensible.
        _n_s, _total_s, _name = matches[-1]
        try:
            n = int(_n_s)
            total = int(_total_s)
        except ValueError:
            return (0, latest_label, 0, _CANONICAL_TOTAL, 0)
        if total <= 0:
            return (50, latest_label, n, _CANONICAL_TOTAL, 0)
        overall = (n - 0.5) / total * 100
        return (50, latest_label, n, _CANONICAL_TOTAL,
                max(0, min(99, int(overall))))

    # Overall progress: marker count vs expected total. This is what stops
    # progress from oscillating across plans — each new marker monotonically
    # increases the count, regardless of which [N/M] denominator it belongs
    # to. Falls back to canonical_max/4 when caller didn't supply an
    # expected total.
    markers_seen = len(matches)
    if total_expected_markers and total_expected_markers > 0:
        overall = (markers_seen - 0.5) / total_expected_markers * 100
    else:
        overall = (max_canonical - 0.5) / _CANONICAL_TOTAL * 100
    overall_capped = max(0, min(99, int(overall)))

    return (50, latest_label, latest_canonical, _CANONICAL_TOTAL, overall_capped)


def _spawn_run_py(
    project_path: str,
    extra_args: Optional[List[str]] = None,
    output_file_path: Optional[str] = None,
) -> subprocess.Popen:
    """Spawn `python run.py <project_path> [extra_args...]` rooted at the
    analyzer repo so run.py resolves config/, src/, model/ correctly.

    When output_file_path is provided, stdout AND stderr are merged into
    that file (line-buffered) so import-time crashes — which happen before
    parser.py / run.py configure their loggers — leave a visible trail.
    Without this, DEVNULL'd stderr makes every Phase-1 failure look the
    same regardless of cause. The file handle is attached to the Popen
    object as `_spawn_output_fh` so the watcher can close it on exit.

    Windows needs shell=True (project preference — see CLAUDE.md note
    about subprocess.run requirements). The process group flags let API 11
    kill the whole tree cleanly when cancel arrives.
    """
    cmd: List[str] = [sys.executable, "run.py", project_path]
    if extra_args:
        cmd.extend(extra_args)
    is_windows = sys.platform == "win32"

    out_fh: Optional[object] = None
    if output_file_path:
        os.makedirs(os.path.dirname(output_file_path) or ".", exist_ok=True)
        out_fh = open(output_file_path, "w", encoding="utf-8", buffering=1)
        stdout_target = out_fh
        stderr_target = subprocess.STDOUT  # merge into the same file
    else:
        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL

    popen_kwargs: Dict = dict(
        cwd=_REPO_ROOT,
        stdout=stdout_target,
        stderr=stderr_target,
    )
    if is_windows:
        popen_kwargs["shell"] = True
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True  # own process group

    proc = subprocess.Popen(cmd, **popen_kwargs)
    # Attach so _watch_subprocess_job can close it when the process exits.
    proc._spawn_output_fh = out_fh  # type: ignore[attr-defined]
    return proc


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Hard-kill the subprocess and every descendant.

    Windows: `taskkill /F /T /PID <pid>` walks the process tree (works
    because _spawn_run_py sets CREATE_NEW_PROCESS_GROUP). Falls back to
    proc.terminate() if taskkill is missing.

    POSIX: `os.killpg(getpgid(pid), SIGKILL)` — _spawn_run_py sets
    start_new_session=True so the spawned process is the group leader.
    Falls back to proc.kill() if anything in that chain fails.
    """
    if proc.poll() is not None:
        return  # already exited
    pid = proc.pid
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            proc.terminate()
        except OSError:
            pass
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
        return
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass


def _finalize_job(job_id: str, rc: Optional[int], error: Optional[str] = None) -> None:
    """Centralised completion bookkeeping — called by both the watcher
    (process exited on its own) and the cancel endpoint (process killed).

    Sets complete/return_code/error in one place; chooses the right
    progress representation for the job type; snapshots the rolling-log
    end_offset (for fallback tail reads); and closes the per-job
    stdout/stderr capture file so the final flush lands on disk.

    Cancelled-with-nonzero-rc is reported as "cancelled by user"; a
    cancel that races a clean exit (rc=0) is recorded with no error so
    the UI doesn't show a confusing failure on a successful run.
    """
    job = _jobs.get(job_id)
    if not job or job.get("complete"):
        return
    job["complete"] = True
    job["return_code"] = rc

    if error:
        job["error"] = error
    elif rc not in (0, None):
        if job.get("cancelled"):
            job["error"] = "cancelled by user"
        else:
            job["error"] = f"run.py exited with code {rc}"

    if job.get("type") == "export":
        if job.get("cancelled") and rc not in (0, None):
            stage = "cancelled"
        elif rc == 0:
            stage = "done"
        else:
            stage = "failed"
        job["progress"] = ExportProgress(pct=100, stage=stage)
    else:
        # Prepare jobs: integer percentage. 100 on any terminal state so
        # the UI can flip its spinner off.
        job["progress"] = 100

    log_file = job.get("log_file") or ""
    if log_file and os.path.isfile(log_file):
        try:
            job["log_end_offset"] = os.path.getsize(log_file)
        except OSError:
            pass

    proc = job.get("process")
    if proc is not None:
        fh = getattr(proc, "_spawn_output_fh", None)
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass


async def _watch_subprocess_job(job_id: str) -> None:
    """Background task: poll until the spawned subprocess exits, then hand
    off to _finalize_job. When a cancel request flips the cancelled flag
    mid-flight, the kill happens in the cancel handler; this watcher just
    needs to detect the resulting exit and finalize."""
    job = _jobs.get(job_id)
    if not job:
        return
    proc: Optional[subprocess.Popen] = job.get("process")
    if proc is None:
        return
    while True:
        rc = proc.poll()
        if rc is not None:
            _finalize_job(job_id, rc=rc)
            return
        await asyncio.sleep(0.5)


def _build_module_tree(
    module_key: str,
    inner: dict,
    base_path: Optional[str],
    by_file: Dict[str, List[dict]],
) -> TreeNode:
    """Build the tree for one module (one outer key of modulesGroups).

    Layout rules:
      - The tree root is always the module itself (type=submodule).
      - When the module has exactly one logical group whose name matches the
        module name, the logical-group level is collapsed — avoids the
        "core -> core -> app, math" double-nesting for the common case.
      - When the module has multiple logical groups, each appears as its own
        child — useful for the tests/tests_a/tests_b partition pattern.
    """
    inner_dict = inner if isinstance(inner, dict) else {}
    base = base_path or ""

    if not base or not os.path.isdir(base):
        return TreeNode(id=module_key, type="submodule", name=module_key)

    logical_keys = list(inner_dict.keys())

    if len(logical_keys) == 1 and logical_keys[0] == module_key:
        only_group = logical_keys[0]
        children: List[TreeNode] = []
        for rel in _normalize_dirs(inner_dict[only_group]):
            node = _dir_node(base, rel, by_file)
            if node is not None:
                children.append(node)
        return TreeNode(
            id=module_key,
            type="submodule",
            name=module_key,
            children=children or None,
        )

    children = [
        _logical_group_node(group_name, spec, base, by_file)
        for group_name, spec in inner_dict.items()
    ]
    return TreeNode(
        id=module_key,
        type="submodule",
        name=module_key,
        children=children or None,
    )


# ---------------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Analyzer Backend",
    description="Backend API for the analyzer document generation UI",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes — Batch 1 (implemented against real data)
# ---------------------------------------------------------------------------


@app.get("/api/v1/repository", response_model=List[Repository])
async def list_repositories() -> List[Repository]:
    """List every repository registered in backend/repository_config.json.

    Returns [] when no repos are configured (use POST /api/v1/repository
    to add the first). The legacy `{"path": "..."}` single-repo file
    format is auto-migrated to a one-entry list named "default" on read,
    so existing setups keep working without a manual edit.
    """
    return [Repository(**r) for r in _load_repositories()]


@app.get("/api/v1/repository/{name}", response_model=Repository)
async def get_repository(name: str) -> Repository:
    """Fetch one repository by name. 404 when no entry has that name."""
    for r in _load_repositories():
        if r["name"] == name:
            return Repository(**r)
    raise HTTPException(status_code=404, detail=f"repository {name!r} not found")


@app.post("/api/v1/repository", response_model=Repository, status_code=201)
async def add_repository(body: Repository) -> Repository:
    """Add a new repository entry.

    Names are case-sensitive and must be unique; 409 if a repo with that
    name already exists. Both fields are required and stripped of
    surrounding whitespace before storage.

    backend/repository_config.json (and its parent directory) is
    auto-created on first POST so the UI doesn't have to bootstrap it.
    """
    name = (body.name or "").strip()
    path = (body.path or "").strip()
    if not name or not path:
        raise HTTPException(status_code=400, detail="name and path are required")
    repos = _load_repositories()
    if any(r["name"] == name for r in repos):
        raise HTTPException(
            status_code=409, detail=f"repository {name!r} already exists"
        )
    repos.append({"name": name, "path": path})
    try:
        _save_repositories(repos)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"failed to save repository_config.json: {exc}",
        )
    return Repository(name=name, path=path)


@app.put("/api/v1/repository/{name}", response_model=Repository)
async def update_repository(name: str, body: Repository) -> Repository:
    """Update an existing repository's path.

    The URL `{name}` is the identifier; the body's `name` must match it
    (renames aren't supported here — delete + add the new name instead).
    404 when no entry has that name.
    """
    if (body.name or "").strip() != name:
        raise HTTPException(
            status_code=400,
            detail=(
                f"body name {body.name!r} does not match URL name {name!r}; "
                f"renames aren't supported via PUT"
            ),
        )
    new_path = (body.path or "").strip()
    if not new_path:
        raise HTTPException(status_code=400, detail="path is required")
    repos = _load_repositories()
    for r in repos:
        if r["name"] == name:
            r["path"] = new_path
            try:
                _save_repositories(repos)
            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"failed to save repository_config.json: {exc}",
                )
            return Repository(name=name, path=new_path)
    raise HTTPException(status_code=404, detail=f"repository {name!r} not found")


@app.delete("/api/v1/repository/{name}", status_code=204)
async def delete_repository(name: str):
    """Remove a repository by name. 404 when no entry has that name.

    The on-disk file becomes `[]` (not deleted) when the last repository
    is removed — the UI can keep POSTing without re-bootstrapping the
    file.
    """
    repos = _load_repositories()
    remaining = [r for r in repos if r["name"] != name]
    if len(remaining) == len(repos):
        raise HTTPException(
            status_code=404, detail=f"repository {name!r} not found"
        )
    try:
        _save_repositories(remaining)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"failed to save repository_config.json: {exc}",
        )
    return None


@app.get("/api/v1/components", response_model=List[ComponentSummary])
async def list_components() -> List[ComponentSummary]:
    """API 2 — single hardcoded "FTL" wrapping every entry in
    config.json::modulesGroups. moduleCount tracks that dict live so the UI
    badge updates as soon as a new group is added (no restart needed)."""
    groups = _load_modules_groups()
    return [
        ComponentSummary(
            id=_COMPONENT_ID,
            code=_COMPONENT_CODE,
            name=_COMPONENT_NAME,
            desc=_COMPONENT_DESC,
            moduleCount=len(groups),
        )
    ]


@app.get("/api/v1/components/{component_id}", response_model=Component)
async def get_component(component_id: str) -> Component:
    """API 3 — full module breakdown for one component, including the
    directory/file/function tree built from metadata.json::basePath joined
    against model/functions.json. Case-insensitive component_id lookup.
    Unknown component_id → 404."""
    if component_id.upper() != _COMPONENT_ID.upper():
        raise HTTPException(status_code=404, detail=f"component {component_id!r} not found")

    groups = _load_modules_groups()
    base_path = _project_base_path()
    functions_data = _load_functions()
    by_file = _functions_by_file(functions_data)

    modules: List[Module] = []
    for module_key, inner in groups.items():
        inner_dict = inner if isinstance(inner, dict) else {}
        all_dirs = _collect_module_dirs(inner_dict)
        files_count = _count_source_files(base_path or "", all_dirs)
        tree = _build_module_tree(module_key, inner_dict, base_path, by_file)
        modules.append(
            Module(
                id=module_key,
                name=module_key,
                path=module_key,
                files=files_count,
                tree=tree,
                loc="0",  # placeholder; loc is typed str across both model shapes
            )
        )

    return Component(
        id=_COMPONENT_ID,
        code=_COMPONENT_CODE,
        name=_COMPONENT_NAME,
        desc=_COMPONENT_DESC,
        modules=modules,
    )


# ---------------------------------------------------------------------------
# Routes — Batches 2, 3, 4
# ---------------------------------------------------------------------------


@app.get("/api/v1/components/{component_id}/modules", response_model=List[ModuleSummary])
async def list_modules(component_id: str) -> List[ModuleSummary]:
    """API 4 — list modules for a component, no tree.

    Same data the modules array of API 3 carries, but lighter: no
    file/function tree built, so the response is fast even for very large
    projects. Case-insensitive component_id; unknown id → 404.
    """
    if component_id.upper() != _COMPONENT_ID.upper():
        raise HTTPException(status_code=404, detail=f"component {component_id!r} not found")

    groups = _load_modules_groups()
    base_path = _project_base_path()
    summaries: List[ModuleSummary] = []
    for module_key, inner in groups.items():
        inner_dict = inner if isinstance(inner, dict) else {}
        all_dirs = _collect_module_dirs(inner_dict)
        files_count = _count_source_files(base_path or "", all_dirs)
        summaries.append(
            ModuleSummary(
                id=module_key,
                name=module_key,
                path=module_key,
                files=files_count,
                loc="0",
            )
        )
    return summaries


@app.get("/api/v1/functions/{fn_id}", response_model=FunctionDetailWithHidden)
async def get_function(fn_id: str) -> FunctionDetailWithHidden:
    """API 5 — full function detail.

    Reads the function record from model/functions.json (the composite
    fn_id is the key), resolves callers/callees by looking up calledByIds
    and callsIds in the same table, and pulls the Mermaid script from
    output/flowcharts/*.json by matching functionKey == fn_id. Hidden
    flag is sourced from the in-memory _db["hidden_functions"] store —
    that flag is session-only by design (no JSON persistence).
    """
    functions_data = _load_functions()
    fn_info = functions_data.get(fn_id)
    if not isinstance(fn_info, dict):
        raise HTTPException(status_code=404, detail=f"function {fn_id!r} not found")

    # Descriptions are canonical in functions_<group>.json (per-module file)
    # — fall back to the master functions.json value only when no per-module
    # file exists yet (pipeline hasn't run for this group).
    desc_override = _read_description_override(fn_id)
    description = desc_override if desc_override is not None else _description_of(fn_info)

    callers: List[FunctionCaller] = []
    for caller_id in (fn_info.get("calledByIds") or []):
        caller_info = functions_data.get(caller_id) or {}
        caller_name = caller_info.get("qualifiedName") or caller_id
        callers.append(FunctionCaller(id=str(caller_id), name=str(caller_name), loc="0"))

    callees: List[FunctionCaller] = []
    for callee_id in (fn_info.get("callsIds") or []):
        callee_info = functions_data.get(callee_id) or {}
        callee_name = callee_info.get("qualifiedName") or callee_id
        callees.append(FunctionCaller(id=str(callee_id), name=str(callee_name), loc="0"))

    flowchart_text = _find_flowchart_for_fn(fn_id)
    hidden = fn_id in _db["hidden_functions"]

    loc_block = fn_info.get("location") or {}
    return FunctionDetailWithHidden(
        id=fn_id,
        name=str(fn_info.get("qualifiedName") or fn_id),
        file=str(loc_block.get("file") or ""),
        line=str(loc_block.get("line") or ""),
        ret=str(fn_info.get("returnType") or ""),
        description=description,
        callers=callers,
        callees=callees,
        flowchart=flowchart_text,
        hidden=hidden,
    )


@app.patch("/api/v1/functions/{fn_id}", response_model=PatchFunctionResult)
async def patch_function(fn_id: str, body: PatchFunctionBody) -> PatchFunctionResult:
    """API 6 — persist edited description / toggle hidden flag.

    Description writes go to model/functions.json AND model/knowledge_base.json
    (the two on-disk sources the analyzer pipeline reads from). The hidden
    flag stays in the in-memory _db only — by team agreement no JSON gets a
    `hidden` field. Returns the saved timestamp so the UI can show
    "saved at HH:MM" feedback.

    fn_id is validated against functions.json before any write; unknown
    ids return 404 without touching disk.
    """
    functions_data = _load_functions()
    if fn_id not in functions_data:
        raise HTTPException(status_code=404, detail=f"function {fn_id!r} not found")

    if body.description is not None:
        _persist_description(fn_id, body.description, functions_data)

    if body.hidden is not None:
        if body.hidden:
            _db["hidden_functions"][fn_id] = True
        else:
            _db["hidden_functions"].pop(fn_id, None)

    return PatchFunctionResult(
        fnId=fn_id,
        savedAt=datetime.now().strftime("%H:%M"),
    )


@app.get("/api/v1/flowcharts/{fn_id}", response_model=Flowchart)
async def get_flowchart(fn_id: str) -> Flowchart:
    """API 7 — return the Mermaid script for one function.

    Reads output/flowcharts/*.json (skipping `_summary.json` and any file
    starting with `_`) and matches on functionKey. Returns 404 when the
    flowchart hasn't been rendered yet for this fn_id — clients should
    surface "flowchart not generated, run the pipeline first."
    """
    entry = _find_flowchart_entry(fn_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"flowchart for {fn_id!r} not found")
    return Flowchart(
        id=fn_id,
        name=str(entry.get("name") or fn_id),
        code=str(entry.get("flowchart") or ""),
    )


@app.post("/api/v1/jobs/prepare", response_model=JobStartResult)
async def start_prepare(
    request: PrepareJobRequest,
    background_tasks: BackgroundTasks,
    name: Optional[str] = None,
) -> JobStartResult:
    """API 8 — spawn `python run.py <path>` and start tracking it.

    Project path resolution (in priority order):
      1. ?name=<repo_name> query param — looked up in
         backend/repository_config.json (404 if no such repo).
      2. request body `path` — used directly.

    Exactly one of those must yield a directory. componentId and
    moduleId are accepted for shape parity with the UI contract but
    are not forwarded to run.py — per team decision only the path
    + --selected-group (from moduleId) drive the pipeline. Job state
    lives only in memory (`_jobs[job_id]`) and is lost on FastAPI
    restart.

    The log file path + current size are recorded at spawn time so
    API 9 can return only THIS job's slice when multiple prepare jobs
    share the rolling daily log file.

    Errors:
      400 — neither `?name=` nor body `path` supplied; or the resolved
            path isn't a directory
      404 — `?name=` doesn't match any configured repository
      500 — Popen failed (e.g. python not on PATH inside the host)
    """
    if name and name.strip():
        # _resolve_repository_path raises HTTPException on miss; let it propagate
        project_path = _resolve_repository_path(name)
    else:
        project_path = (request.path or "").strip()
    if not project_path:
        raise HTTPException(
            status_code=400,
            detail="either ?name=<repo> query param or body `path` is required",
        )
    # Allow relative paths — resolve against the analyzer repo root.
    if not os.path.isabs(project_path):
        candidate = os.path.join(_REPO_ROOT, project_path)
        if os.path.isdir(candidate):
            project_path = candidate
    if not os.path.isdir(project_path):
        raise HTTPException(
            status_code=400,
            detail=f"path not found or not a directory: {project_path!r}",
        )

    # moduleId, when present, forwards as `--selected-group <name>` so the
    # pipeline only processes that module — same semantics as the CLI.
    # Empty/None moduleId runs the full project. Unknown moduleId 400s here
    # so the UI gets immediate feedback instead of an unattended full-project
    # run that the user didn't ask for.
    selected_group = _resolve_group_name(request.moduleId)
    extra_args: List[str] = ["--selected-group", selected_group] if selected_group else []

    log_file = _expected_log_file_path()
    log_offset = os.path.getsize(log_file) if os.path.isfile(log_file) else 0

    job_id = _new_job_id("prep")
    # Per-job stdout+stderr capture — catches import-time crashes (e.g.
    # libclang DLL load failure) that happen BEFORE parser.py configures
    # its logger and so never reach the rolling daily log file.
    output_file = os.path.join(_REPO_ROOT, "logs", f"job_{job_id}.out.log")

    try:
        proc = _spawn_run_py(
            project_path,
            extra_args=extra_args or None,
            output_file_path=output_file,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to spawn run.py: {exc}")

    _jobs[job_id] = {
        "type": "prepare",
        "process": proc,
        "pid": proc.pid,
        "log_file": log_file,
        "log_offset": log_offset,
        "output_file": output_file,
        "output_docx_path": _expected_docx_path(selected_group),
        "selected_group": selected_group,
        "command_line": _format_command_line(project_path, extra_args or []),
        # Snapshot how many `[N/M] === Phase ... ===` markers the planner
        # is expected to emit so /status can compute monotonic overall
        # progress even when the run splits into multiple plans (e.g.
        # build-model + per-group views+export).
        "total_phase_markers": _expected_phase_markers(
            selected_group, from_phase=1
        ),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "complete": False,
        "cancelled": False,
        "error": None,
        "return_code": None,
        "project_path": project_path,
    }

    background_tasks.add_task(_watch_subprocess_job, job_id)
    return JobStartResult(jobId=job_id)


@app.get("/api/v1/jobs/{job_id}/prepare/logs", response_model=List[PrepLog])
async def get_prepare_logs(job_id: str) -> List[PrepLog]:
    """API 9 — return up to the most recent 40 log lines emitted by this
    prepare job's run.py subprocess.

    Reads the rolling daily log file at the byte offset recorded when the
    job started, so each job's response contains only that job's slice
    even when several jobs share `logs/run_<UTC-date>.log`.

    Errors:
      404 — unknown job_id
      400 — job_id exists but isn't a prepare job (use the export endpoint)
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found")
    if job.get("type") != "prepare":
        raise HTTPException(
            status_code=400, detail=f"job {job_id!r} is not a prepare job"
        )
    # Prefer the per-job output file (true isolation, captures import-time
    # crashes). Fall back to the rolling daily log slice only if the
    # per-job file is unavailable for some reason — keeps the endpoint
    # working even when an older job (created before this fix) is queried.
    output_file = job.get("output_file") or ""
    if output_file and os.path.isfile(output_file):
        return _read_log_tail(output_file, 0, _LOG_TAIL_LIMIT)
    end_off = job.get("log_end_offset")
    return _read_log_tail(
        job.get("log_file") or "",
        int(job.get("log_offset") or 0),
        _LOG_TAIL_LIMIT,
        end_offset=int(end_off) if end_off is not None else None,
    )


@app.get("/api/v1/jobs/{job_id}/status")
async def get_job_status(job_id: str):
    """API 10 — return type/complete/progress/error for a job.

    Progress fields:
      progress         within-current-phase % (running: 50, complete: 100;
                       for export jobs this is wrapped in an
                       ExportProgress({pct, stage}) object)
      overallProgress  pipeline-wide %, 0..99 while running, 100 complete
      phase            human phase label, prefix-stripped (e.g.
                       "Derive model" not "Phase 2: Derive model")
      phaseNumber      currently running phase N (1-based), 0 when no
                       markers seen yet
      totalPhase       total phases planned for the run

    Still-running export jobs also include the redundant top-level
    `stage` field for UIs that only consume that label. 404 on unknown id.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found")

    # Live progress: while the subprocess is running, scan the per-job
    # output file for `[N/M] === Phase ... ===` markers so the UI sees
    # something better than a frozen 0. Once _finalize_job has set
    # complete=True we still scan to get phase_number/total_phase for
    # the "Phase 4 of 4 — Complete" UX, but override the percent fields.
    per_phase_pct, phase_label, phase_number, total_phase, overall_pct = \
        _compute_progress_and_phase(
            job.get("output_file") or "",
            total_expected_markers=int(job.get("total_phase_markers") or 0),
        )

    if job.get("complete"):
        # Terminal state: progress + overallProgress jump to 100; phase
        # label clears (no phase is "currently running" any more) but
        # we keep phaseNumber/totalPhase so the UI can show
        # "Completed 4 of 4 phases" etc.
        phase_label = ""
        overall_pct = 100
        if job.get("type") == "export":
            existing = job.get("progress")
            stage = existing.stage if isinstance(existing, ExportProgress) else "done"
            progress = ExportProgress(pct=100, stage=stage)
        else:
            progress = 100
    else:
        if job.get("type") == "export":
            existing = job.get("progress")
            stage = existing.stage if isinstance(existing, ExportProgress) else "running"
            progress = ExportProgress(pct=per_phase_pct, stage=stage)
        else:
            progress = per_phase_pct

    response: Dict = {
        "jobId": job_id,
        "type": job.get("type"),
        "complete": bool(job.get("complete")),
        "progress": progress,
        "overallProgress": overall_pct,
        "phase": phase_label,
        "phaseNumber": phase_number,
        "totalPhase": total_phase,
        "error": job.get("error"),
        # Verification fields — let the UI confirm which CLI was actually
        # spawned without having to open the per-job log file.
        "selectedGroup": job.get("selected_group"),
        "commandLine": job.get("command_line"),
    }
    if job.get("type") == "export":
        prog = response["progress"]
        response["stage"] = prog.stage if isinstance(prog, ExportProgress) else ""
    return response


@app.delete("/api/v1/jobs/{job_id}")
async def cancel_job(job_id: str):
    """API 11 — full process-tree kill of a running job.

    Sets cancelled=True, kills the subprocess and its descendants
    (taskkill /F /T on Windows, killpg(SIGKILL) on POSIX), waits up to
    2 seconds for the process to exit, then finalises the job so a
    follow-up /status call returns complete=True without waiting for
    the watcher's next poll.

    Idempotent: cancelling an already-complete job returns the same
    `{"status": "cancelled"}` shape — there's nothing useful for the
    UI to do with a "too late" signal.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found")

    if job.get("complete"):
        return {"status": "cancelled"}

    job["cancelled"] = True
    proc: Optional[subprocess.Popen] = job.get("process")
    if proc is None:
        _finalize_job(job_id, rc=None, error="cancelled by user")
        return {"status": "cancelled"}

    _kill_process_tree(proc)
    # Give the OS a moment to reap the process so /status reflects
    # complete=True before the next request lands.
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    rc = proc.poll()
    _finalize_job(job_id, rc=rc, error="cancelled by user")
    return {"status": "cancelled"}


@app.get("/api/v1/jobs/{job_id}/export/status")
async def get_export_status(job_id: str):
    """Docx-artifact status: extends API 10 with the docx filename and
    a ready-to-use download URL once the file is on disk. The UI polls
    this until `complete` is true, then hits `downloadUrl`.

    Works for BOTH prepare and export jobs — `python run.py <path>`
    without --from-phase already runs phase 4, so a prepare job produces
    the same docx an export job does. The endpoint is named
    `/export/status` for URL stability; the action is "status of the
    docx this job is producing."

    Response:
      jobId, complete, stage, progress (pct), error, filename (or null),
      downloadUrl (or null), hiddenCount (always 0 — hiddenFns ignored).

    Errors:
      404 — unknown job_id
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found")
    prog = job.get("progress")
    if isinstance(prog, ExportProgress):
        stage = prog.stage
        pct = prog.pct
    else:
        # Prepare jobs (progress is a plain int) don't carry an ExportProgress
        # but the UI still wants a `stage` label. Synthesize one from the
        # job's terminal state so the docx-status endpoint behaves the same
        # whether the docx came from prepare or from --from-phase 4 export.
        pct = int(prog or 0)
        if not job.get("complete"):
            stage = "running"
        elif (job.get("error") or "").lower().startswith("cancelled"):
            stage = "cancelled"
        elif job.get("error"):
            stage = "failed"
        else:
            stage = "done"

    # Live progress / phase label — see API 10 for rationale.
    per_phase_pct, phase_label, phase_number, total_phase, overall_pct = \
        _compute_progress_and_phase(
            job.get("output_file") or "",
            total_expected_markers=int(job.get("total_phase_markers") or 0),
        )
    if not job.get("complete") and per_phase_pct > 0:
        pct = per_phase_pct
    if job.get("complete"):
        # Terminal state: phase label clears, overall jumps to 100; keep
        # phaseNumber/totalPhase so the UI can show "4 of 4" etc.
        phase_label = ""
        overall_pct = 100
        pct = 100

    docx_path = job.get("output_docx_path") or ""
    has_file = bool(docx_path and os.path.isfile(docx_path))
    return {
        "jobId": job_id,
        "complete": bool(job.get("complete")),
        "stage": stage,
        "phase": phase_label,
        "phaseNumber": phase_number,
        "totalPhase": total_phase,
        "progress": pct,
        "overallProgress": overall_pct,
        "error": job.get("error"),
        "filename": os.path.basename(docx_path) if has_file else None,
        "downloadUrl": f"/api/v1/jobs/{job_id}/export/download" if has_file else None,
        "hiddenCount": 0,
        "selectedGroup": job.get("selected_group"),
        "commandLine": job.get("command_line"),
    }


@app.get("/api/v1/jobs/{job_id}/export/download")
async def download_export(job_id: str):
    """Stream the docx produced by this job back to the caller.

    Works for BOTH prepare and export jobs — `python run.py <path>` (no
    --from-phase) already runs phase 4 at the tail of the full pipeline,
    so a prepare job's output_docx_path is just as real as an export
    job's. The endpoint name keeps "export" for URL stability.

    Standard browser download flow: returns a FileResponse with the
    Office content type and a Content-Disposition that uses the docx's
    basename.

    Errors:
      404 — unknown job_id or the docx file is missing on disk
      409 — job hasn't completed yet, or completed with an error
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id!r} not found")
    if not job.get("complete"):
        raise HTTPException(
            status_code=409, detail=f"job {job_id!r} not complete yet"
        )
    if job.get("error"):
        raise HTTPException(
            status_code=409,
            detail=f"job {job_id!r} failed: {job['error']}",
        )
    docx_path = job.get("output_docx_path") or ""
    if not docx_path or not os.path.isfile(docx_path):
        raise HTTPException(
            status_code=404,
            detail=f"docx not found on disk: {docx_path or '(no path recorded)'}",
        )
    return FileResponse(
        path=docx_path,
        filename=os.path.basename(docx_path),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )


# ---------------------------------------------------------------------------
# Project-structure helpers
# ---------------------------------------------------------------------------

# Filename for the small "where is the CPP project on this machine?" pointer.
# Hand-edited by the user / written by an external tool — the backend only
# reads it. Lives next to main.py so the path resolver doesn't depend on
# repo layout (works whether backend/ sits at the analyzer root or under
# fast-app/ or anywhere else).
_REPOSITORY_CONFIG_NAME = "repository_config.json"


def _repository_config_path() -> str:
    return os.path.join(_BACKEND_DIR, _REPOSITORY_CONFIG_NAME)


def _load_repositories() -> List[Dict[str, str]]:
    """Read the repositories list from backend/repository_config.json.

    Returns [] if the file is missing, unreadable, or malformed — callers
    handle the "no repos configured" case so error messages can be
    specific to the endpoint that needed one.

    Auto-migrates the legacy `{"path": "..."}` single-repo format into
    `[{"name": "default", "path": "..."}]` so existing on-disk configs
    keep working without a manual edit.
    """
    path_file = _repository_config_path()
    if not os.path.isfile(path_file):
        return []
    try:
        with open(path_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    # New format: list of {name, path}
    if isinstance(data, list):
        out: List[Dict[str, str]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            path = str(entry.get("path") or "").strip()
            if name and path:
                out.append({"name": name, "path": path})
        return out

    # Legacy single-repo format: {"path": "..."} -> [{"name": "default", "path": "..."}]
    if isinstance(data, dict):
        legacy_path = str(data.get("path") or "").strip()
        if legacy_path:
            return [{"name": "default", "path": legacy_path}]
    return []


def _save_repositories(repos: List[Dict[str, str]]) -> None:
    """Atomically write the repositories list to backend/repository_config.json,
    creating the file (and the parent directory) if either is missing."""
    path_file = _repository_config_path()
    os.makedirs(os.path.dirname(path_file) or ".", exist_ok=True)
    _safe_write_json(path_file, repos)


def _resolve_repository_path(name: str) -> str:
    """Return the on-disk path for the repository with the given name.

    Raises HTTPException(404) if no repository has that name — callers
    can let it propagate so the error reaches the client unchanged.
    """
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="repository name is empty")
    for r in _load_repositories():
        if r["name"] == name:
            path = (r.get("path") or "").strip()
            if not path:
                raise HTTPException(
                    status_code=400,
                    detail=f"repository {name!r} has no path configured",
                )
            return path
    raise HTTPException(
        status_code=404,
        detail=f"repository {name!r} not found in repository_config.json",
    )


def _walk_project_structure(abs_path: str, dirs_only: bool = False) -> Dict:
    """Return a minimal structure tree: every node has `name`; directories
    additionally carry `children`. UI infers type by `"children" in node`.

    Dotfiles / dot-directories are skipped (handles `.git`, `.flowchart_cache`,
    `.vscode`, etc. uniformly across Windows + Linux without poking at
    OS-specific hidden-attribute bits). Sort order: directories first then
    files, alphabetical within each group, so identical projects produce
    byte-identical responses across runs.

    When `dirs_only=True`, file entries are omitted from `children` —
    only directories appear. Useful for tree-view sidebars that just
    want navigation without leaf nodes.
    """
    name = os.path.basename(abs_path) or abs_path
    if os.path.isdir(abs_path):
        try:
            entries = sorted(os.listdir(abs_path))
        except OSError:
            entries = []
        entries = [e for e in entries if not e.startswith(".")]
        sub_dirs = [e for e in entries if os.path.isdir(os.path.join(abs_path, e))]
        children = [
            _walk_project_structure(os.path.join(abs_path, e), dirs_only=dirs_only)
            for e in sub_dirs
        ]
        if not dirs_only:
            sub_files = [
                e for e in entries
                if not os.path.isdir(os.path.join(abs_path, e))
            ]
            children.extend(
                _walk_project_structure(os.path.join(abs_path, e), dirs_only=dirs_only)
                for e in sub_files
            )
        return {"name": name, "children": children}
    return {"name": name}


# ---------------------------------------------------------------------------
# Surgical JSONC modifier for config.json
# ---------------------------------------------------------------------------

def _find_modules_groups_key_pos(raw_text: str) -> int:
    """Return the byte offset of the opening `"` of the root-level
    `"modulesGroups"` key in raw JSONC text, or -1 if not found.

    Walks the entire file with full JSONC awareness — strings (with
    `\\"` escape handling), `//` line comments, `/* */` block comments,
    and `{}` nesting. The match is only accepted when:
      - we're at object depth 1 (so it's a root-level key, not a key
        in some nested object that happens to share the name)
      - the next non-whitespace char is `:` (so it's a key, not just
        a string literal that reads "modulesGroups")

    This is a hardening over the previous str.find() approach, which
    could match the literal substring `"modulesGroups"` appearing
    *inside* a clangArg string value (very plausible for huge office
    configs with hundreds of clang flags). A false match there would
    send the brace tracker into the wrong region of the file and
    produce truncated output — the 80%-of-config-written behaviour
    reported earlier.
    """
    pos = 0
    n = len(raw_text)
    depth = 0
    in_string = False
    escape = False
    in_line_comment = False
    in_block_comment = False
    string_start = -1

    while pos < n:
        c = raw_text[pos]

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            pos += 1
            continue
        if in_block_comment:
            if c == "*" and pos + 1 < n and raw_text[pos + 1] == "/":
                in_block_comment = False
                pos += 2
                continue
            pos += 1
            continue
        if in_string:
            if escape:
                escape = False
                pos += 1
                continue
            if c == "\\":
                escape = True
                pos += 1
                continue
            if c == '"':
                # String just closed — was it our key?
                if depth == 1 and raw_text[string_start + 1:pos] == "modulesGroups":
                    nxt = pos + 1
                    while nxt < n and raw_text[nxt] in " \t\r\n":
                        nxt += 1
                    if nxt < n and raw_text[nxt] == ":":
                        return string_start
                in_string = False
                pos += 1
                continue
            pos += 1
            continue

        if c == '"':
            in_string = True
            string_start = pos
            pos += 1
            continue
        if c == "/" and pos + 1 < n:
            nxt = raw_text[pos + 1]
            if nxt == "/":
                in_line_comment = True
                pos += 2
                continue
            if nxt == "*":
                in_block_comment = True
                pos += 2
                continue

        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        pos += 1

    return -1


def _splice_modules_groups(raw_text: str, new_value: dict) -> str:
    """Replace JUST the `modulesGroups` value inside the raw JSONC text,
    preserving every other key, all comments (// and /* */), and the
    original formatting elsewhere in the file.

    Uses a JSONC-aware key finder (so a `"modulesGroups"` substring
    inside another string can't trigger a false match) plus a brace-
    nesting scanner that understands strings and comments — never
    replaces a `{ ... }` that's actually inside a string literal or
    comment.

    Raises ValueError when modulesGroups isn't present or its value
    isn't a JSON object (so the caller can return 400 with a meaningful
    detail instead of writing garbage to disk).
    """
    idx = _find_modules_groups_key_pos(raw_text)
    if idx < 0:
        raise ValueError("modulesGroups key not found at root level of config.json")

    # Skip past the literal `"modulesGroups"` then the whitespace + `:`
    pos = idx + len('"modulesGroups"')
    while pos < len(raw_text) and raw_text[pos] in " \t\r\n:":
        pos += 1
    if pos >= len(raw_text) or raw_text[pos] != "{":
        raise ValueError("modulesGroups value is not an object")

    value_start = pos
    depth = 0
    in_string = False
    escape = False
    in_line_comment = False
    in_block_comment = False
    value_end = -1

    while pos < len(raw_text):
        c = raw_text[pos]

        if in_line_comment:
            if c == "\n":
                in_line_comment = False
            pos += 1
            continue
        if in_block_comment:
            if c == "*" and pos + 1 < len(raw_text) and raw_text[pos + 1] == "/":
                in_block_comment = False
                pos += 2
                continue
            pos += 1
            continue
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            pos += 1
            continue

        if c == '"':
            in_string = True
            pos += 1
            continue
        if c == "/" and pos + 1 < len(raw_text):
            nxt = raw_text[pos + 1]
            if nxt == "/":
                in_line_comment = True
                pos += 2
                continue
            if nxt == "*":
                in_block_comment = True
                pos += 2
                continue

        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                value_end = pos + 1
                break
        pos += 1

    if value_end < 0:
        raise ValueError("unmatched braces inside modulesGroups value")

    # Indent the new JSON to sit at the same column as the key, so the
    # diff against the original file is local to this one block.
    line_start = raw_text.rfind("\n", 0, idx) + 1
    indent = raw_text[line_start:idx]
    new_json = json.dumps(new_value, indent=2, ensure_ascii=False)
    if "\n" in new_json:
        first, rest = new_json.split("\n", 1)
        rest = "\n".join(indent + line if line else line for line in rest.split("\n"))
        new_json = first + "\n" + rest
    return raw_text[:value_start] + new_json + raw_text[value_end:]


@app.get("/api/v1/project/structure")
async def get_project_structure(
    name: Optional[str] = None,
    dirsOnly: bool = False,
):
    """Return the directory/file tree of one configured repository.

    Shape (recursive):
        directory -> { "name": str, "children": StructureNode[] }
        file      -> { "name": str }   (no `children` key at all)
    The UI distinguishes by `"children" in node`. Dotfiles / dot-dirs
    are skipped. Sort order: dirs first, then files, alphabetical
    within each group. Depth is unlimited.

    Query params:
      ?name=<repo_name> — pick a specific repository by name. When
        omitted, the FIRST entry in backend/repository_config.json is
        used (matches the previous single-repo behaviour).
      ?dirsOnly=true — omit file entries from the response, returning
        a directories-only tree. Useful for navigation sidebars. Default
        is `false` (files included).

    Errors:
      404 — no repositories configured / unknown name / path doesn't
            resolve to an existing directory
    """
    repos = _load_repositories()
    if not repos:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no repositories configured in backend/{_REPOSITORY_CONFIG_NAME} — "
                f"POST /api/v1/repository to add the first"
            ),
        )
    if name:
        match = next((r for r in repos if r["name"] == name), None)
        if not match:
            raise HTTPException(
                status_code=404, detail=f"repository {name!r} not found"
            )
        project_path = match["path"]
    else:
        project_path = repos[0]["path"]

    if not project_path or not os.path.isdir(project_path):
        raise HTTPException(
            status_code=404,
            detail=f"project path does not exist or is not a directory: {project_path!r}",
        )
    return _walk_project_structure(project_path, dirs_only=dirsOnly)


@app.post("/api/v1/config")
async def update_config(body: UpdateConfigRequest, dryRun: bool = False):
    """Replace ONLY the `modulesGroups` block in config/config.json,
    preserving every other top-level key (`views`, `clang`, `llm`,
    `export`, ...), all `//` and `/* */` comments, trailing commas,
    and the whitespace/formatting elsewhere in the file.

    Strategy: JSONC-aware surgical splice. No parse-and-rewrite
    fallback — if the splice produces unparseable text the endpoint
    refuses to write and dumps the attempted output to
    `logs/config_splice_failed_<UTC>.json` so it can be diagnosed.
    Per team decision, comments must survive every save; we never
    silently strip them.

    Body:
      { "modulesGroups": { ... } }

    Query params:
      ?dryRun=true — run the splice + validation but don't write to
        disk. Returns the would-have-been-written byte size.

    Errors:
      404 — config/config.json missing
      400 — body missing modulesGroups; modulesGroups not present at
            root of the on-disk file; or the splice produced
            unparseable text (response includes the parser error
            position and a path to the diagnostic dump)
      500 — IO failure during write
    """
    new_groups = body.modulesGroups
    config_path = os.path.join(_REPO_ROOT, "config", "config.json")
    if not os.path.isfile(config_path):
        raise HTTPException(status_code=404, detail="config/config.json not found")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to read config.json: {exc}")

    try:
        updated_text = _splice_modules_groups(raw_text, new_groups)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Validate that the spliced result is still parseable JSONC.
    from core.config import _strip_json_comments, _strip_trailing_commas  # type: ignore
    try:
        cleaned = _strip_trailing_commas(_strip_json_comments(updated_text))
        json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Dump the failed output for inspection — invaluable when the
        # splice mis-tracks something specific to a particular config.
        diag_path = ""
        try:
            logs_dir = os.path.join(_REPO_ROOT, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            diag_path = os.path.join(logs_dir, f"config_splice_failed_{stamp}.json")
            with open(diag_path, "w", encoding="utf-8") as f:
                f.write(updated_text)
        except OSError:
            diag_path = ""
        raise HTTPException(
            status_code=400,
            detail=(
                f"refused to write {config_path}: result would be unparseable "
                f"JSON — {exc.msg} at line {exc.lineno} col {exc.colno}"
                + (f"; diagnostic copy at {diag_path}" if diag_path else "")
            ),
        )

    if dryRun:
        return {
            "status": "dryRun",
            "wouldWrite": config_path,
            "moduleCount": len(new_groups),
            "modules": sorted(list(new_groups.keys())),
            "previewBytes": len(updated_text),
        }

    try:
        _safe_write_json_text(config_path, updated_text)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to write config.json: {exc}")

    return {
        "status": "ok",
        "moduleCount": len(new_groups),
        "modules": sorted(list(new_groups.keys())),
    }


def _safe_write_json_text(path: str, text: str) -> None:
    """Atomic-replace flavour of _safe_write_json that takes pre-serialised
    text (so we can keep comments and exact whitespace from a surgical edit).
    """
    dir_ = os.path.dirname(path) or "."
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False, dir=dir_, suffix=".tmp"
    )
    try:
        tmp.write(text)
        tmp.flush()
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


@app.get("/api/v1/config")
async def get_config_raw():
    """Return the parsed contents of config/config.json as JSON.

    The on-disk file is JSONC (allows // line comments and trailing
    commas); we strip those using the same helpers the analyzer pipeline
    uses so the response is exactly what the pipeline sees, just without
    the comment syntax. config.local.json overrides are NOT applied here
    — this endpoint deliberately returns only config.json so the UI sees
    the canonical, version-controlled values.

    Errors:
      404 — config/config.json missing
      500 — file is present but unparseable
    """
    config_path = os.path.join(_REPO_ROOT, "config", "config.json")
    if not os.path.isfile(config_path):
        raise HTTPException(status_code=404, detail="config/config.json not found")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
        # Reuse the analyzer's JSONC sanitiser so the API answers exactly
        # what the pipeline parses.
        from core.config import _strip_json_comments, _strip_trailing_commas  # type: ignore
        cleaned = _strip_trailing_commas(_strip_json_comments(raw_text))
        return json.loads(cleaned)
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to parse config.json: {exc}")


@app.post("/api/v1/jobs/export", response_model=JobStartResult)
async def start_export(
    request: ExportJobRequest,
    background_tasks: BackgroundTasks,
    name: Optional[str] = None,
) -> JobStartResult:
    """API 12 — spawn `python run.py <path> --from-phase 4`.

    Phase 4 is the docx export step in the analyzer pipeline; we resume
    from there so we don't re-parse and re-derive. componentId / moduleId
    are accepted for shape parity but not forwarded (path drives the
    pipeline). hiddenFns is ignored per team decision — the per-function
    hide isn't wired through run.py yet.

    Project path resolution (in priority order):
      1. ?name=<repo_name> query param — looked up in
         backend/repository_config.json (404 if no such repo).
      2. request body `path` — used directly.

    Same spawn/watch infrastructure as start_prepare; only difference is
    the extra --from-phase 4 argument and the initial progress shape
    (ExportProgress with pct=0/stage='running' instead of plain 0).

    Validation:
      400 — neither `?name=` nor body `path` supplied; or resolved path
            isn't a directory
      404 — `?name=` doesn't match any configured repository
      500 — Popen failed
    """
    if name and name.strip():
        project_path = _resolve_repository_path(name)
    else:
        project_path = (request.path or "").strip()
    if not project_path:
        raise HTTPException(
            status_code=400,
            detail="either ?name=<repo> query param or body `path` is required",
        )
    if not os.path.isabs(project_path):
        candidate = os.path.join(_REPO_ROOT, project_path)
        if os.path.isdir(candidate):
            project_path = candidate
    if not os.path.isdir(project_path):
        raise HTTPException(
            status_code=400,
            detail=f"path not found or not a directory: {project_path!r}",
        )

    # Same moduleId → --selected-group plumbing as start_prepare, so
    # exports can also be scoped to one module instead of regenerating
    # the docx for the entire project.
    selected_group = _resolve_group_name(request.moduleId)
    extra_args: List[str] = ["--from-phase", "4"]
    if selected_group:
        extra_args.extend(["--selected-group", selected_group])

    log_file = _expected_log_file_path()
    log_offset = os.path.getsize(log_file) if os.path.isfile(log_file) else 0

    job_id = _new_job_id("exp")
    output_file = os.path.join(_REPO_ROOT, "logs", f"job_{job_id}.out.log")

    try:
        proc = _spawn_run_py(
            project_path,
            extra_args=extra_args,
            output_file_path=output_file,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to spawn run.py: {exc}")

    _jobs[job_id] = {
        "type": "export",
        "process": proc,
        "pid": proc.pid,
        "log_file": log_file,
        "log_offset": log_offset,
        "output_file": output_file,
        "output_docx_path": _expected_docx_path(selected_group),
        "selected_group": selected_group,
        "command_line": _format_command_line(project_path, extra_args),
        # Export jobs run with --from-phase 4 — see _expected_phase_markers
        # for how that resolves to a marker count given the live config.
        "total_phase_markers": _expected_phase_markers(
            selected_group, from_phase=4
        ),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "complete": False,
        "cancelled": False,
        "error": None,
        "return_code": None,
        "project_path": project_path,
        "progress": ExportProgress(pct=0, stage="running"),
        "result": None,
    }

    background_tasks.add_task(_watch_subprocess_job, job_id)
    return JobStartResult(jobId=job_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
