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
        + "  Phase 1 parses only the layers the ORIGINAL run selected, so a component\n"
        "  outside them has nothing stored to render. Re-run `generate` with a scope\n"
        "  that covers its layer, then re-export."
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

      * run.py validates ONCE against the whole run's scope, before Phase 1. A unit outside
        that scope will produce nothing anywhere, so it is an error — strict=True.
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
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    from core.config import app_config
    from views import run_views

    model = _load_model()
    config = app_config()
    config = dict(config)  # make a copy so we can modify it
    model_dir = _p.model_dir
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
    if selected_units:
        selected_units = _resolve_units(
            model, selected_units, config.get("_analyzerAllowedComponents"), strict=False)
        config = dict(config)
        config["_analyzerSelectedUnits"] = selected_units
        # _resolve_units already explained the "elsewhere" case; echoing its sentinel here
        # would print `narrowed to unit(s): __none__`, which reads like a bug.
        if selected_units != ["__none__"]:
            print(f"[run_views] narrowed to unit(s): {', '.join(selected_units)}")
    run_views(model, output_dir, model_dir, config, doc_type=doc_type)


if __name__ == "__main__":
    main()
    # DB mode: land this phase's buffered model writes (doc 10, step 3). Database writes are
    # buffered so the pieces persist together in one transaction, so without this the phase
    # exits and the buffer is lost — the next phase then finds no model at all. Deliberately
    # AFTER main() returns, never in a finally: a phase that failed must not publish a
    # half-built model. No-op in file mode and when nothing is pending.
    from core.run_context import flush_model
    flush_model()
