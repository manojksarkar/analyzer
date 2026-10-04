"""Each component of a version, with the state of its documents (staged generation).

A version's model covers whole layers; its documents are made per component, by any number of
runs. This answers "which components does this version have, and which have documents": the
one view behind `analyzer.py components`, `export --remaining`, `resume`, and later the web app.

State of a component, first rule that applies:

    a `version_components` row   its state: waiting | generating | generated | failed | stale
                                 -- and "stopped" for waiting/generating when no writer holds
                                 the version any more (the run died). `stale`: documents older
                                 than the model (a layer added since changed their inputs)
    documents, no row            generated (a version made before rows existed)
    neither                      not_requested -- nobody asked for it yet

The components come from the stored model (`model_components`: every component of the layers
Phase 1 parsed), the version's configuration (`config_components`: those of layers the model
lacks too -- `export` adds such a layer), the rows and the documents together, so nothing that
has a state is missing. Each entry says `in_model` and `layer_parsed` (its layer is in the model).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

STATES = ("generating", "waiting", "stopped", "failed", "stale", "generated", "not_requested")
HAS_DOCUMENTS = ("generated", "stale")
# What `export --remaining` and `resume` make: everything that has no documents yet.
NOT_GENERATED = ("waiting", "stopped", "failed", "not_requested")


def _split(component: str) -> tuple:
    layer, dot, name = component.partition(".")
    return (layer, name) if dot else ("", component)


def model_components(engine, version_id: str) -> List[str]:
    """The components of the layers this version parsed, as their output folder names."""
    if engine is None:
        return []
    from sqlalchemy import select
    from api.db.postgres import schema as s
    t = s.model_components
    with engine.connect() as cx:
        return sorted({r[0] for r in cx.execute(select(t.c.name).where(t.c.version_id == version_id))})


def state_rows(engine, version_id: str) -> Dict[str, Dict[str, Any]]:
    if engine is None:
        return {}
    from sqlalchemy import select
    from api.db.postgres import schema as s
    t = s.version_components
    with engine.connect() as cx:
        return {r.component: dict(r._mapping)
                for r in cx.execute(select(t).where(t.c.version_id == version_id))}


def config_components(db: Any, version: Any) -> List[str]:
    """Every component the version's configuration names, as layer-qualified output folder
    names (`Layer2.Gpio`) -- those of layers its model lacks too. From what
    `document_registry.component_dirs` merges: the project's `architecture_layers`, the version's
    `resolved_config`, the version's own `config.json` (`workspaces/<pid>/versions/<vid>/`) and
    the project's. Never raises: a configuration that cannot be read gives [] (and a log line),
    and the view is then the model's components, rows and documents, as before."""
    try:
        from types import SimpleNamespace
        from . import doc_render, document_registry
        project = db.projects.get(version.project_id) or SimpleNamespace(
            id=version.project_id, architecture_layers=None)
        out_root = (doc_render.workspaces_root() / str(version.project_id) / "versions"
                    / str(version.id) / "output")
        return sorted(document_registry.component_dirs(project, version, out_root))
    except Exception as exc:                        # noqa: BLE001 - see the docstring
        _log.warning("version %s: its configuration's components could not be read (%s: %s)",
                     getattr(version, "id", "?"), type(exc).__name__, exc)
        return []


def components_view(db: Any, version: Any, *, alive: Optional[bool] = None,
                    all_components: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Every component of `version`, sorted by layer then name.

    `alive`: whether a writer holds the version now (`core.version_run.alive`). False turns a
    waiting or generating component into "stopped"; None (cannot tell) leaves it as recorded.
    `all_components`: the components the version's configuration names; None reads them
    (`config_components`). Those outside the model are listed with `in_model: False`."""
    engine = getattr(db, "_engine", None)
    comps = set(model_components(engine, version.id))
    rows = state_rows(engine, version.id)
    if all_components is None:
        all_components = config_components(db, version)
    configured = {c for c in all_components or () if c}
    parsed_layers = {_split(c)[0] for c in comps}
    from .review_workflow import version_docs
    docs: Dict[str, list] = {}
    for d in version_docs(db, version):
        docs.setdefault(d.group, []).append(d)
    out = []
    for c in sorted(comps | configured | set(rows) | set(docs),
                    key=lambda x: (_split(x)[0], _split(x)[1].lower())):
        row = rows.get(c)
        if row is not None:
            state = row["state"]
            if alive is False and state in ("waiting", "generating"):
                state = "stopped"
        else:
            state = "generated" if docs.get(c) else "not_requested"
        layer, name = _split(c)
        out.append({
            "component": c, "layer": layer, "name": name, "state": state,
            "in_model": c in comps,
            # Whether its layer is in the model: False for a layer `export` must add first.
            "layer_parsed": c in comps or (bool(layer) and layer in parsed_layers),
            "requested_at": row and row.get("requested_at"),
            "started_at": row and row.get("started_at"),
            "finished_at": row and row.get("finished_at"),
            "error": row and row.get("error"),
            "documents": [{"id": d.id, "process": d.process, "status": d.status}
                          for d in sorted(docs.get(c, []), key=lambda d: d.process)],
        })
    return out


def counts(view: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {s: 0 for s in STATES}
    for c in view:
        out[c["state"]] = out.get(c["state"], 0) + 1
    return {k: v for k, v in out.items() if v}


def resolve(view: List[Dict[str, Any]], names: List[str]) -> tuple:
    """Map what a user typed -- `Layer1.Math` or a bare `Math` -- to components of the view:
    those of the model and those the version's configuration names in layers the model lacks
    (`export` adds such a layer). Returns (found, problems): a bare name two layers share, or
    one neither has, is a problem that names the candidates."""
    by_id = {c["component"]: c for c in view}
    found, problems = [], []
    for n in names:
        key = n.strip().replace(" ", "-")
        if not key:
            continue
        if key in by_id:
            found.append(key)
            continue
        hits = [c["component"] for c in view if c["name"].lower() == key.lower()
                or c["component"].lower() == key.lower()]
        if len(hits) == 1:
            found.append(hits[0])
        elif hits:
            problems.append(f"{n!r} is in more than one layer: {', '.join(hits)} -- name it "
                            f"with its layer")
        else:
            problems.append(f"{n!r} is not a component of this version: not in its model, nor "
                            f"in its configuration")
    return list(dict.fromkeys(found)), problems


def _staged():
    """engine/incremental/staged.py -- the one home of the rules (which components `export`,
    `reexport` and `resume` make), with the engine on the path as the API's runner arranges."""
    import os
    import sys
    eng = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)
    from incremental import staged
    return staged


def export_targets(view: List[Dict[str, Any]], found: List[str]) -> tuple:
    """(to make, skipped as generated) -- `analyzer.py export`'s rule."""
    return _staged().export_targets(view, found, remaining=False)


def default_reexport(view: List[Dict[str, Any]]) -> List[str]:
    """Every component the version has documents for -- what a re-export makes again."""
    return _staged().default_reexport(view)


#: What `resume` would do for a version a run stopped in: `staged.resume_plan`'s actions.
RESUMABLE = ("regenerate", "derive", "export", "close")


def resume_action(db: Any, version: Any, *, view: Optional[List[Dict[str, Any]]] = None,
                  alive: Optional[bool] = None, run: Optional[Dict[str, Any]] = None) -> str:
    """What resuming `version` would do now -- `analyzer.py resume`'s own rule
    (`staged.resume_plan`): busy | regenerate | derive | export | close | nothing.

    "busy" also when this API is at work on the version (one of its jobs), or the recorded run's
    process still lives on this machine (a database with no lock to ask: SQLite). "nothing" with
    no database behind the API: there is no run to carry on."""
    engine = getattr(db, "_engine", None)
    from . import pipeline_runner as pr
    vr = pr._version_run_module() if engine is not None else None
    if vr is None:
        return "nothing"
    if any(j.status in ("queued", "running", "paused") and (pr.job_alive(j.id) or pr._reexport_alive(j.id))
           for j in db.jobs.list_for_version(version.id)):
        return "busy"
    if alive is None:
        alive = vr.alive(version.id, engine=engine)
    if run is None:
        run = vr.run_row(version.id, engine=engine)
    if not alive and run and run.get("outcome") == "running":
        import socket
        fr = pr._frozen_run_module()
        if fr is not None and run.get("host") == socket.gethostname() and fr.process_alive(run.get("pid")):
            alive = True
    if view is None:
        view = components_view(db, version, alive=alive)
    import sqlalchemy as sa
    from api.db.postgres import schema as s
    with engine.connect() as cx:
        status = cx.execute(sa.select(s.versions.c.pipeline_status)
                            .where(s.versions.c.id == version.id)).scalar()
        parsed = bool(cx.execute(sa.select(sa.func.count()).select_from(s.parse_snapshots)
                                 .where(s.parse_snapshots.c.version_id == version.id)).scalar())
    return _staged().resume_plan(alive=alive, pipeline_status=status, view=view, run=run,
                                 parse_stored=parsed)["action"]
