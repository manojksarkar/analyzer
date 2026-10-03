"""Staged generation: the decisions behind `export`, `reexport`, `resume` and `progress`.

A version's model (Phases 1-2) covers whole layers; its documents (Phases 3-4) are made per
component, by any number of runs into the same version:

    generate   Phases 1-4             a new version (or `--model-only`: Phases 1-2)
    export     Phases 3-4             components NOT generated yet, of the layers it parsed
    reexport   Phases 3-4 (or 2/4)    components ALREADY generated, again
    resume     from where it stopped  a run that was cut short

Everything here is pure -- it takes the component view (`api/services/version_components.py`)
and the run record (`core/version_run.py`) and returns what to do or what to print -- so the
rules are tested without a database. `analyzer.py` does the I/O.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

NOT_GENERATED = ("waiting", "stopped", "failed", "not_requested")
UNFINISHED = ("waiting", "stopped", "failed", "generating")
DOC_STATUS = {"in_review": "In review", "submitted": "Ready for approval",
              "changes_requested": "Changes requested", "approved": "Approved"}
STATE_LABEL = {"generated": "generated", "generating": "generating", "waiting": "waiting",
               "stopped": "stopped", "failed": "failed", "not_requested": "not requested"}


# ---------------------------------------------------------------------------
# Which components a command makes
# ---------------------------------------------------------------------------

def _by_id(view: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {c["component"]: c for c in view}


def has_documents(c: Dict[str, Any]) -> bool:
    """Generated, or has documents whatever its last run recorded: a re-export that died leaves
    its components "stopped" or "failed" although their documents are there."""
    return c["state"] == "generated" or bool(c.get("documents"))


def export_targets(view: List[Dict[str, Any]], found: List[str], *,
                   remaining: bool) -> Tuple[List[str], List[str]]:
    """(to make, skipped as already generated). `found` are resolved component ids; `remaining`
    takes every component of the parsed layers that has no documents yet instead."""
    comps = _by_id(view)
    if remaining:
        return [c["component"] for c in view
                if c["in_model"] and c["state"] in NOT_GENERATED and not has_documents(c)], []
    todo, skipped = [], []
    for cid in found:
        c = comps.get(cid)
        if c is None or not c["in_model"]:
            continue
        (skipped if has_documents(c) or c["state"] == "generating" else todo).append(cid)
    return todo, skipped


def reexport_targets(view: List[Dict[str, Any]], found: List[str]) -> Tuple[List[str], List[str]]:
    """(to make again, refused as never generated)."""
    comps = _by_id(view)
    todo, refused = [], []
    for cid in found:
        c = comps.get(cid)
        (todo if c is not None and has_documents(c) else refused).append(cid)
    return todo, refused


def default_reexport(view: List[Dict[str, Any]]) -> List[str]:
    """`reexport` with no components: every component the version has documents for -- what the
    web app's re-export does. Empty when the documents are not per component (an old group-scoped
    version); the caller then falls back to the scope the version was generated with."""
    return [c["component"] for c in view if has_documents(c) and c["in_model"]]


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def resume_plan(*, alive: Optional[bool], pipeline_status: Optional[str],
                view: List[Dict[str, Any]], run: Optional[Dict[str, Any]],
                parse_stored: bool = False, model_only: bool = False) -> Dict[str, Any]:
    """What `resume` does, first rule that applies:

    busy        a writer still holds the version -- it is not cut short
    regenerate  Phase 1 did not finish (no stored parse): run the recorded `generate` again (the
                LLM work already paid is in the cache; the parse is not)
    derive      the parse is stored, the model is not (Phase 2 was killed OR failed): Phase 2 from
                the stored parse, then Phases 3-4 for the components the run asked for -- or, for a
                `--model-only` run, Phase 2 alone (`to_phase: 2`)
    export      the model is complete: Phases 3-4 for the components the run asked for and did
                not finish
    close       every requested component is generated, but the run died before closing the
                version: only the closing steps
    nothing     the version is complete; nothing was cut short
    """
    if alive:
        return {"action": "busy"}
    has_model = any(c["in_model"] for c in view)
    todo = [c["component"] for c in view if c["state"] in UNFINISHED]
    argv = list((run or {}).get("argv") or []) if (run or {}).get("command") == "generate" else []
    if not has_model:
        if parse_stored or pipeline_status == "deriving":
            # The manifest says so even after a resume of it was cut short in turn (the run
            # row then holds the resume, not the generate's command line).
            if model_only or "--model-only" in argv:
                return {"action": "derive", "components": [], "to_phase": 2}
            return {"action": "derive", "components": todo}
        return {"action": "regenerate", "argv": [a for a in argv if a != "--detach"]}
    todo = [c["component"] for c in view if c["in_model"] and c["state"] in UNFINISHED]
    if todo:
        return {"action": "export", "components": todo}
    if pipeline_status not in (None, "complete"):
        return {"action": "close"}
    return {"action": "nothing"}


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _aware(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.datetime.fromisoformat(dt)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "?"
    s = int(max(0, seconds))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d} d {h} h"
    if h:
        return f"{h} h {m} min"
    return f"{m} min" if m else "under a minute"


def ago(dt, now: datetime.datetime) -> str:
    dt = _aware(dt)
    return f"{duration((now - dt).total_seconds())} ago" if dt else "?"


def stage_eta(run: Dict[str, Any]) -> Tuple[Optional[int], Optional[float]]:
    """(percent done, seconds left at the current pace) for the run's current stage."""
    done, total = run.get("done"), run.get("total")
    if not total or done is None:
        return None, None
    pct = int(100 * done / total)
    start, at = _aware(run.get("stage_started_at")), _aware(run.get("progress_at"))
    if not (start and at and done > 0):
        return pct, None
    elapsed = (at - start).total_seconds()
    if elapsed <= 0:
        return pct, None
    return pct, (total - done) * elapsed / done


def count_line(view: List[Dict[str, Any]]) -> str:
    order = ("generated", "generating", "waiting", "stopped", "failed", "not_requested")
    n = {s: sum(1 for c in view if c["state"] == s) for s in order}
    parts = [f"{n[s]} {STATE_LABEL[s]}" for s in order if n[s]]
    return f"{len(view)} component(s): " + (" · ".join(parts) if parts else "none")


def progress_lines(*, version: Any, pipeline_status: Optional[str], run: Optional[Dict[str, Any]],
                   alive: Optional[bool], view: List[Dict[str, Any]], project_id: str,
                   now: Optional[datetime.datetime] = None) -> List[str]:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    name = getattr(version, "tag", None) or getattr(version, "version", None) or version.id
    out = [f"version   {name} ({version.id})   commit {(version.commit_sha or '?')[:10]}",
           f"phase     {pipeline_status or 'not started'}"]
    if run:
        out.append(f"run       {run.get('command') or '?'} -- pid {run.get('pid')} on "
                   f"{run.get('host')}, started {ago(run.get('started_at'), now)}")
        resume = (f"python analyzer.py resume --project-id {project_id} "
                  f"--version-id {version.id} --detach")
        if alive:
            out.append("state     RUNNING (it holds the version)")
        elif run.get("outcome") == "running" and alive is False:
            out.append(f"state     STOPPED -- the process is gone. Continue it with:\n"
                       f"            {resume}")
        elif run.get("outcome") == "running":
            out.append("state     running, as last recorded (this database cannot tell whether "
                       "the process is alive)")
        else:
            out.append(f"state     {run.get('outcome') or '?'}, {ago(run.get('finished_at'), now)}")
        if run.get("log_path"):
            out.append(f"log       {run['log_path']}")
        if run.get("code_dir"):
            out.append(f"code      {run['code_dir']} (frozen copy)")
        if run.get("stage") and run.get("outcome") == "running" and alive is False:
            # A killed run never closed its record: say where it was, not a time left.
            out.append(f"stopped   during {run['stage']}: {run.get('done') or 0:,}/"
                       f"{run.get('total') or 0:,}, last update {ago(run.get('progress_at'), now)}")
        elif run.get("stage") and run.get("outcome") == "running":
            pct, left = stage_eta(run)
            line = f"now       {run['stage']}: {run.get('done') or 0:,}/{run.get('total') or 0:,}"
            if pct is not None:
                line += f" ({pct}%)"
            if left is not None:
                line += (" -- under a minute left in this stage" if left < 60 else
                         f" -- about {duration(left)} left in this stage at its pace so far")
            out.append(line)
            out.append(f"          last update {ago(run.get('progress_at'), now)}")
    else:
        out.append("run       none recorded")
    out.append(count_line(view))
    if not alive and any(c["state"] in ("stopped", "failed") and c.get("in_model", True)
                         for c in view) and not (
            run and run.get("outcome") == "running" and alive is False):
        out.append(f"          components were cut short or failed -- `resume` makes them again:\n"
                   f"            python analyzer.py resume --project-id {project_id} "
                   f"--version-id {version.id} --detach")
    for c in view:
        if c["state"] in ("generating", "stopped", "failed"):
            extra = f" -- {c['error']}" if c.get("error") else ""
            out.append(f"  {c['component']:<32} {STATE_LABEL[c['state']]}{extra}")
    return out


def component_lines(view: List[Dict[str, Any]], *, project_id: str, version_id: str) -> List[str]:
    out: List[str] = []
    layer = None
    width = max([len(c["name"]) for c in view] + [12])
    for c in view:
        if c["layer"] != layer:
            layer = c["layer"]
            mine = [x for x in view if x["layer"] == layer]
            out.append(f"{layer or '(no layer)'} -- {count_line(mine)}")
        docs = " · ".join(f"{d['process']} {DOC_STATUS.get(d['status'], d['status'])}"
                          for d in c["documents"])
        note = f"   {docs}" if docs else ""
        if c.get("error") and c["state"] == "failed":
            note += f"   {c['error']}"
        if not c["in_model"]:
            note += "   (not in this version's model)"
        out.append(f"  {c['name']:<{width}}  {STATE_LABEL[c['state']]:<13}{note}")
    out.append("")
    out.append(count_line(view))
    if any(c["state"] in NOT_GENERATED and c["in_model"] for c in view):
        out.append(f"make the rest:  python analyzer.py export --project-id {project_id} "
                   f"--version-id {version_id} --remaining   (or --components A,B)")
    return out
