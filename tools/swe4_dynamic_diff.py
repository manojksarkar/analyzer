#!/usr/bin/env python3
"""Why does SWE.4 emit more Dynamic Behaviour specs than SWE.3 draws diagrams?

Both sides start from the same selector (`create_diagram_selector`), so the counts
should agree. They can diverge because the SWE.3 path applies two further filters
that the SWE.4 path does not:

  FILTER-1  views/behaviour_diagram.py -- when a GROUP is selected, "external
            caller" is re-defined as "outside the group". A caller in a sibling
            COMPONENT of the same group leaves `external_callers` empty, and the
            `idx >= len(external_callers): break` drops the row -- even though the
            selector chose it and the .mmd file was written to disk.

  FILTER-2  behaviour_diagram/generator.py -- `skip_within_unit and not
            has_internal_call` skips a diagram whose traced chain has no
            cross-unit arrow inside the component.

This prints every interaction SWE.4 selects and says which of the two filters (if
any) would have removed it from the SWE.3 document, so the difference is a list of
named functions rather than a pair of numbers.

Usage:
    python tools/swe4_dynamic_diff.py [--model DIR] [--group NAME] [--component C]...

With no scope flags every component in the model is considered.
"""
import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINE = os.path.join(_ROOT, "engine")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)


def _load(model_dir, name):
    with open(os.path.join(model_dir, f"{name}.json"), "r", encoding="utf-8") as f:
        return json.load(f) or {}


def _group_components(config, group_name):
    """Component names in `group_name`, searched across every layer."""
    for layer in (config.get("layers") or {}).values():
        for gname, grp in ((layer or {}).get("groups") or {}).items():
            if gname.lower() == group_name.lower() and isinstance(grp, dict):
                return {c.replace(" ", "-").lower() for c in grp}
    return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.path.join(_ROOT, "model"))
    ap.add_argument("--group")
    ap.add_argument("--component", action="append", default=[])
    ap.add_argument("--config", default=os.path.join(_ROOT, "engine", "config", "config.json"))
    ap.add_argument("--filter-mode", default=None)
    args = ap.parse_args()

    units = _load(args.model, "units")
    functions = _load(args.model, "functions")
    components = _load(args.model, "components")
    try:
        with open(args.config, "r", encoding="utf-8") as f:
            config = json.load(f) or {}
    except (OSError, ValueError):
        config = {}

    filter_mode = args.filter_mode or (
        ((config.get("views") or {}).get("sequenceDiagrams") or {}).get(
            "filterMode", "skip_within_unit"))

    allowed = {c.replace(" ", "-").lower() for c in args.component}
    if args.group:
        allowed |= _group_components(config, args.group)

    from views.dynamic_specs import select_targets, _component_of
    from behaviour_diagram import SequenceDiagramGenerator

    unit_of = {fid: uk for uk, u in units.items()
               for fid in (u.get("functionIds") or [])}
    targets = select_targets(units, functions, components, unit_of,
                             filter_mode, allowed)

    # A generator over the same model, to ask FILTER-2 the way SWE.3 asks it.
    gen = SequenceDiagramGenerator.__new__(SequenceDiagramGenerator)
    gen.components, gen.units, gen.functions = components, units, functions
    gen.function_to_unit = unit_of
    gen.unit_to_component = {un: cn for cn, cd in components.items()
                             for un in (cd.get("units") or [])}
    gen.UNKNOWN_COMPONENT = "Unknown"
    gen.filter_mode = filter_mode
    gen.config = config
    from behaviour_diagram.tracer import CallChainTracer
    from behaviour_diagram.mermaid_builder import MermaidBuilder
    from behaviour_diagram.llm_call_description import CallDescriptionGenerator
    gen._tracer = CallChainTracer(unit_of, gen.unit_to_component, functions, "Unknown")
    gen._mermaid_builder = MermaidBuilder(current_component=None)
    gen._call_description = CallDescriptionGenerator(None)

    kept, drop1, drop2 = [], [], []
    for fid, caller_fid in targets:
        unit_key = unit_of.get(fid, "")
        component = _component_of(unit_key)

        # FILTER-2: does the traced chain carry a cross-unit in-component arrow?
        try:
            _d, _b, has_internal = gen.generate_diagram_for_caller(
                fid, caller_fid, skip_within_unit=(filter_mode == "skip_within_unit"))
        except Exception:
            has_internal = True          # cannot tell -- do not blame this filter

        # FILTER-1: is the chosen caller outside the GROUP (not merely the component)?
        called_by = functions.get(fid, {}).get("calledByIds") or []
        if allowed:
            outside = [c for c in called_by
                       if c and "|" in c and c.split("|")[0].lower() not in allowed]
        else:
            outside = [c for c in called_by
                       if c and "|" in c and c.split("|")[0] != component]

        row = (component, unit_of.get(fid, ""), fid, caller_fid)
        if filter_mode == "skip_within_unit" and not has_internal:
            drop2.append(row)
        elif not outside:
            drop1.append(row)
        else:
            kept.append(row)

    def _show(title, rows):
        print("\n%s: %d" % (title, len(rows)))
        for component, unit_key, fid, caller in rows:
            print("  %-14s %-26s <- %s" % (component, fid.split("|")[2], caller))

    print("filter mode : %s" % filter_mode)
    print("scope       : %s" % (", ".join(sorted(allowed)) or "(whole model)"))
    print("\nSWE.4 dynamic behaviour specs : %d" % len(targets))
    print("SWE.3 diagram rows in the DOCX: %d" % len(kept))
    _show("Also in SWE.3", kept)
    _show("EXTRA in SWE.4 -- caller is inside the group, so FILTER-1 drops the "
          "SWE.3 row (the .mmd IS written to disk)", drop1)
    _show("EXTRA in SWE.4 -- no cross-unit arrow, so FILTER-2 drops the diagram",
          drop2)


if __name__ == "__main__":
    main()
