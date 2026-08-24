"""Dynamic Behaviour test specs (SWE.4): one spec per *interaction*.

A function spec verifies one function with everything outside its unit stubbed.
A dynamic behaviour spec verifies the *interaction* a component performs when an
outside caller enters it, so the component's own units run for real and only
calls leaving the component are stubbed. See docs/spec/SWE4_WIKI.md,
"Dynamic Behaviour test specs".

Nothing here re-derives Precondition or Input. `test_specs._build_spec` funnels
both through a single `mocked_ids` set -- "one walk, one boundary" -- so widening
the boundary from the unit to the component is the entire change, and every
builder downstream (`_mock_functions`, `_global_ids`, `_mock_return_entries`,
`_mock_writeback_entries`) is reused untouched. Two consequences fall out of that
one swap, and both are the point of this document section:

  - an in-component callee leaves the mock list, so its return value leaves Input;
  - the globals walk now passes *through* it, so that other unit's globals come
    into scope.

Selection is delegated to the behaviour-diagram selector rather than restated, so
SWE.3's Dynamic Behaviour section and this one cannot drift apart: a spec exists
exactly where a diagram is drawn.

Deterministic, like the rest of the view -- no LLM. The diagram's
`behaviorDescription` is deliberately NOT consumed: its call arrows are LLM prose
when `llm.descriptions` is on, so the topology is read from the model's call graph
instead, which is the same set of edges and never LLM-touched.
"""

from utils import KEY_SEP, short_name

from .test_specs import (
    GENERATION_METHOD,
    _decl,
    _global_ids,
    _global_name,
    _is_out_parameter,
    _mock_functions,
    _mock_return_entries,
    _mock_writeback_entries,
    _out_parameter_entries,
    _ranged,
)

# Top-level keys in test_specs.json that are not unit entries. The document
# iterates the file's keys, so anything added beside the units has to be skipped
# by name.
DYNAMIC_KEY = "dynamicSpecs"

# Provisional. The wiki leaves the Test Case ID scheme OPEN -- it only has to stay
# distinct from the `TC_<interfaceId>` of the same function's own spec. This suffix
# satisfies that and nothing more; change it when the client settles the scheme.
_DYNAMIC_ID_SUFFIX = "_DYN"


def _component_of(unit_key):
    """`Signal|SignalDriver` -> `Signal`. Unit keys are `Component|Unit`."""
    return (unit_key or "").split(KEY_SEP)[0] if KEY_SEP in (unit_key or "") else ""


def _walk_boundary(func, functions_data, unit_of, home_component):
    """Split this spec's callees into the ones that run and the ones that are stubbed.

    The component-scoped twin of `test_specs._mocked_callee_ids`, and the only
    place the two spec kinds actually differ. Both arms of the function-spec rule
    are gone:

      - "has a spec of its own" -- dropped deliberately. The callee this section
        exists to exercise (another unit of this component) usually *does* have its
        own spec; stubbing it would erase the interaction under test.
      - "belongs to a different unit" -- widened to a different *component*.

    Follow the real execution path and stop at each stub, exactly as the unit-scoped
    walk does: a callee that runs really executes, so a call *it* makes to something
    outside the component really happens and must be stubbed here too.

    A callee whose unit cannot be resolved counts as **outside** the component --
    its file was never parsed, so it cannot be this component's code. Defaulting the
    other way would silently inline it.

    Returns `(executing_ids, mocked_ids)`.
    """
    executing, mocked, seen = set(), set(), set()
    stack = list(func.get("callsIds") or [])
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        if _component_of(unit_of.get(cid, "")) != home_component:
            mocked.add(cid)      # a stub: it does not run, so do not walk into it
            continue
        callee = functions_data.get(cid)
        if not callee:           # unnameable library call -- left out (wiki)
            continue
        executing.add(cid)
        stack.extend(callee.get("callsIds") or [])
    return executing, mocked


def _unit_to_component(components_data):
    """`unit_key -> component name`, the shape the behaviour selector expects."""
    return {un: cn
            for cn, cd in (components_data or {}).items()
            for un in (cd.get("units") or [])}


def select_targets(units_data, functions_data, components_data,
                   unit_of, filter_mode, allowed_components):
    """`[(target_fid, caller_fid)]` -- the interactions that get a spec.

    Delegated to the behaviour-diagram selector so the rule has one home. Under the
    default `skip_within_unit` mode that means: public, at least one external
    caller, and a forward chain spanning more than one unit of its own component;
    one spec per function, from its first external caller.

    `allowed_components` narrows this to the document's own components. The model
    reaching the view is filtered to the *layer*, which is wider, so callers outside
    the document but inside the layer still count as external callers -- exactly the
    context the selector needs.
    """
    try:
        from behaviour_diagram.selector import create_diagram_selector
    except ImportError:      # behaviour engine unavailable -- emit no dynamic specs
        return []

    selector = create_diagram_selector(
        filter_mode, unit_of, _unit_to_component(components_data), functions_data,
        "Unknown")

    targets = []
    for fid in sorted(unit_of):
        unit_key = unit_of[fid]
        if allowed_components and _component_of(unit_key).lower() not in allowed_components:
            continue
        func = functions_data.get(fid)
        if not func or (func.get("visibility") or "").lower() == "private":
            continue
        chosen = selector.select_diagrams_to_generate(fid)
        if chosen:
            targets.append((fid, chosen[0][0]))
    return targets


def _entry_point(caller_fid):
    """`Cross|Hub|hubCompute|int,int` -> `Hub - hubCompute`.

    The same label the behaviour view writes as `externalUnitFunction`, so the
    SWE.4 heading and the SWE.3 diagram caption read identically.
    """
    parts = (caller_fid or "").split(KEY_SEP)
    if len(parts) < 3:
        return caller_fid or ""
    return "%s - %s" % (parts[1], short_name(parts[2]))


def _cross_unit_calls(executing, unit_key, unit_of, unit_names, functions_data):
    """The in-component, cross-unit calls this spec must observe.

    These are what the interaction *is*; a function spec could never assert them,
    because it stubs every one of them.
    """
    calls = []
    for cid in sorted(executing):
        callee_unit = unit_of.get(cid, "")
        if callee_unit == unit_key:
            continue                     # same unit: covered by that function's spec
        callee = functions_data.get(cid)
        if not callee:
            continue
        callee_unit_name = unit_names.get(callee_unit, callee_unit)
        qn = callee.get("qualifiedName", "")
        calls.append({
            "functionId": cid,
            "name": short_name(qn),
            "qualifiedName": qn,
            "unitKey": callee_unit,
            "unitName": callee_unit_name,
            "text": "%s.%s" % (callee_unit_name, qn or short_name(qn)),
        })
    return calls


def _build_dynamic_spec(fid, func, caller_fid, unit_key, unit_name, functions_data,
                        global_variables_data, unit_of, unit_names, dd):
    """One Table A + Table B for one interaction.

    Precondition and Input are the function-spec builders, unchanged, fed the
    component-scoped boundary. Only the cross-unit call list and the entry point
    are new.
    """
    qn = func.get("qualifiedName", "")
    name = short_name(qn)
    params = func.get("parameters") or []
    home_component = _component_of(unit_key)

    executing, mocked_ids = _walk_boundary(func, functions_data, unit_of, home_component)
    reads = _global_ids(func, "reads", functions_data, mocked_ids)
    writes = _global_ids(func, "writes", functions_data, mocked_ids)

    # ---- Precondition: names only, no values, no ranges --------------------
    pre_globals = []
    for gid in sorted(reads | writes):
        g = global_variables_data.get(gid)
        if not g:
            continue
        gname = _global_name(gid, g)
        pre_globals.append({"globalId": gid, "name": gname, "type": g.get("type", ""),
                            "text": _decl(g.get("type", ""), gname)})
    precondition = {
        "mockFunctions": _mock_functions(mocked_ids, functions_data),
        "parameters": [{"name": p.get("name", ""), "type": p.get("type", ""),
                        "text": _decl(p.get("type", ""), p.get("name", ""))}
                       for p in params],
        "globals": pre_globals,
    }

    # ---- Input: the read side of the Precondition, with ranges -------------
    input_entries = []
    for p in params:
        if _is_out_parameter(p):
            continue          # written through -> an output, asserted in Expected
        input_entries.append({"kind": "parameter", "name": p.get("name", ""),
                              "type": p.get("type", ""),
                              "text": _ranged(p.get("type", ""), p.get("name", ""), dd)})
    for gid in sorted(reads):  # write-only globals are outputs, not inputs
        g = global_variables_data.get(gid)
        if not g:
            continue
        gname = _global_name(gid, g)
        input_entries.append({"kind": "global", "globalId": gid, "name": gname,
                              "type": g.get("type", ""),
                              "text": _ranged(g.get("type", ""), gname, dd)})
    input_entries += _mock_return_entries(mocked_ids, functions_data, dd)
    input_entries += _mock_writeback_entries(func, mocked_ids, functions_data, dd)

    # ---- Expected Results --------------------------------------------------
    written_globals = []
    for gid in sorted(writes):
        g = global_variables_data.get(gid)
        if not g:
            continue
        gname = _global_name(gid, g)
        written_globals.append({"kind": "global", "globalId": gid, "name": gname,
                                "type": g.get("type", ""),
                                "text": _ranged(g.get("type", ""), gname, dd)})

    base_id = func.get("interfaceId") or ""
    test_case_id = ("TC_%s%s" % (base_id, _DYNAMIC_ID_SUFFIX) if base_id
                    else "TC_" + "".join(ch if ch.isalnum() else "_" for ch in qn)
                         + _DYNAMIC_ID_SUFFIX)

    return {
        "functionId": fid,
        "callerFunctionId": caller_fid,
        "entryPoint": _entry_point(caller_fid),
        "interfaceId": base_id,
        "testCaseId": test_case_id,
        "name": name,
        "qualifiedName": qn,
        "unitKey": unit_key,
        "unitName": unit_name,
        "component": home_component,
        "location": dict(func.get("location", {})),
        "returnType": func.get("returnType", ""),
        "generationMethod": GENERATION_METHOD,
        "precondition": precondition,
        "input": {"entries": input_entries, "isVoid": not input_entries},
        "expected": {
            "mockFunctions": precondition["mockFunctions"],
            # The interaction itself: asserted in step order once the CFG pass
            # has spliced the callee bodies in.
            "crossUnitCalls": _cross_unit_calls(executing, unit_key, unit_of,
                                                unit_names, functions_data),
            # One entry per return, each naming the step it comes from -- needs the
            # control-flow graph, so the CFG pass fills it.
            "returns": [],
            "outParameters": _out_parameter_entries(func, params, dd),
            "globals": written_globals,
        },
        # The interaction transcribed with unit attribution -- filled by the CFG pass.
        "testSteps": [],
        # Every function whose body runs in this spec, so the CFG pass knows which
        # callee graphs to splice rather than re-deriving the boundary.
        "executingFunctionIds": sorted(executing),
    }


def build(units_data, functions_data, global_variables_data, components_data,
          data_dictionary=None, *, allowed_components=None,
          filter_mode="skip_within_unit"):
    """`{component: [spec, ...]}` -- every interaction spec this document carries."""
    dd = data_dictionary or {}
    unit_of = {fid: uk
               for uk, u in units_data.items()
               for fid in (u.get("functionIds") or [])}
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
                  for uk, u in units_data.items()}

    result = {}
    for fid, caller_fid in select_targets(units_data, functions_data, components_data,
                                          unit_of, filter_mode, allowed_components):
        func = functions_data.get(fid)
        unit_key = unit_of.get(fid, "")
        if not func or not unit_key:
            continue
        spec = _build_dynamic_spec(fid, func, caller_fid, unit_key,
                                   unit_names.get(unit_key, unit_key), functions_data,
                                   global_variables_data, unit_of, unit_names, dd)
        result.setdefault(spec["component"], []).append(spec)
    return result


def needed_function_ids(units_data, functions_data, components_data,
                        allowed_components=None, filter_mode="skip_within_unit"):
    """Function ids whose control-flow graph a dynamic behaviour spec actually needs.

    Only two kinds qualify: each interaction's target, and the cross-unit callees
    whose bodies get spliced under it (`test_steps._splice_map` skips same-unit
    callees, so those need no graph of their own).

    This exists so the expensive Phase-3 CFG pass can be narrowed when a run only
    wants dynamic specs -- on the sample that is 2 functions instead of 140, because
    only 1 of 52 public functions qualifies for an interaction at all. Selection
    reads the call graph and nothing else, so it can be answered BEFORE the
    flowchart pass even though `DOC_TYPE_VIEWS` orders flowcharts first.
    """
    unit_of = {fid: uk
               for uk, u in (units_data or {}).items()
               for fid in (u.get("functionIds") or [])}
    needed = set()
    for fid, _caller in select_targets(units_data, functions_data, components_data,
                                       unit_of, filter_mode, allowed_components):
        func = functions_data.get(fid)
        home_unit = unit_of.get(fid, "")
        if not func or not home_unit:
            continue
        needed.add(fid)
        executing, _mocked = _walk_boundary(func, functions_data, unit_of,
                                            _component_of(home_unit))
        needed |= {c for c in executing if unit_of.get(c, "") != home_unit}
    return needed
