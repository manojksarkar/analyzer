"""
Real analysis-job runner.

Replaces the mock's job_runner.py simulation with actual subprocess calls to
run.py. A daemon thread per job handles the full lifecycle:

  1. Clone / check out the project commit into workspaces/<project_id>/<sha16>/.
  2. Write a per-project config.json (base config + build_config overrides +
     architecture_layers → layers schema) and pass it via --config.
  3. Invoke run.py as a subprocess (shell=False, cwd=repo_root), capturing
     combined stdout+stderr so all phase-script output flows through.
  4. Tail subprocess output: detect phase transitions, update job record for SSE.
  5. On completion: register a real Version + Documents from output/ dirs.
  6. On failure: mark job failed with the tail of subprocess output.
  7. On cancel: terminate the subprocess immediately.

Public surface used by routes/jobs.py:
  start(db, job_id)            — kick off on a daemon thread
  cancel_subprocess(job_id)    — kill the running subprocess
  signal_resume(job_id)        — unblock a paused thread
  reexport(db, job_id)         — run Phase 4 only on a daemon thread
  get_log_lines(job_id, after) — (lines, new_cursor) for SSE streaming
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Set

from ..models.domain import Version, Document
from . import git_cli
from .settings import get_settings

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Per-job state (thread-safe via _LOCK)
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_job_logs: dict[str, deque] = {}        # recent log lines (ring buffer)
_job_log_totals: dict[str, int] = {}    # monotonic line count (for SSE cursor)
_job_procs: dict[str, subprocess.Popen] = {}
_job_resume_events: dict[str, threading.Event] = {}
_LOG_MAX = 500

# Concurrency semaphore — lazily initialised from JOB_MAX_CONCURRENCY setting.
_SEMAPHORE: Optional[threading.BoundedSemaphore] = None
_SEM_LOCK = threading.Lock()


def _get_semaphore() -> threading.BoundedSemaphore:
    global _SEMAPHORE
    with _SEM_LOCK:
        if _SEMAPHORE is None:
            _SEMAPHORE = threading.BoundedSemaphore(get_settings().job_max_concurrency)
        return _SEMAPHORE


_PHASES = [(1, "Parse C++"), (2, "Derive Model"), (3, "Run Views"), (4, "Export DOCX")]
_ACTIVITY = {
    1: "Parsing C++ sources with libclang…",
    2: "Deriving model + enriching with LLM…",
    3: "Rendering views, diagrams and flowcharts…",
    4: "Exporting Software Detailed Design DOCX…",
}

# Phase name fragments that appear in PhaseRunner log lines
# e.g.: "INFO orchestration: [1/4] === Phase 1: Parse C++ source ==="
_PHASE_MARKERS = {
    1: "Phase 1:",
    2: "Phase 2:",
    3: "Phase 3:",
    4: "Phase 4:",
}


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start(db: Any, job_id: str) -> None:
    """Kick off the real pipeline on a daemon thread (returns immediately)."""
    t = threading.Thread(target=_run, args=(db, job_id), daemon=True, name=f"job-{job_id}")
    t.start()


def cancel_subprocess(job_id: str) -> None:
    """Terminate the subprocess for the given job (if still alive)."""
    with _LOCK:
        proc = _job_procs.get(job_id)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


def signal_resume(job_id: str) -> None:
    """Unblock a thread that is holding at the pause point."""
    with _LOCK:
        ev = _job_resume_events.get(job_id)
    if ev is not None:
        ev.set()


def reexport(db: Any, job_id: str) -> None:
    """Run Phase 4 only (re-export DOCX) on a daemon thread."""
    t = threading.Thread(target=_do_reexport, args=(db, job_id), daemon=True,
                         name=f"reexport-{job_id}")
    t.start()


def get_log_lines(job_id: str, after_idx: int) -> tuple[list[str], int]:
    """Return (new_lines, updated_cursor) for SSE streaming. Thread-safe."""
    with _LOCK:
        buf = _job_logs.get(job_id)
        total = _job_log_totals.get(job_id, 0)
    if buf is None:
        return [], after_idx
    lines = list(buf)
    buf_start = max(0, total - len(lines))
    start = max(0, after_idx - buf_start)
    return lines[start:], total


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _append_log(job_id: str, line: str) -> None:
    with _LOCK:
        buf = _job_logs.get(job_id)
        if buf is None:
            return
        buf.append(line)
        _job_log_totals[job_id] = _job_log_totals.get(job_id, 0) + 1


def _init_state(job_id: str) -> None:
    with _LOCK:
        _job_logs[job_id] = deque(maxlen=_LOG_MAX)
        _job_log_totals[job_id] = 0
        _job_resume_events[job_id] = threading.Event()


def _cleanup_state(job_id: str) -> None:
    with _LOCK:
        _job_procs.pop(job_id, None)
        _job_resume_events.pop(job_id, None)
        # Keep logs so SSE can drain remaining lines after completion


def _mark_failed(db: Any, job_id: str, message: str) -> None:
    job = db.jobs.get(job_id)
    if job and job.status not in ("cancelled", "complete", "failed"):
        job.status = "failed"
        job.error_message = message[:4000]
        job.completed_at = _now()
        db.jobs.update(job)


# ---------------------------------------------------------------------------
# Main thread entry
# ---------------------------------------------------------------------------

def _run(db: Any, job_id: str) -> None:
    try:
        _init_state(job_id)
        _inner_run(db, job_id)
    except Exception as exc:
        _mark_failed(db, job_id, f"Runner error: {exc}")
    finally:
        _cleanup_state(job_id)


def _inner_run(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return
    project = db.projects.get(job.project_id)
    if not project:
        _mark_failed(db, job_id, "Project not found.")
        return

    # Respect JOB_MAX_CONCURRENCY — block until a slot is free (or job cancelled).
    sem = _get_semaphore()
    while not sem.acquire(timeout=2.0):
        if _is_cancelled(db, job_id):
            return

    try:
        _inner_run_locked(db, job_id, project)
    finally:
        sem.release()


def _scope_to_cli(scope: Any) -> str:
    """Map a scope dict {type, names} to the engine's --scope string
    (project | layer:L | group:G | component:C1,C2)."""
    if not isinstance(scope, dict):
        return "project"
    stype = scope.get("type") or "project"
    names = scope.get("names") or []
    if stype == "project" or not names:
        return "project"
    return f"{stype}:{','.join(str(n) for n in names)}"


def _inner_run_locked(db: Any, job_id: str, project: Any) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return

    job.status = "running"
    job.current_activity = "Preparing workspace…"
    db.jobs.update(job)
    _append_log(job_id, "Starting analysis pipeline…")

    root = get_settings().repo_root

    # 1. Checkout commit
    checkout_dir = root / "workspaces" / job.project_id / job.commit_sha[:16]
    try:
        _checkout(project, job.commit_sha, checkout_dir, job_id)
    except Exception as exc:
        _mark_failed(db, job_id, f"Checkout failed: {exc}")
        return

    _append_log(job_id, f"Checked out commit {job.commit_sha[:8]} → {checkout_dir.name}")

    # 2. Write per-project config
    workspace_dir = root / "workspaces" / job.project_id
    try:
        config_path = _write_project_config(project, workspace_dir,
                                            no_llm=bool(getattr(job, "no_llm", False)))
    except Exception as exc:
        _mark_failed(db, job_id, f"Config generation failed: {exc}")
        return
    _append_log(job_id, f"Config written to {config_path.name}")

    if _is_cancelled(db, job_id):
        return

    job = db.jobs.get(job_id)
    job.current_activity = _ACTIVITY[1]
    db.jobs.update(job)

    # 3. Run the version4 incremental engine (does what the old /generate did):
    #    mode "full"  -> src/incremental/generate.py (force a full generation)
    #    otherwise    -> src/incremental/engine.py, which selects the nearest-ancestor
    #                    baseline itself (an explicit reference_version_id still wins) and
    #                    falls back to full when there is none.
    #    The engine reuses the checkout we just made, writes model/output + manifest INTO
    #    the commit dir (workspaces/<pid>/<commit[:16]>/), and seeds the reuse index. The
    #    job lifecycle (SSE phase tailing, cancel) wraps the subprocess as before.
    job = db.jobs.get(job_id)
    mode = (getattr(job, "mode", "auto") or "auto")
    scope = getattr(job, "scope", None) or {"type": "project"}
    script = "generate.py" if mode == "full" else "engine.py"
    cmd = [sys.executable, str(root / "src" / "incremental" / script),
           "--project-id", job.project_id, "--branch", job.branch,
           "--commit", job.commit_sha, "--scope", _scope_to_cli(scope),
           "--config", str(config_path)]
    if mode != "full" and getattr(job, "reference_version_id", None):
        cmd += ["--base-version-id", job.reference_version_id]
    if getattr(job, "data_dict_id", None):
        cmd += ["--data-dict-id", job.data_dict_id]
    if getattr(job, "no_llm", False):
        cmd.append("--no-llm")
    if mode != "full" and getattr(job, "narrowed_parse", False):
        cmd.append("--narrowed-parse")
    _append_log(job_id, f"Generating ({'full' if mode == 'full' else 'auto'}) via {script}…")

    ok = _execute_subprocess(db, job_id, cmd, phase_start=1)
    if ok:
        _complete(db, job_id)


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def _checkout(project: Any, commit_sha: str, checkout_dir: Path, job_id: str) -> None:
    """Clone (or reuse) the project repo and check out commit_sha."""
    if checkout_dir.is_dir() and (checkout_dir / ".git").is_dir():
        _append_log(job_id, "Reusing existing checkout.")
        return

    bc = project.build_config or {}
    token = bc.get("repo_access_token") or bc.get("access_token") or ""
    token = (token or "").strip()
    username = token  # PAT goes in username position for GitHub/GitLab
    password = ""

    checkout_dir.mkdir(parents=True, exist_ok=True)

    # Shallow clone — enough depth to reach the target commit
    git_cli.shallow_clone(
        project.repo_url, username, password, str(checkout_dir),
        ref=project.default_branch or "main",
        depth=50,
    )

    # Check out the specific commit
    git_exe = shutil.which("git") or "git"
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    r = subprocess.run(
        [git_exe, "-C", str(checkout_dir), "checkout", commit_sha],
        capture_output=True, text=True, env=env, shell=False,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git checkout {commit_sha[:8]} failed: {r.stderr.strip()}")


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

def _write_project_config(project: Any, workspace_dir: Path, *, no_llm: bool = False) -> Path:
    """Write a per-project config.json by merging the base config with project settings."""
    base_path = get_settings().repo_root / "config" / "config.json"
    try:
        with open(base_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        cfg = {}

    # Apply explicit section overrides from build_config
    bc = project.build_config or {}
    for key in ("clang", "llm", "views", "docx"):
        if key in bc and isinstance(bc[key], dict):
            cfg.setdefault(key, {})
            cfg[key].update(bc[key])

    # Convert architecture_layers to the layers schema
    layers = _convert_layers(project.architecture_layers or [])
    if layers:
        cfg["layers"] = layers

    # noLlm — disable per-entity LLM (descriptions + behaviour names), mirroring
    # apply_no_llm. Phase summarization is disabled via --no-llm-summarize in _build_cmd.
    if no_llm:
        cfg.setdefault("llm", {})
        cfg["llm"]["descriptions"] = False
        cfg["llm"]["behaviourNames"] = False

    workspace_dir.mkdir(parents=True, exist_ok=True)
    out_path = workspace_dir / "config.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return out_path


def _convert_layers(arch_layers: list) -> dict:
    """Convert API architecture_layers list to config.json layers dict.

    API shape (from NewProjectPage):
      [{"name": "L1", "path": "Layer1", "lib_paths": [...],
        "groups": [{"name": "G1", "components": [{"name": "C1", "files": [...]}]}]}]
    Config shape:
      {"L1": {"path": "Layer1", "groups": {"G1": {"C1": "Sample/C1"}}}}

    Component paths are derived from the files list: the common ancestor directory
    of all selected files, stripped of the layer path prefix.
    """
    result: dict = {}
    for layer in arch_layers:
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "").strip()
        lpath = str(layer.get("path") or lname).strip()
        if not lname:
            continue
        groups: dict = {}
        for g in (layer.get("groups") or []):
            if isinstance(g, str):
                gname, comps = g.strip(), {}
            elif isinstance(g, dict):
                gname = str(g.get("name") or "").strip()
                comps = {}
                for c in (g.get("components") or []):
                    if isinstance(c, str):
                        cname = c.strip()
                        if cname:
                            comps[cname] = cname
                    elif isinstance(c, dict):
                        cname = str(c.get("name") or "").strip()
                        files = [str(f) for f in (c.get("files") or []) if f]
                        if cname:
                            comp_path = _derive_component_path(files, lpath) or cname
                            comps[cname] = comp_path
            else:
                continue
            if gname:
                groups[gname] = comps
        result[lname] = {"path": lpath, "groups": groups}
    return result


def _derive_component_path(files: list, layer_path: str) -> str:
    """Return the component directory path relative to layer_path.

    Finds the common ancestor directory of all file paths, then strips the
    layer_path prefix so the result is relative to the layer root.
    """
    import posixpath
    dirs = [posixpath.dirname(f.replace("\\", "/")) for f in files if f]
    dirs = [d for d in dirs if d]
    if not dirs:
        return ""
    common = dirs[0]
    for d in dirs[1:]:
        while common and not (d == common or d.startswith(common + "/")):
            common = posixpath.dirname(common)
    if not common:
        return ""
    layer_norm = layer_path.rstrip("/").replace("\\", "/")
    if common == layer_norm:
        return ""
    if layer_norm and common.startswith(layer_norm + "/"):
        return common[len(layer_norm) + 1:]
    return common


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------

def _build_cmd(
    job: Any,
    checkout_dir: Path,
    config_path: Path,
    *,
    from_phase: int = 1,
    to_phase: Optional[int] = None,
    use_model: bool = False,
    arch_layers: list = (),
) -> list[str]:
    cmd = [sys.executable, str(get_settings().repo_root / "run.py")]
    cmd += ["--config", str(config_path)]
    if use_model:
        cmd.append("--use-model")
    if from_phase > 1:
        cmd += ["--from-phase", str(from_phase)]
    if to_phase is not None:
        cmd += ["--to-phase", str(to_phase)]
    # Scope -> run.py selection flags (mutually exclusive with --selected-layer). A
    # first-class scope wins over layer_filter; project scope selects nothing (full).
    scope = getattr(job, "scope", None)
    stype = (scope.get("type") if isinstance(scope, dict) else None) or "project"
    names = (scope.get("names") if isinstance(scope, dict) else None) or []
    if stype == "group" and names:
        cmd += ["--selected-group", str(names[0])]
    elif stype == "component" and names:
        cmd += ["--selected-component", str(names[0])]
    elif job.layer_filter:
        cmd += ["--selected-layer", job.layer_filter]
    if getattr(job, "no_llm", False):
        cmd.append("--no-llm-summarize")     # descriptions/behaviourNames disabled via config
    ddid = getattr(job, "data_dict_id", None)
    if ddid:
        dd_path = (get_settings().repo_root / "workspaces" / job.project_id
                   / "datadict" / f"{ddid}.csv")
        if dd_path.is_file():
            cmd += ["--data-dictionary", str(dd_path)]
    if getattr(job, "version_tag", None):
        cmd += ["--project-name", job.version_tag]
    # Extra include paths from architecture_layers.lib_paths (--include-path <layer> <abs_dir>)
    for layer in arch_layers:
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "").strip()
        if not lname:
            continue
        for lp in (layer.get("lib_paths") or []):
            lp = str(lp).strip()
            if lp:
                cmd += ["--include-path", lname, str(checkout_dir / lp)]
    cmd.append(str(checkout_dir))
    return cmd


# ---------------------------------------------------------------------------
# Incremental helpers
# ---------------------------------------------------------------------------

def _get_baseline_version_dir(project_id: str, reference_version_id: str) -> Optional[Path]:
    """Return the baseline version directory if its model snapshot is usable, else None.

    A snapshot is usable when model/hashes.json exists — that file is the entity-hash
    index produced by Phase 1 and needed for impact classification.
    """
    if not reference_version_id:
        return None
    root = get_settings().repo_root
    vdir = root / "workspaces" / project_id / "versions" / reference_version_id
    if (vdir / "model" / "hashes.json").is_file():
        return vdir
    return None


def _baseline_candidates(db: Any, project_id: str) -> list:
    """His DB versions, shaped for select_baseline and filtered to those with a usable
    captured snapshot (model/hashes.json) — the same gate as _get_baseline_version_dir."""
    root = get_settings().repo_root
    out: list = []
    try:
        versions = db.versions.list_for_project(project_id)
    except Exception:
        return out
    for v in versions:
        vdir = root / "workspaces" / project_id / "versions" / v.id
        if (vdir / "model" / "hashes.json").is_file():
            out.append({"versionId": v.id, "commit": getattr(v, "commit_sha", ""),
                        "branch": getattr(v, "branch", ""), "status": "complete"})
    return out


def _resolve_baseline(db: Any, job: Any, checkout_dir: Path) -> dict:
    """Decide the incremental baseline for this job, mirroring /generate's select_baseline.

      mode == "full"        -> always full (no baseline).
      reference_version_id  -> explicit override (still validated by select_baseline).
      otherwise (mode auto) -> nearest-ancestor completed version, or full when none.

    Runs in the worker (the repo is checked out by then). Returns
    {refVid, decision, baselineCommit, warnings}. Never raises — falls back to full."""
    mode = getattr(job, "mode", "auto") or "auto"
    explicit = getattr(job, "reference_version_id", None) or None
    if mode == "full":
        return {"refVid": "", "decision": "full", "baselineCommit": None, "warnings": []}

    import sys as _sys
    src_dir = str(get_settings().repo_root / "src")
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)
    try:
        from incremental import git_ops                      # type: ignore[import]
        from incremental.baseline import select_baseline     # type: ignore[import]

        target = git_ops.resolve(str(checkout_dir), job.commit_sha)
        if not target:
            return {"refVid": (explicit or ""),
                    "decision": ("incremental" if explicit else "full"),
                    "baselineCommit": None,
                    "warnings": ["target commit could not be resolved; baseline auto-select skipped"]}
        base = select_baseline(str(checkout_dir), _baseline_candidates(db, job.project_id),
                               target, explicit)
        decision = base.get("decision", "full")
        chosen = base.get("chosenBaseVersionId") if decision == "incremental" else None
        return {"refVid": (chosen or ""), "decision": decision,
                "baselineCommit": base.get("chosenBaseCommit"),
                "warnings": list(base.get("warnings") or [])}
    except Exception as exc:
        return {"refVid": (explicit or ""),
                "decision": ("incremental" if explicit else "full"),
                "baselineCommit": None,
                "warnings": [f"baseline auto-select failed ({exc})"]}


def _find_project_repo(project_id: str) -> Optional[Path]:
    """Newest existing per-commit checkout (a git repo) for the project, for read-only git
    queries (baseline preview). None when the project has never been generated."""
    base = get_settings().repo_root / "workspaces" / project_id
    if not base.is_dir():
        return None
    repos = [d for d in base.iterdir() if d.is_dir() and (d / ".git").is_dir()]
    return max(repos, key=lambda d: d.stat().st_mtime) if repos else None


def preview_baseline(db: Any, project_id: str, commit: str,
                     base_version_id: Optional[str] = None) -> dict:
    """Read-only baseline decision for `commit` (what an auto-mode job WOULD pick), using an
    existing project checkout for git ancestry. No checkout/clone, changes nothing — mirrors
    the standalone /generate/preview. Returns the select_baseline result, or a full-decision
    stub with a warning when no local history is available yet."""
    def _stub(warning: str) -> dict:
        return {"targetCommit": commit, "decision": "full",
                "chosenBaseVersionId": None, "chosenBaseCommit": None,
                "chosenIsAncestor": False, "chosenIsNearest": False,
                "changedFiles": None, "warnings": [warning]}

    import sys as _sys
    src_dir = str(get_settings().repo_root / "src")
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)
    try:
        from incremental import git_ops                      # type: ignore[import]
        from incremental.baseline import select_baseline     # type: ignore[import]
    except Exception as exc:
        return _stub(f"incremental engine unavailable ({exc})")

    repo = _find_project_repo(project_id)
    if not repo:
        return _stub("no local checkout yet — run one generation to enable incremental previews")
    target = git_ops.resolve(str(repo), commit)
    if not target:
        return _stub(f"commit {commit!r} not found in the local checkout")
    return select_baseline(str(repo), _baseline_candidates(db, project_id), target, base_version_id)


def _compute_incremental_plan(job_id: str, model_dir: Path, baseline_version_dir: Path) -> Optional[dict]:
    """Compute and write model/incremental_plan.json from the baseline version snapshot.

    Called between Phase 1 (which produced the fresh hashes/functions/edges) and Phase 2.
    Imports the incremental engine helpers from src/, classifies changed entities via
    the entity-hash diff, carries forward baseline LLM outputs (descriptions, behaviour
    names) for the reuse set so Phase 2 skips LLM for them, and writes the plan file
    that Phases 2–3 read to restrict enrichment and flowchart regeneration.
    """
    import json as _json
    import sys as _sys

    src_dir = str(get_settings().repo_root / "src")
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)

    from incremental.engine import (  # type: ignore[import]
        plan_incremental,
        carry_forward_descriptions,
        carry_forward_globals,
    )

    base_model_dir = baseline_version_dir / "model"

    def _read(d: Path, name: str) -> dict:
        p = d / name
        return _json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

    target_hashes    = _read(model_dir,      "hashes.json")
    target_functions = _read(model_dir,      "functions.json")
    target_edges     = _read(model_dir,      "edges.json")
    target_globals   = _read(model_dir,      "globalVariables.json")
    base_hashes      = _read(base_model_dir, "hashes.json")
    base_functions   = _read(base_model_dir, "functions.json")
    base_globals     = _read(base_model_dir, "globalVariables.json")

    if not base_hashes:
        _append_log(job_id, "Baseline hashes empty — incremental plan skipped (full enrichment).")
        return

    plan = plan_incremental(base_hashes, target_hashes, target_functions,
                            target_edges, base_functions)

    # Impacted globals = changed/new globals + globals read/written by impacted functions.
    cls = plan["classify"]
    impacted_globals: Set[str] = {k for k in (cls["changed"] | cls["new"]) if k.count("|") == 2}
    for fid in plan["impact"]:
        f = target_functions.get(fid) or {}
        impacted_globals.update(f.get("readsGlobalIds") or [])
        impacted_globals.update(f.get("writesGlobalIds") or [])
    impacted_globals &= set(target_globals)
    reused_globals = set(target_globals) - impacted_globals

    # Carry baseline LLM outputs into the reuse set so Phase 2 skips them.
    n_fn = carry_forward_descriptions(plan["reused"], target_functions, base_functions)
    carry_forward_globals(reused_globals, target_globals, base_globals)

    # M3.7 cross-version reuse (content-addressed across ALL prior versions): for any
    # IMPACT-set entity whose content fingerprint was already produced by a PRIOR version
    # (a revert, or code identical to another branch), copy that version's stored LLM
    # output instead of regenerating it. Catches reuse the parent->child baseline carry-
    # forward can't. The index is seeded after every run by _seed_reuse_index().
    index_reused: dict = {}
    index_reused_g: dict = {}
    _vstore = None
    try:
        from incremental.engine import (  # type: ignore[import]
            carry_forward_from_index, _CARRY_FIELDS)
        from incremental.fingerprint import compute_fingerprints  # type: ignore[import]
        from incremental.stores import Workspace, VersionStore, ReuseIndex  # type: ignore[import]

        _project_id = baseline_version_dir.parent.parent.name   # workspaces/<pid>/versions/<vid>
        _ws = Workspace(_project_id, workspaces_root=str(get_settings().repo_root / "workspaces"))
        _vstore = VersionStore(_ws)
        _ridx = ReuseIndex(_ws)
        _target_fps = compute_fingerprints(target_hashes, target_functions, target_edges)
        _fn_cache: dict = {}
        _gl_cache: dict = {}

        def _src_funcs(vid: str) -> dict:
            if vid not in _fn_cache:
                _fn_cache[vid] = _read(Path(_vstore.version_dir(vid)) / "model", "functions.json")
            return _fn_cache[vid]

        def _src_globs(vid: str) -> dict:
            if vid not in _gl_cache:
                _gl_cache[vid] = _read(Path(_vstore.version_dir(vid)) / "model", "globalVariables.json")
            return _gl_cache[vid]

        # current_version_id="" — the version being produced isn't in the index yet, so
        # there is no risk of a self-match here.
        index_reused = carry_forward_from_index(plan["impact"], _target_fps, target_functions,
                                                _ridx, "", _src_funcs, _CARRY_FIELDS)
        index_reused_g = carry_forward_from_index(impacted_globals, _target_fps, target_globals,
                                                  _ridx, "", _src_globs, ("description",))
    except Exception as exc:
        _append_log(job_id, f"Cross-version index reuse skipped ({exc}).")

    # Persist the mutated function/global data (carry-forwards baked in).
    (model_dir / "functions.json").write_text(
        _json.dumps(target_functions, indent=2), encoding="utf-8")
    (model_dir / "globalVariables.json").write_text(
        _json.dumps(target_globals, indent=2), encoding="utf-8")

    # Flowchart scoping: file-level = files of the full impact set; function-level = direct fids.
    impacted_files = sorted({
        (target_functions.get(fid) or {}).get("location", {}).get("file")
        for fid in plan["impact"]
    } - {None})
    direct_fns = {k for k in (cls["changed"] | cls["new"]) if k in target_functions}
    flowchart_files: Set[str] = {
        (target_functions.get(fid) or {}).get("location", {}).get("file")
        for fid in direct_fns
    }
    for fid in cls["deleted"]:
        bf = base_functions.get(fid)
        if bf:
            flowchart_files.add((bf.get("location") or {}).get("file"))

    # A directly-changed fn reused from the index (revert / cross-branch-identical) has the
    # SAME flowchart as its source version, so the view splices it in instead of regenerating.
    xver_flowcharts = ({fid: str(_vstore.version_dir(index_reused[fid]))
                        for fid in direct_fns if fid in index_reused}
                       if _vstore else {})
    # Index-satisfied entities drop out of the regen sets (Phase 2 skips them — they now
    # carry descriptions/behaviour) and out of flowchart regen (spliced via crossVersionFlowcharts).
    inc_plan = {
        "impactFids":             sorted(set(plan["impact"]) - set(index_reused)),
        "impactedGlobals":        sorted(impacted_globals - set(index_reused_g)),
        "impactedFiles":          impacted_files,
        "flowchartFiles":         sorted(flowchart_files - {None}),
        "flowchartFids":          sorted(direct_fns - set(xver_flowcharts)),
        "crossVersionFlowcharts": xver_flowcharts,
        "baselineVersionDir":     str(baseline_version_dir),
    }
    (model_dir / "incremental_plan.json").write_text(
        _json.dumps(inc_plan, indent=2), encoding="utf-8")

    _append_log(job_id,
                f"Incremental plan: {len(plan['reused'])} reused + {len(index_reused)} via "
                f"cross-version index, {len(inc_plan['impactFids'])} to regenerate "
                f"({n_fn} descriptions carried).")
    return {"reused": len(plan["reused"]) + len(index_reused),
            "regenerated": len(inc_plan["impactFids"])}


def _store_incremental_counts(db: Any, job_id: str, counts: Optional[dict]) -> None:
    """Persist the incremental accounting (regenerated/reused) onto the job so _make_version
    can surface it on the resulting Version."""
    if not counts:
        return
    job = db.jobs.get(job_id)
    if job:
        job.regenerated = counts.get("regenerated")
        job.reused = counts.get("reused")
        db.jobs.update(job)


def _try_narrowed_parse_pipeline(db: Any, job_id: str, checkout_dir: Path, config_path: Path,
                                 baseline_version_dir: Path, model_dir: Path,
                                 arch_layers: list = ()) -> bool:
    """M4.4 narrowed parse: re-parse ONLY the affected TUs (run.py --only-files) and merge
    them into the baseline's parser-level snapshot (versions/<base>/model/), so model/ ends
    up the same blank skeleton a full parse would produce. Returns True if model/ now holds
    the merged skeleton; False to fall back to a full Phase-1 parse (always the safe choice).
    Reuses the engine's pure merge helpers — the merge is verified byte-equal to a full parse."""
    import sys as _sys
    src_dir = str(get_settings().repo_root / "src")
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)
    try:
        from incremental import git_ops                                         # type: ignore[import]
        from incremental.affected import affected_tus, full_reparse_reason      # type: ignore[import]
        from incremental.parse_merge import merge_model                         # type: ignore[import]
        from incremental.engine import _load_parse_dir, _write_parse_artifacts  # type: ignore[import]
    except Exception as exc:
        _append_log(job_id, f"narrowed parse unavailable ({exc}) — full parse")
        return False

    base_parse = baseline_version_dir / "model"
    if not (base_parse / "tu_includes.json").is_file() or not (base_parse / "entity_files.json").is_file():
        _append_log(job_id, "narrowed parse unavailable: baseline has no parser snapshot — full parse")
        return False

    job = db.jobs.get(job_id)
    base_commit = getattr(job, "baseline_commit", None)
    if not base_commit:
        _append_log(job_id, "narrowed parse: baseline commit unknown — full parse")
        return False

    try:
        tu_includes = json.loads((base_parse / "tu_includes.json").read_text(encoding="utf-8"))
        status = git_ops.changed_files_status(str(checkout_dir), base_commit, job.commit_sha)
    except Exception as exc:
        _append_log(job_id, f"narrowed parse: diff failed ({exc}) — full parse")
        return False

    reason = full_reparse_reason(status, tu_includes)
    if reason:
        _append_log(job_id, f"narrowed parse skipped ({reason}) — full parse")
        return False

    changed = [p for _s, p in status]
    affected = affected_tus(changed, tu_includes)
    deleted = {p for s, p in status if s == "D"}
    base_model = _load_parse_dir(str(base_parse))
    model_dir.mkdir(parents=True, exist_ok=True)

    if not affected:                       # nothing to re-parse -> merged skeleton == baseline
        _write_parse_artifacts(str(model_dir), base_model)
        _append_log(job_id, "narrowed parse: 0 affected TU(s) — reused the baseline skeleton")
        return True

    listfile = model_dir / ".affected_tus.txt"
    listfile.write_text("\n".join(sorted(affected)) + "\n", encoding="utf-8")
    # Hand the partial parse the baseline's func-key map so calls into UN-parsed files still
    # resolve to edges (inherited by the run.py -> parser.py subprocess via env).
    bfk = base_parse / "func_keys.json"
    prev_bfk = os.environ.get("ANALYZER_BASELINE_FUNCKEYS")
    if bfk.is_file():
        os.environ["ANALYZER_BASELINE_FUNCKEYS"] = str(bfk)
    try:
        cmd = _build_cmd(job, checkout_dir, config_path, to_phase=1, arch_layers=arch_layers)
        cmd += ["--only-files", str(listfile)]
        ok = _execute_subprocess(db, job_id, cmd, phase_start=1)
    finally:
        if prev_bfk is None:
            os.environ.pop("ANALYZER_BASELINE_FUNCKEYS", None)
        else:
            os.environ["ANALYZER_BASELINE_FUNCKEYS"] = prev_bfk
    if not ok:
        _append_log(job_id, "narrowed parse: partial parse failed — full parse")
        return False

    partial = _load_parse_dir(str(model_dir))
    # Parse-fingerprint gate: if clang flags / std / toolchain changed since the baseline was
    # parsed, the baseline skeleton was built differently and a merge would be unsound.
    base_fp = (base_model.get("metadata") or {}).get("parseFingerprint")
    part_fp = (partial.get("metadata") or {}).get("parseFingerprint")
    if base_fp and part_fp and base_fp != part_fp:
        _append_log(job_id, "narrowed parse: parse fingerprint changed (clang flags / std / toolchain) — full parse")
        return False

    drop = set(affected) | set(changed) | deleted
    merged = merge_model(base_model, partial, drop)
    _write_parse_artifacts(str(model_dir), merged)
    _append_log(job_id, f"narrowed parse: re-parsed {len(affected)} affected TU(s), merged into the "
                        f"baseline skeleton ({len(merged.get('functions') or {})} functions total)")
    return True


# ---------------------------------------------------------------------------
# Run strategies
# ---------------------------------------------------------------------------

def _run_full(db: Any, job_id: str, checkout_dir: Path, config_path: Path,
              arch_layers: list = ()) -> None:
    job = db.jobs.get(job_id)
    cmd = _build_cmd(job, checkout_dir, config_path, arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd, phase_start=1)
    if ok:
        _complete(db, job_id)


def _run_with_pause(db: Any, job_id: str, checkout_dir: Path, config_path: Path,
                    arch_layers: list = ()) -> None:
    job = db.jobs.get(job_id)
    # Phase 1+2 only
    cmd = _build_cmd(job, checkout_dir, config_path, to_phase=2, arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd, phase_start=1)
    if not ok or _is_cancelled(db, job_id):
        return

    # Pause
    job = db.jobs.get(job_id)
    job.status = "paused"
    job.current_activity = "Paused after Phase 2 — review functions, then resume."
    db.jobs.update(job)
    _append_log(job_id, "Paused. Resume to run Phases 3–4.")

    # Wait for resume signal or cancel
    ev = None
    with _LOCK:
        ev = _job_resume_events.get(job_id)
    while ev and not ev.is_set():
        ev.wait(timeout=2.0)
        if _is_cancelled(db, job_id):
            return

    if _is_cancelled(db, job_id):
        return

    # Phase 3+4
    job = db.jobs.get(job_id)
    if not job or job.status == "cancelled":
        return
    job.status = "running"
    job.current_activity = _ACTIVITY[3]
    db.jobs.update(job)
    _append_log(job_id, "Resuming from Phase 3…")

    job = db.jobs.get(job_id)
    cmd = _build_cmd(job, checkout_dir, config_path, from_phase=3, use_model=True,
                     arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd, phase_start=3)
    if ok:
        _complete(db, job_id)


def _run_incremental(db: Any, job_id: str, checkout_dir: Path, config_path: Path,
                     baseline_version_dir: Path, arch_layers: list = ()) -> None:
    """Incremental run: Phase 1 → compute impact plan → Phase 2–4.

    Phase 1 produces fresh hashes/edges.  The in-process plan computation diffs them
    against the baseline, carries forward LLM outputs for unchanged entities, and writes
    model/incremental_plan.json.  Phases 2–4 then read the plan to restrict LLM
    enrichment (Phase 2) and flowchart generation (Phase 3).
    """
    job = db.jobs.get(job_id)
    model_dir = get_settings().repo_root / "model"

    # Phase 1 only (parse → hashes.json, functions.json, edges.json, …)
    used_narrowed = False
    if getattr(job, "narrowed_parse", False):
        used_narrowed = _try_narrowed_parse_pipeline(
            db, job_id, checkout_dir, config_path, baseline_version_dir, model_dir, arch_layers)
        if _is_cancelled(db, job_id):
            return
    if not used_narrowed:
        cmd1 = _build_cmd(job, checkout_dir, config_path, to_phase=1, arch_layers=arch_layers)
        ok = _execute_subprocess(db, job_id, cmd1, phase_start=1)
        if not ok or _is_cancelled(db, job_id):
            return

    # Impact classification + carry-forward → incremental_plan.json
    _append_log(job_id, "Computing incremental plan from baseline snapshot…")
    try:
        _store_incremental_counts(db, job_id, _compute_incremental_plan(job_id, model_dir, baseline_version_dir))
    except Exception as exc:
        _append_log(job_id, f"Incremental plan error ({exc}) — Phase 2+ runs with full enrichment.")

    # Phase 2–4 (model_deriver reads plan to restrict LLM; flowcharts view reads plan for reuse)
    job = db.jobs.get(job_id)
    cmd2 = _build_cmd(job, checkout_dir, config_path, from_phase=2, arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd2, phase_start=2)
    if ok:
        _complete(db, job_id)


def _run_incremental_with_pause(db: Any, job_id: str, checkout_dir: Path, config_path: Path,
                                 baseline_version_dir: Path, arch_layers: list = ()) -> None:
    """Incremental run with a pause after Phase 2 for function-visibility review."""
    job = db.jobs.get(job_id)
    model_dir = get_settings().repo_root / "model"

    # Phase 1 only
    used_narrowed = False
    if getattr(job, "narrowed_parse", False):
        used_narrowed = _try_narrowed_parse_pipeline(
            db, job_id, checkout_dir, config_path, baseline_version_dir, model_dir, arch_layers)
        if _is_cancelled(db, job_id):
            return
    if not used_narrowed:
        cmd1 = _build_cmd(job, checkout_dir, config_path, to_phase=1, arch_layers=arch_layers)
        ok = _execute_subprocess(db, job_id, cmd1, phase_start=1)
        if not ok or _is_cancelled(db, job_id):
            return

    # Impact classification + carry-forward → incremental_plan.json
    _append_log(job_id, "Computing incremental plan from baseline snapshot…")
    try:
        _store_incremental_counts(db, job_id, _compute_incremental_plan(job_id, model_dir, baseline_version_dir))
    except Exception as exc:
        _append_log(job_id, f"Incremental plan error ({exc}) — Phase 2 runs with full enrichment.")

    # Phase 2 only (model derivation; LLM enrichment gated by the plan)
    job = db.jobs.get(job_id)
    cmd2 = _build_cmd(job, checkout_dir, config_path, from_phase=2, to_phase=2, arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd2, phase_start=2)
    if not ok or _is_cancelled(db, job_id):
        return

    # Pause — user reviews function visibility
    job = db.jobs.get(job_id)
    job.status = "paused"
    job.current_activity = "Paused after Phase 2 — review functions, then resume."
    db.jobs.update(job)
    _append_log(job_id, "Paused. Resume to run Phases 3–4.")

    ev = None
    with _LOCK:
        ev = _job_resume_events.get(job_id)
    while ev and not ev.is_set():
        ev.wait(timeout=2.0)
        if _is_cancelled(db, job_id):
            return

    if _is_cancelled(db, job_id):
        return

    # Phase 3–4 (incremental_plan.json still present → flowchart reuse active)
    job = db.jobs.get(job_id)
    if not job or job.status == "cancelled":
        return
    job.status = "running"
    job.current_activity = _ACTIVITY[3]
    db.jobs.update(job)
    _append_log(job_id, "Resuming from Phase 3…")

    job = db.jobs.get(job_id)
    cmd3 = _build_cmd(job, checkout_dir, config_path, from_phase=3, use_model=True,
                      arch_layers=arch_layers)
    ok = _execute_subprocess(db, job_id, cmd3, phase_start=3)
    if ok:
        _complete(db, job_id)


# ---------------------------------------------------------------------------
# Subprocess execution + output tailing
# ---------------------------------------------------------------------------

def _execute_subprocess(
    db: Any,
    job_id: str,
    cmd: list[str],
    phase_start: int = 1,
) -> bool:
    """Run cmd, tail its output, update job progress. Returns True on success."""
    cfg = get_settings()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if cfg.libclang_path:
        env["LIBCLANG_PATH"] = cfg.libclang_path

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cfg.repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except Exception as exc:
        _mark_failed(db, job_id, f"Failed to start run.py: {exc}")
        return False

    with _LOCK:
        _job_procs[job_id] = proc

    current_phase = phase_start
    phase_start_time = _now()
    recent_lines: list[str] = []
    line_count = 0
    _timeout = get_settings().subprocess_timeout or None
    _timed_out = False

    # Mark the first phase of this subprocess as "running" immediately.
    # Without this, phase_start stays "pending" until the *next* phase fires
    # _transition_phase — meaning phase 1 (and phase 3 on a resume) would
    # skip "running" entirely and jump from "pending" to "done".
    job = db.jobs.get(job_id)
    if job:
        for p in job.phases:
            if p.number == phase_start:
                p.status = "running"
        job.phase = phase_start
        db.jobs.update(job)

    try:
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n\r")
            if not line:
                continue

            _append_log(job_id, line)
            recent_lines.append(line)
            if len(recent_lines) > 80:
                recent_lines.pop(0)
            line_count += 1

            # Cancel check (every 20 lines to keep overhead low)
            if line_count % 20 == 0 and _is_cancelled(db, job_id):
                try:
                    proc.terminate()
                except OSError:
                    pass
                return False

            # Phase transition detection
            new_phase = _detect_phase(line, current_phase)
            if new_phase != current_phase:
                _transition_phase(db, job_id, current_phase, new_phase, phase_start_time)
                current_phase = new_phase
                phase_start_time = _now()

            # Update activity detail from log content (strip log prefix)
            detail = _strip_log_prefix(line)
            if detail and len(detail) > 10:
                _update_activity(db, job_id, detail[:120])

    finally:
        try:
            proc.wait(timeout=_timeout)
        except subprocess.TimeoutExpired:
            _timed_out = True
            try:
                proc.terminate()
            except OSError:
                pass
            proc.wait()

    if _timed_out:
        _append_log(job_id,f"Job failed after timing out {_timeout}s")
        _mark_failed(db, job_id, f"Subprocess timed out after {_timeout}s.")
        return False

    with _LOCK:
        _job_procs.pop(job_id, None)

    rc = proc.returncode
    if _is_cancelled(db, job_id):
        return False

    if rc != 0:
        tail = "\n".join(recent_lines[-20:])
        _append_log(job_id,f"Job failed with code{rc}")
        _mark_failed(db, job_id, f"run.py exited with code {rc}.\n{tail}")
        return False

    # Mark the final phase done
    job = db.jobs.get(job_id)
    if job:
        for p in job.phases:
            if p.number == current_phase and p.status != "done":
                p.status = "done"
                p.duration_seconds = max(1, int((_now() - phase_start_time).total_seconds()))
        db.jobs.update(job)

    return True


def _detect_phase(line: str, current_phase: int) -> int:
    """Detect a phase start marker in a log line. Only advances forward."""
    if "===" not in line:
        return current_phase
    for n in range(current_phase + 1, 5):
        if _PHASE_MARKERS[n] in line:
            return n
    return current_phase


def _strip_log_prefix(line: str) -> str:
    """Strip [HH:MM:SS] LEVEL name: prefix, return the message part."""
    import re
    m = re.match(r"^\[[\d:]+\]\s+\w+\s+\S+:\s+(.*)", line)
    return m.group(1).strip() if m else line.strip()


def _transition_phase(db: Any, job_id: str, old_phase: int, new_phase: int,
                       old_phase_start: datetime) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return
    elapsed = max(1, int((_now() - old_phase_start).total_seconds()))
    for p in job.phases:
        if p.number == old_phase:
            p.status = "done"
            p.duration_seconds = elapsed
        elif p.number == new_phase:
            p.status = "running"
    job.phase = new_phase
    job.phase_pct = 0
    job.current_activity = _ACTIVITY.get(new_phase, f"Phase {new_phase}…")
    job.elapsed_seconds = int((_now() - job.started_at).total_seconds())
    job.eta_seconds = max(0, (4 - new_phase) * 120)
    db.jobs.update(job)
    _append_log(job_id, f"→ Phase {new_phase}: {_ACTIVITY.get(new_phase, '')}")


def _update_activity(db: Any, job_id: str, detail: str) -> None:
    job = db.jobs.get(job_id)
    if job:
        job.activity_detail = detail
        job.elapsed_seconds = int((_now() - job.started_at).total_seconds())
        db.jobs.update(job)


def _is_cancelled(db: Any, job_id: str) -> bool:
    job = db.jobs.get(job_id)
    return not job or job.status == "cancelled"


# ---------------------------------------------------------------------------
# Version snapshot — capture model/ + output/ for the compare engine (M3)
# ---------------------------------------------------------------------------

def _capture_version_snapshot(project_id: str, version_id: str) -> None:
    """Copy current model/ and output/ into workspaces/<project_id>/versions/<version_id>/
    so the compare engine can diff two versions without re-running the pipeline."""
    root = get_settings().repo_root
    vdir = root / "workspaces" / project_id / "versions" / version_id
    try:
        vdir.mkdir(parents=True, exist_ok=True)
        for dirname in ("model", "output"):
            src = root / dirname
            dst = vdir / dirname
            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
    except Exception:
        pass  # snapshot is best-effort; failures must not break the job


def _seed_reuse_index(project_id: str, version_id: str) -> None:
    """Seed the content-addressed reuse index from a just-captured version's model, so a
    later incremental run can reuse THIS version's LLM outputs across branches/reverts
    (M3.7). Best-effort; covers full + incremental (called from _complete for every run)."""
    import sys as _sys
    src_dir = str(get_settings().repo_root / "src")
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)
    try:
        from incremental.fingerprint import compute_fingerprints  # type: ignore[import]
        from incremental.stores import Workspace, VersionStore, ReuseIndex  # type: ignore[import]

        ws = Workspace(project_id, workspaces_root=str(get_settings().repo_root / "workspaces"))
        vmodel = Path(VersionStore(ws).version_dir(version_id)) / "model"

        def _r(name: str) -> dict:
            p = vmodel / name
            return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}

        fps = compute_fingerprints(_r("hashes.json"), _r("functions.json"), _r("edges.json"))
        if not fps:
            return
        ridx = ReuseIndex(ws)
        for entity_key, fp in fps.items():
            ridx.put(fp, version_id, entity_key)   # first version to produce a fp keeps it
        ridx.save()
    except Exception:
        pass  # best-effort — reuse-index seeding must never break a completed job


# ---------------------------------------------------------------------------
# Completion — register Version + Documents
# ---------------------------------------------------------------------------

def _commit_dir(project_id: str, commit_sha: str) -> Path:
    """The per-commit version dir workspaces/<pid>/<commit[:16]> — the git checkout PLUS the
    model/ output/ manifest the incremental engine writes for that commit (== version)."""
    return get_settings().repo_root / "workspaces" / project_id / (commit_sha or "")[:16]


def _read_engine_manifest(project_id: str, commit_sha: str) -> dict:
    """Read the engine's manifest.json from the commit dir (decision / baselineVersionId /
    regenerated / reused / documents). Returns {} when absent."""
    p = _commit_dir(project_id, commit_sha) / "manifest.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def _complete(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if not job or job.status in ("cancelled", "failed"):
        return

    now = _now()
    project = db.projects.get(job.project_id)
    # The engine wrote model/output + manifest INTO the commit dir and seeded the reuse index
    # itself — read the manifest for the incremental accounting; no separate capture/seed.
    manifest = _read_engine_manifest(job.project_id, job.commit_sha)

    version = _make_version(db, project, job, now, manifest)
    docs = _make_documents(db, project, version, now)
    _make_sections(db, docs, now, _commit_dir(job.project_id, job.commit_sha) / "output")
    version.docs_count = len(docs)
    db.versions.update(version)

    _load_and_register_functions(db, job, version.id)

    job.status = "complete"
    job.phase = 4
    job.phase_pct = 100
    job.current_activity = "Done"
    job.activity_detail = f"{len(docs)} document(s) generated"
    job.eta_seconds = 0
    job.completed_at = now
    job.version_id = version.id
    job.elapsed_seconds = int((now - job.started_at).total_seconds())
    for p in job.phases:
        p.status = "done"
    db.jobs.update(job)

    if project:
        project.status = "in_review"
        project.updated_at = now
        db.projects.update(project)

    _append_log(job_id, f"Complete. Version {version.tag}, {len(docs)} document(s).")


def _make_sections(db: Any, docs: list, now: datetime, output_dir: Path) -> None:
    """Seed DocumentSection records for every document created by _make_documents.
    `output_dir` is the version's commit-dir output (workspaces/<pid>/<commit[:16]>/output)."""
    from ..models.domain import DocumentSection


    for doc in docs:
        existing = db.documents.list_sections(doc.id)
        if existing:
            continue  # already has sections (e.g. re-export of an existing doc)

        if doc.process in ("SYS.2", "SWE.1"):
            sections = [
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="intro", title="1. Introduction", order=1,
                    content=f"This document captures the {doc.subtitle} for {doc.name}.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
            ]
        else:
            # SWE.2 / SWE.3 — read unit count from interface_tables.json
            n_units, n_comps = 0, 1
            group_dir = output_dir / doc.group if doc.group else None
            if group_dir and group_dir.is_dir():
                itf_path = group_dir / "interface_tables.json"
                if itf_path.exists():
                    try:
                        itf = json.loads(itf_path.read_text(encoding="utf-8"))
                        unit_names = itf.get("unitNames", {}) or {}
                        n_units = len(unit_names)
                        comps: dict = {}
                        for uk in unit_names:
                            comps.setdefault(uk.split("|", 1)[0], []).append(uk)
                        n_comps = max(len(comps), 1)
                    except Exception:
                        pass

            sections = [
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="intro", title="1. Introduction", order=1,
                    content=(
                        f"This {doc.subtitle} describes the '{doc.name}' software component, "
                        f"covering {n_units} unit(s) across {n_comps} component(s). "
                        f"Interfaces, static structure and control-flow are derived from "
                        f"the Clang AST analysis."
                    ),
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="interfaces", title="2. Interfaces", order=2,
                    content="Interface table derived from the pipeline analysis.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="static_design", title="3. Static Design", order=3,
                    content="Component structure and include-dependency graph derived from Clang AST.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
                DocumentSection(
                    id=f"sec{uuid.uuid4().hex[:8]}", document_id=doc.id,
                    section_key="dynamic_design", title="4. Dynamic Design", order=4,
                    content="Control-flow graphs (CFGs) for each function, derived from the Clang AST.",
                    review_state=None, reviewed_by=None, reviewed_at=None,
                ),
            ]

        for sec in sections:
            db.documents.update_section(sec)


def _make_version(db: Any, project: Any, job: Any, now: datetime, manifest: dict = None) -> Version:
    manifest = manifest or {}
    existing = db.versions.list_for_project(project.id) if project else []
    taken = {v.tag for v in existing}
    tag = (getattr(job, "version_tag", None) or "").strip() or f"v0.{len(existing) + 1}.0"
    base, i = tag, 1
    while tag in taken:
        tag = f"{base}-{i}"
        i += 1
    version = Version(
        id=f"ver{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        tag=tag,
        commit_sha=job.commit_sha,
        branch=job.branch,
        description="Generated by analysis run",
        status="in_review",
        docs_count=0,
        created_by=(project.created_by if project else "system"),
        created_at=now,
        # Incremental accounting comes from the engine's manifest (baselineVersionId is the
        # baseline commit[:16]; resolvable by compare as a commit-sha prefix).
        baseline_version_id=manifest.get("baselineVersionId"),
        decision=manifest.get("decision") or getattr(job, "decision", None),
        regenerated=manifest.get("regenerated"),
        reused=manifest.get("reused"),
    )
    db.versions.create(version)
    return version


def _make_documents(db: Any, project: Any, version: Version, now: datetime) -> list[Document]:
    """Create Documents by scanning real output/ dirs, falling back to architecture walk."""
    docs: list[Document] = []

    def add(process: str, name: str, subtitle: str, layer: str, group: str) -> None:
        doc = Document(
            id=f"doc{uuid.uuid4().hex[:8]}",
            project_id=project.id,
            version_id=version.id,
            process=process, name=name, subtitle=subtitle,
            layer=layer, group=group, status="in_review",
            due_date=None, created_at=now, updated_at=now,
        )
        db.documents.update(doc)
        docs.append(doc)

    add("SYS.2", "System Requirements", "SyRS", "", "Global")
    add("SWE.1", "Software Requirements", "SRS", "", "Global")

    # Collect allowed groups from the project's architecture_layers so we don't
    # pick up stale output dirs from previous pipeline runs for other projects.
    allowed_groups: set[str] = set()
    for _layer in (project.architecture_layers or []):
        if not isinstance(_layer, dict):
            continue
        for _g in (_layer.get("groups") or []):
            _gn = _g if isinstance(_g, str) else (str(_g.get("name") or "") if isinstance(_g, dict) else "")
            if _gn:
                allowed_groups.add(_gn)

    # The pipeline normalises group names to filesystem-safe dir names (spaces → hyphens).
    # Build a matching set so we can compare against actual output/ subdirectory names.
    allowed_dirs: set[str] = {g.replace(" ", "-") for g in allowed_groups}

    # Real output/ dirs — add one SWE.2 per group directory found that is also
    # declared in the project configuration (guards against stale dirs from prior runs).
    output_dir = _commit_dir(version.project_id, version.commit_sha) / "output"
    groups_found: list[str] = []
    if output_dir.is_dir():
        all_dirs = [d.name for d in sorted(output_dir.iterdir()) if d.is_dir()]
        groups_found = [d for d in all_dirs if not allowed_dirs or d in allowed_dirs]
        for gname in groups_found:
            add("SWE.2", gname, "Component Design", "", gname)

    # groups_found contains actual output dir names (e.g. "My-Sample").
    # When a group already has a real pipeline output dir, it produces one
    # consolidated document covering all its units — so skip per-unit SWE.3
    # docs for that group to avoid duplicating what is already inside it.
    groups_found_dirs: set[str] = set(groups_found)

    # Walk architecture_layers: add SWE.2 only when no output dirs found (fallback),
    # and add SWE.3 unit design docs only for groups that have no output coverage.
    unit_count = 0
    for layer in (project.architecture_layers or []):
        if not isinstance(layer, dict):
            continue
        lname = str(layer.get("name") or "")
        for g in (layer.get("groups") or []):
            gname = g if isinstance(g, str) else (str(g.get("name") or "") if isinstance(g, dict) else "")
            if not gname:
                continue
            if not groups_found:
                add("SWE.2", gname, "Component Design", lname, gname)
            # Skip unit-level docs when the group's output dir was produced by the
            # pipeline — those units are already sections inside the group document.
            gname_dir = gname.replace(" ", "-")
            if gname_dir in groups_found_dirs:
                continue
            comps = [] if isinstance(g, str) else (g.get("components", []) or [])
            for c in comps:
                cname = c if isinstance(c, str) else (c.get("name", "") if isinstance(c, dict) else "")
                if cname and unit_count < 24:
                    add("SWE.3", str(cname), "Unit Design", lname, gname)
                    unit_count += 1

    if unit_count == 0 and len(docs) <= 2:
        add("SWE.3", "Main Module", "Unit Design", "", "Global")
    return docs


# ---------------------------------------------------------------------------
# Functions loader — reads model/functions.json and registers under the job
# ---------------------------------------------------------------------------

def _baseline_fn_keys(project_id: str, reference_commit: str) -> Optional[Set[str]]:
    """Return the set of function dict-keys from the baseline commit's model, or None."""
    path = _commit_dir(project_id, reference_commit) / "model" / "functions.json"
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
        return set(raw.keys()) if isinstance(raw, dict) else None
    except Exception:
        return None


def _load_and_register_functions(db: Any, job: Any, version_id: str) -> None:
    """Read model/functions.json and register functions in the DB under the job's id."""
    from ..models.domain import Function

    path = _commit_dir(job.project_id, job.commit_sha) / "model" / "functions.json"
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return
    if not isinstance(raw, dict):
        return

    ref_keys: Optional[Set[str]] = None
    if getattr(job, "reference_version_id", None):
        ref_keys = _baseline_fn_keys(job.project_id, job.reference_version_id)

    functions: list[Function] = []
    for fn_key, fn_data in raw.items():
        if not isinstance(fn_data, dict):
            continue
        fn_name = fn_data.get("name") or fn_key.split("::")[-1]
        file_path = fn_data.get("file", fn_data.get("filePath", ""))
        layer = fn_data.get("layer", fn_data.get("layerName", ""))
        group = fn_data.get("componentName", fn_data.get("group", ""))
        description = fn_data.get("description", "")
        is_visible = bool(fn_data.get("isVisible", fn_data.get("is_visible", True)))
        fn_id = fn_data.get("id") or str(uuid.uuid4())
        is_new = (fn_key not in ref_keys) if ref_keys is not None else False

        functions.append(Function(
            id=fn_id,
            project_id=job.project_id,
            version_id=version_id,
            name=fn_name,
            file_path=file_path,
            layer=layer,
            group=group,
            is_visible=is_visible,
            is_new=is_new,
            description=description,
        ))

    if hasattr(db.functions, "load_from_pipeline"):
        db.functions.load_from_pipeline({job.id: functions})


# ---------------------------------------------------------------------------
# Re-export
# ---------------------------------------------------------------------------

def _do_reexport(db: Any, job_id: str) -> None:
    job = db.jobs.get(job_id)
    if not job:
        return
    project = db.projects.get(job.project_id)
    if not project:
        return

    root = get_settings().repo_root
    checkout_dir = root / "workspaces" / job.project_id / job.commit_sha[:16]
    if not checkout_dir.is_dir():
        _mark_failed(db, job_id, "Checkout not found — run the full analysis first.")
        return

    workspace_dir = root / "workspaces" / job.project_id
    config_path = workspace_dir / "config.json"
    if not config_path.is_file():
        try:
            config_path = _write_project_config(project, workspace_dir)
        except Exception as exc:
            _mark_failed(db, job_id, f"Config generation failed: {exc}")
            return

    arch_layers = project.architecture_layers or []
    cmd = _build_cmd(job, checkout_dir, config_path, from_phase=4, use_model=True,
                     arch_layers=arch_layers)
    _execute_subprocess(db, job_id, cmd, phase_start=4)
