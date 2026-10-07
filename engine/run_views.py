"""Load model from disk and run views. Phase 3: Generate views."""
import os
import sys
import json

from core.paths import paths as _paths

# Apply (and strip) --model-root / --output-root BEFORE paths() is snapshotted below.
# `_p` is a MODULE-LEVEL snapshot, so applying the overrides later (e.g. inside main())
# leaves every constant derived from it pointing at the DEFAULT directories. That is not
# cosmetic: this phase hands `model_dir` to the views, which look there for
# incremental_plan.json — with a stale value the plan is never found, carry-forward never
# runs, and an incremental run silently emits only the diagrams it regenerated.
from core.run_context import apply_cli_run_context as _apply_run_context
sys.argv = _apply_run_context(sys.argv)
from core.logging_setup import start_phase_logging as _start_phase_logging  # noqa: E402
_start_phase_logging()     # this step in the live log (docs/design/LIVE_LOGS_DESIGN.md)

_p = _paths()
SCRIPT_DIR = _p.src_dir
PROJECT_ROOT = _p.project_root


def _filter_model_to_components(model: dict, allowed: set) -> dict:
    """Return a copy of model with only data belonging to the given component names."""
    from core.model_io import FUNCTIONS, GLOBALS, UNITS, COMPONENTS
    lower = {c.lower().replace(" ", "-") for c in allowed}
    filtered = dict(model)
    # functions / globals / units: key starts with "ComponentName|..."
    for key in (FUNCTIONS, GLOBALS, UNITS):
        if key in model:
            filtered[key] = {k: v for k, v in model[key].items()
                             if k.split("|")[0].lower() in lower}
    # components: key IS the component name
    if COMPONENTS in model:
        filtered[COMPONENTS] = {k: v for k, v in model[COMPONENTS].items()
                                 if k.lower() in lower}
    return filtered


def _assert_components_in_model(model: dict, selected_components) -> None:
    """Fail when a named component is not in the stored model at all.

    Phase 1 parses whole LAYERS, so re-rendering a component the original run did
    not name is free and supported — as long as its layer was parsed. A component
    from a layer that was NOT is a different matter: there is nothing to render, and
    the run used to finish with exit 0 and an empty document. That is the silent
    wrong output this whole area exists to prevent, so it stops here instead.

    Only for EXPLICIT `--selected-component` names, which the caller typed and can
    fix. A group scope derives its components from config, where one may legitimately
    have no parsed source (an empty directory), and failing the group for that would
    refuse a run that is merely uninteresting.
    """
    from core.model_io import COMPONENTS

    known = model.get(COMPONENTS)
    if not isinstance(known, dict) or not known:
        return                       # no component index to check against; say nothing

    def _ident(name):
        return (name or "").strip().replace(" ", "-").casefold()

    have = {_ident(k) for k in known}
    missing = [c for c in selected_components if _ident(c) not in have]
    if not missing:
        return

    layers = sorted({(str(k).split(".", 1)[0] if "." in str(k) else "") for k in known} - {""})
    raise SystemExit(
        f"[run_views] {', '.join(repr(c) for c in missing)} "
        f"{'is' if len(missing) == 1 else 'are'} not in this version's model.\n"
        f"  The model covers {len(known)} component(s)"
        + (f" in layer(s): {', '.join(layers)}.\n" if layers else ".\n")
        + "  Phase 1 parsed only the layers this version's runs selected, so a component\n"
        "  outside them has nothing stored to render. `analyzer.py export --components\n"
        "  <it>` adds a layer the version did not parse (it parses that layer with the\n"
        "  model's and derives the model again), then makes its documents; or run\n"
        "  `generate` with a scope that covers its layer, for a new version."
    )

def _unit_names(model: dict, allowed_components=None) -> list:
    """Unit names that this run will actually visit.

    Unit keys are "Component|Unit". The model reaching here is filtered to the
    *layer*, which is wider than the run's component scope — so a unit from a
    sibling group would otherwise look valid while contributing nothing, because
    the flowchart filter requires the component to match too.
    """
    from core.model_io import UNITS
    lower = {c.lower() for c in (allowed_components or [])}
    names = set()
    for k in (model.get(UNITS) or {}):
        if not k:
            continue
        parts = k.split("|")
        if lower and parts[0].lower() not in lower:
            continue
        names.add(parts[-1])
    return sorted(names)


def _unit_home(model: dict, unit: str) -> list:
    """Which component(s) a unit name lives in. For error messages only."""
    from core.model_io import UNITS
    key = unit.strip().lower()
    homes = set()
    for k in (model.get(UNITS) or {}):
        parts = (k or "").split("|")
        if len(parts) > 1 and parts[-1].lower() == key:
            homes.add(parts[0])
    return sorted(homes)


def _resolve_units(model: dict, requested: list, allowed_components=None,
                   *, strict: bool = True) -> list:
    """Map requested unit names onto the model's spelling, or exit with a listing.

    A mistyped unit would otherwise filter the function set down to nothing and the run would
    report success having generated no flowcharts at all — so a name that exists NOWHERE is a
    hard error, with a suggestion when one is close.

    `strict` is what separates the two callers, and conflating them was the bug:

      * run.py validates ONCE against the whole run's scope, at startup -- and only when the
        stored model is the one Phase 3 will use (`group_planner.unit_check_can_run_early`).
        A unit outside that scope will produce nothing anywhere, so it is an error — strict=True.
      * Phase 3 runs once PER COMPONENT when documents are per component (the normal case).
        `--selected-unit Utils` reaches the App invocation as well as the Math one, and there
        the unit is not unknown, merely elsewhere — strict=False, narrow to nothing, say so.

    Before this split, the App invocation killed the whole run with "unknown --selected-unit
    'Utils'" after Math's diagrams had already been rendered.
    """
    import difflib
    in_scope = _unit_names(model, allowed_components)
    anywhere = _unit_names(model)                    # ignore the component filter
    by_lower = {u.lower(): u for u in in_scope}
    anywhere_lower = {u.lower() for u in anywhere}
    resolved, unknown, elsewhere = [], [], []
    for u in requested:
        key = u.strip().lower()
        match = by_lower.get(key)
        if match:
            resolved.append(match)
        elif key in anywhere_lower:
            elsewhere.append(u)
        else:
            unknown.append(u)
    if unknown:
        for u in unknown:
            near = difflib.get_close_matches(u, in_scope if strict else anywhere,
                                             n=3, cutoff=0.5)
            hint = f" Did you mean {' or '.join(repr(n) for n in near)}?" if near else ""
            print(f"Error: unknown --selected-unit {u!r}.{hint}")
        _listing = in_scope if strict else anywhere
        print(f"Units in scope: {', '.join(_listing) if _listing else '(none)'}")
        raise SystemExit(1)
    if elsewhere and strict:
        # Outside the whole run's scope: it will produce nothing anywhere, which is the case
        # the hard error exists for. Do NOT call it unknown -- it exists, it is just not in
        # the scope that was asked for, and the two need different fixes: a typo is fixed in
        # the unit name, this one is fixed in --scope. Saying "unknown" for a unit the caller
        # can see in their own source sends them looking for the wrong thing.
        for u in elsewhere:
            homes = _unit_home(model, u)
            where = f" It is in {', '.join(homes)}, which this run's scope excludes." if homes else ""
            print(f"Error: --selected-unit {u!r} is not in this run's scope.{where}")
        if elsewhere:
            _homes = sorted({h for u in elsewhere for h in _unit_home(model, u)})
            if _homes:
                print(f"  Widen the scope to reach it, e.g. --scope \"component:{_homes[0]}\"")
        print(f"Units in scope: {', '.join(in_scope) if in_scope else '(none)'}")
        raise SystemExit(1)
    if elsewhere and not resolved:
        print(f"[run_views] {', '.join(elsewhere)} is not in this component "
              f"({', '.join(sorted(allowed_components or [])) or 'this scope'}) — "
              f"nothing to render here.")
        # A sentinel no unit can be called, so every view narrows to nothing rather
        # than falling back to "no filter = render everything".
        return ["__none__"]
    return resolved


def _load_model():
    from core.model_io import (
        load_model, FUNCTIONS, GLOBALS, UNITS, COMPONENTS, DATA_DICTIONARY, ModelFileMissing,
    )
    try:
        return load_model(
            FUNCTIONS, GLOBALS, UNITS, COMPONENTS,
            optional=[DATA_DICTIONARY],
        )
    except ModelFileMissing as e:
        print(f"Error: {e}. Run Phase 2 (model_deriver) first.")
        raise SystemExit(1)



#: Set when this run could not load the reviewers' corrections (`_with_text_overrides`): its
#: views are built without them, so it must not vouch for them (`_record_derivation`).
_OVERRIDES_UNAVAILABLE = False


def _with_text_overrides(config):
    """`config` plus this version's reviewer corrections (`REQ-AP-05`).

    Returns `config` unchanged when there is no version id (a standalone run) or no database --
    both are ordinary, and neither is a reason to fail a phase that has already paid for the
    parse and the enrichment. A correction that cannot be loaded is logged, not raised: losing a
    whole generation over it would cost far more than the correction is worth.
    """
    try:
        from core.run_context import version_id as _vid
        from core.db import get_engine, is_database_configured
        vid = _vid()
        if not (vid and is_database_configured()):
            return config
        from review.carry_forward import config_with_overrides
        with get_engine().connect() as cx:
            out = config_with_overrides(cx, vid, config)
        from review.phase3_overrides import CONFIG_KEY
        n = sum(len(v) for v in (out.get(CONFIG_KEY) or {}).values())
        if n:
            print("[run_views] applying %d reviewer correction(s) to this run" % n)
        return out
    except Exception as exc:                       # noqa: BLE001 - see docstring
        global _OVERRIDES_UNAVAILABLE
        _OVERRIDES_UNAVAILABLE = True
        print("[run_views] WARNING: could not load the reviewers' corrections (%s): these views "
              "are built without them, and are left marked stale so that an export re-derives "
              "them first" % exc)
        return config


def _check_model_corrections(model) -> None:
    """Every correction in force must be in the model these views are built from. Phase 2 puts
    them back last and never fails a run over it, so one can be missing (RF-1): this run puts it
    back -- in `model` and in the stored model (`carry_forward.restore_missing_corrections`) --
    and only if that fails are the views left unstamped, so the export guard does not call the
    LLM's text up to date. Never fatal, like loading the corrections."""
    global _OVERRIDES_UNAVAILABLE
    try:
        from core.run_context import version_id as _vid
        from core.db import get_engine, is_database_configured
        vid = _vid()
        if not (vid and is_database_configured()):
            return
        from review.carry_forward import corrections_missing, restore_missing_corrections
        with get_engine().connect() as cx:
            missing = corrections_missing(cx, vid, model)
        if missing:
            with get_engine().begin() as cx:
                n = restore_missing_corrections(cx, vid, model, missing)
            print("[run_views] put back %d reviewer correction(s) the model had lost (Phase 2 "
                  "could not re-apply them)" % n)
            with get_engine().connect() as cx:
                missing = corrections_missing(cx, vid, model)
    except Exception as exc:                       # noqa: BLE001 - cannot tell: the cautious way
        missing = [("?", str(exc))]
    if missing:
        _OVERRIDES_UNAVAILABLE = True
        print("[run_views] WARNING: %d reviewer correction(s) are not in the model and could not "
              "be put back (e.g. %s %s): these views print the LLM's text and are left marked "
              "stale; `reexport --from-phase 2` re-derives the model" % (len(missing), *missing[0]))


def _rebuilt_behaviour_rows(output_dir) -> list:
    """The slot keys of the behaviour rows this run wrote into its manifest."""
    from review import phase3_overrides as p3, slot
    path = os.path.join(output_dir, "behaviour_diagrams", "_behaviour_pngs.json")
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for _c, _u, row in p3.behaviour_rows((payload or {}).get("_docxRows")):
        fid, caller = row.get("currentFunctionId"), row.get("externalCallerId")
        if fid and caller:
            try:
                out.append(slot.for_behaviour_row(fid, caller))
            except slot.SlotKeyError:
                continue
    return out


def _retire_behaviour_regenerations(output_dir, ran, model, config) -> None:
    """Clear the queued behaviour-row regenerations this run paid (`REQ-CS-01`).

    Only when the behaviour view ran, and only for the rows it covered: the rows it wrote, and the
    rows of the components it ran over that it no longer writes (`cascade.clear_behaviour_entries`).
    A SWE.4-only run, a run with the view switched off and a run over another component rebuild
    no behaviour row, and must not report one as rebuilt.

    Never fatal: the views have already run and their output is written; failing the phase here
    would throw that away over bookkeeping.
    """
    try:
        if "behaviourDiagram" not in (ran or ()):
            return
        from core.run_context import version_id as _vid
        from core.db import get_engine, is_database_configured
        vid = _vid()
        if not (vid and is_database_configured()):
            return
        # Not narrowed by --selected-unit: that re-renders only some images, and the view still
        # writes every row of its components (views/behaviour_diagram.py).
        from core.model_io import COMPONENTS
        allowed = config.get("_analyzerAllowedComponents")
        components = list(allowed) if allowed else list((model.get(COMPONENTS) or {}).keys())
        from review.cascade import clear_behaviour_entries
        with get_engine().begin() as cx:
            n = clear_behaviour_entries(cx, vid, _rebuilt_behaviour_rows(output_dir), components)
        if n:
            print("[run_views] retired %d regenerated behaviour description(s)" % n)
    except Exception as exc:                       # noqa: BLE001 - see docstring
        print("[run_views] could not retire behaviour regenerations: %s" % exc)


def _rewrite_request(path, *, only: bool) -> dict:
    """The charts whose labels this run writes again (`--rewrite-labels <file>`, written by the
    update: `review.rewrite.write_labels_request`), as the flowcharts view reads them. `only` --
    the run makes some views alone -- charts those functions alone, into the stored charts.

    A request that cannot be read stops the phase: charting everything, or nothing, in place of
    what was asked would both look like success."""
    from review.rewrite import read_labels_request
    req = read_labels_request(path)
    if not req.get("keys"):
        raise SystemExit("[run_views] --rewrite-labels %s names no chart" % path)
    return {"keys": list(req["keys"]), "report": req.get("report"), "only": only}


def _layers_by_name(config) -> dict:
    """`layers` reduced to what the SWE.4 views read from it -- which components each group of
    each layer holds (`test_specs._layer_components`). Paths and file names stay out: they are
    machine-specific, and the record they would travel in is stored with the output."""
    out = {}
    for lname, lcfg in ((config or {}).get("layers") or {}).items():
        if not isinstance(lcfg, dict):
            continue
        groups = {gname: {c: {} for c in grp}
                  for gname, grp in (lcfg.get("groups") or {}).items() if isinstance(grp, dict)}
        out[lname] = {"groups": groups}
    return out


def _record_derivation(output_dir, ran, model, config, read_at, layer_filter,
                       doc_type=None) -> None:
    """Leave the export guard its record of what this run rebuilt (`REQ-AP-04`).

    The record is turned into `view_derivations` rows when the output is captured, in the same
    transaction as the rows themselves -- so it is written only for a versioned run with a
    database, which is the only kind that is captured. Not for a run narrowed to some units
    (`--selected-unit`): it rebuilt part of a component, and a stamp for the whole component would
    vouch for text it never touched. Never fatal -- the views are built; a missing record only
    makes the guard more cautious.
    """
    try:
        from core.run_context import version_id as _vid
        from core.db import is_database_configured
        if not ran or not (_vid() and is_database_configured()):
            return
        if _OVERRIDES_UNAVAILABLE:
            # Built without the corrections: no stamp for these views, so the export guard asks
            # for a re-derive instead of calling the LLM's text up to date (RF-1).
            from review.export_guard import forget_derivation
            forget_derivation(output_dir, ran)
            return
        if config.get("_analyzerSelectedUnits"):
            print("[run_views] --selected-unit narrowed this run; not recorded as a derivation")
            return
        from core.model_io import COMPONENTS
        allowed = config.get("_analyzerAllowedComponents")
        components = list(allowed) if allowed else list((model.get(COMPONENTS) or {}).keys())
        # What the SWE.4 views were built with, so a save can re-derive them exactly as this run
        # did (review.swe4_rederive) -- a version generated from the CLI stores no config of its
        # own anywhere else.
        context = {"allowedComponents": sorted(allowed) if allowed else None,
                   "layerComponents": sorted(layer_filter) if layer_filter else None,
                   "views": (config.get("views") or {}),
                   "layers": _layers_by_name(config)}
        # Which document each view was built for -- by the rule that chose to build it. One
        # `--doc-type all` run builds the flowcharts for SWE.4 alone when `views.flowcharts` is
        # off, and the SWE.3 exporter then prints none (`export_guard._swe3_built`).
        from views import views_to_run
        from views.registry import concrete_doc_types
        types = concrete_doc_types(doc_type or "swe3")
        built_for = {v: [t for t in types if v in views_to_run(t, config)] for v in ran}
        from review.export_guard import record_derivation
        record_derivation(output_dir, ran, components, read_at, context=context,
                          doc_types=built_for)
    except Exception as exc:                       # noqa: BLE001 - see docstring
        print("[run_views] could not record this derivation: %s" % exc)


def main():
    args = sys.argv[1:]        # path flags already applied at import

    output_dir = os.path.join(PROJECT_ROOT, "output")
    if "--output-dir" in args:
        i = args.index("--output-dir")
        if i + 1 < len(args):
            output_dir = args[i + 1]
    selected_group = None
    if "--selected-group" in args:
        i = args.index("--selected-group")
        if i + 1 < len(args):
            selected_group = args[i + 1]
    selected_components = []
    for j in range(len(args) - 1):
        if args[j] == "--selected-component":
            selected_components.append(args[j + 1])
    # Development aid: narrow the expensive per-function view work to these
    # units. The model is left whole, so anything derived from it is unchanged.
    selected_units = [args[j + 1] for j in range(len(args) - 1)
                      if args[j] == "--selected-unit"]
    filter_mode_override = None
    if "--filter-mode" in args:
        i = args.index("--filter-mode")
        if i + 1 < len(args):
            filter_mode_override = args[i + 1]
    allowed_components_override = None
    if "--allowed-components" in args:
        i = args.index("--allowed-components")
        if i + 1 < len(args):
            allowed_components_str = args[i + 1]
            allowed_components_override = [m.strip() for m in allowed_components_str.split(",") if m.strip()]
    from views.registry import DOC_TYPE_SWE3
    doc_type = DOC_TYPE_SWE3
    if "--doc-type" in args:
        i = args.index("--doc-type")
        if i + 1 < len(args):
            doc_type = args[i + 1]
    # An update's Phase 3 (FAST_WORD_FILE_UPDATES P5): only these of the views the doc type needs,
    # and the charts whose labels are written again -- `run.py --views / --rewrite-labels`.
    only_views = None
    if "--views" in args:
        i = args.index("--views")
        if i + 1 < len(args):
            only_views = [v.strip() for v in args[i + 1].split(",") if v.strip()]
    rewrite_labels = None
    if "--rewrite-labels" in args:
        i = args.index("--rewrite-labels")
        if i + 1 < len(args):
            rewrite_labels = args[i + 1]
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    from core.config import app_config
    from views import run_views

    # REQ-AP-04. This run's derivation is stamped with the moment it READ its inputs: taken before
    # the model is loaded, so a correction saved after it -- into the model or the override table
    # -- is newer than the stamp and still reads as stale.
    import datetime as _dt
    read_at = _dt.datetime.now(_dt.timezone.utc)
    model = _load_model()
    config = app_config()
    config = dict(config)  # make a copy so we can modify it
    model_dir = _p.model_dir
    layer_filter = None    # the components the model is narrowed to, for the derivation record
    # Apply filter mode override from command line
    if filter_mode_override:
        if "views" not in config:
            config["views"] = {}
        if "sequenceDiagrams" not in config["views"]:
            config["views"]["sequenceDiagrams"] = {}
        config["views"]["sequenceDiagrams"]["filterMode"] = filter_mode_override
        print(f"[run_views] Using filter mode: {filter_mode_override}")
    if selected_group:
        from core.config import get_flat_groups
        groups = get_flat_groups(config)
        resolved = selected_group
        
        # For single-file mode, use allowed_components_override instead of componentsGroups
        if selected_group.startswith("_single_file_") and allowed_components_override:
            config["_analyzerAllowedComponents"] = allowed_components_override
            config["_analyzerSelectedGroup"] = selected_group
        if isinstance(groups, dict) and selected_group not in groups:
            # Group ids are layer-qualified; a bare name still resolves while only one
            # layer has it. run.py and plan_runs already refuse an ambiguous one, so by
            # the time Phase 3 runs there is at most one candidate left.
            from core.config import resolve_group_id
            _r, _ = resolve_group_id(groups, selected_group)
            if _r:
                resolved = _r
        if resolved != selected_group:
            print(f"[run_views] --selected-group resolved to {resolved!r}")
        grp = (groups.get(resolved) if isinstance(groups, dict) else None)
        if isinstance(grp, dict):
            config = dict(config)
            config["_analyzerSelectedGroup"] = resolved
            config["_analyzerAllowedComponents"] = sorted(k.replace(" ", "-") for k in grp.keys())
            # Filter model to only include components from the same layer
            from core.config import get_layer_components
            layer_comps = get_layer_components(config, resolved)
            if layer_comps:
                model = _filter_model_to_components(model, layer_comps)
                layer_filter = layer_comps
    elif selected_components:
        from core.config import get_component_layer_name, get_layer_flat_groups
        config = dict(config)
        config["_analyzerAllowedComponents"] = sorted(selected_components)
        _assert_components_in_model(model, selected_components)
        # Union over every layer the bundle spans, so a cross-layer selection keeps
        # both layers' components in the model instead of filtering one of them away.
        derived_layers = {l for l in (get_component_layer_name(config, c)
                                      for c in selected_components) if l}
        layer_comps: set = set()
        for _l in derived_layers:
            for g in get_layer_flat_groups(config, _l).values():
                if isinstance(g, dict):
                    layer_comps.update(g.keys())
        if layer_comps:
            model = _filter_model_to_components(model, layer_comps)
            layer_filter = layer_comps
    if selected_units:
        selected_units = _resolve_units(
            model, selected_units, config.get("_analyzerAllowedComponents"), strict=False)
        config = dict(config)
        config["_analyzerSelectedUnits"] = selected_units
        # _resolve_units already explained the "elsewhere" case; echoing its sentinel here
        # would print `narrowed to unit(s): __none__`, which reads like a bug.
        if selected_units != ["__none__"]:
            print(f"[run_views] narrowed to unit(s): {', '.join(selected_units)}")
    # REQ-AP-05. The two Phase-3 kinds -- node labels and behaviour descriptions -- have no
    # model field, so their corrections are an INPUT to this phase. Attached HERE, in the
    # runner, rather than inside a view: a view stays a pure function of (model, config) and
    # never opens a database of its own.
    config = _with_text_overrides(config)
    _check_model_corrections(model)
    if rewrite_labels:
        config = dict(config)
        config["_analyzerRewriteLabels"] = _rewrite_request(rewrite_labels, only=bool(only_views))

    ran = run_views(model, output_dir, model_dir, config, doc_type=doc_type,
                    only=only_views) or []

    # REQ-AP-04. What this run rebuilt -- which views, for which components, from corrections read
    # when -- for the export guard. See review.export_guard.
    _record_derivation(output_dir, ran, model, config, read_at, layer_filter, doc_type)

    # REQ-CS-01's other half. A queued behaviour description has no model field to blank, so
    # Phase 2 cannot pay that debt -- but the behaviour view rebuilds every row it writes, so
    # running it IS the regeneration. Retired here, where it actually happened, and only for the
    # rows this run covered.
    _retire_behaviour_regenerations(output_dir, ran, model, config)


if __name__ == "__main__":
    main()
    # DB mode: land this phase's buffered model writes (doc 10, step 3). Database writes are
    # buffered so the pieces persist together in one transaction, so without this the phase
    # exits and the buffer is lost — the next phase then finds no model at all. Deliberately
    # AFTER main() returns, never in a finally: a phase that failed must not publish a
    # half-built model. No-op in file mode and when nothing is pending.
    from core.run_context import flush_model
    flush_model()
