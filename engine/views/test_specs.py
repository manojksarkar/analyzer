"""Test-spec view (SWE.4): model -> output/<group>/test_specs.json.

Emits one deterministic spec per function that gets one, following
docs/spec/SWE4_WIKI.md. Everything here is derived from the model alone — no
LLM, no sibling-view output — so a rerun on unchanged input is byte-identical.

The Test Steps transcription and the per-return Expected entries come from the
control-flow graph and are filled by the CFG pass; this view lays down the facts
they attach to and leaves `testSteps` / `expected.returns` empty.

Schema (mirrors interface_tables so the SWE.4 exporter can iterate the same
shape): {"unitNames": {unit_key: display}, <unit_key>: {name, functions: [...]}}.
"""
import json
import os

from .registry import register
from utils import get_range, log, short_name, KEY_SEP

# The wiki fixes the generation method as a code constant, not a config key.
GENERATION_METHOD = "Analysis of Requirements"

_HEADER_EXTS = (".h", ".hpp", ".hxx", ".hh")


def _is_header(path):
    return (path or "").lower().endswith(_HEADER_EXTS)


def _test_case_id(func):
    """Deterministic per-function Test Case ID — one per function, however many
    inputs its Table A lists. Prefers the stable interfaceId."""
    iid = func.get("interfaceId") or ""
    if iid:
        return f"TC_{iid}"
    qn = func.get("qualifiedName") or "unknown"
    return "TC_" + "".join(ch if ch.isalnum() else "_" for ch in qn)


def _is_out_parameter(param):
    """A non-const pointer/reference parameter is an output, not an input.

    The model records no per-parameter write information, so this is the
    conventional reading of the signature: `T*`/`T&` is written through,
    `const T*`/`const T&` is read. Out-parameters are excluded from Input and
    asserted in Expected Results instead.

    A function pointer (`int (*)(int, int)`) is a callback the caller supplies —
    an input — even though its type contains a `*`.
    """
    t = (param.get("type") or "")
    if "*" not in t and "&" not in t:
        return False
    if "(*" in t.replace(" ", ""):     # function pointer -> callback, an input
        return False
    return "const" not in t


def _decl(type_str, name):
    """`type name`, the form Precondition uses."""
    t = (type_str or "").strip()
    n = (name or "").strip()
    return f"{t} {n}".strip() if n else t


def _ranged(type_str, name, dd):
    """`type name[low-high]`, the form Input and Expected use. A type with no
    meaningful range (pointer, struct, void) is written without brackets."""
    decl = _decl(type_str, name)
    rng = get_range(type_str or "", dd)
    if not rng or rng in ("NA", "VOID"):
        return decl
    return f"{decl}[{rng}]"


def _spec_function_ids(units_data, functions_data, allowed_components):
    """The function ids that get a spec of their own.

    Per the wiki: every function in the SWE.3 detailed design (a `.cpp`-backed
    unit, not private) **except inline public functions** — those defined in a
    header, which are covered through the functions that call them.

    Called for two different jobs, at two different scopes (layer > group >
    component > unit):

    - the document's components -> which functions this document writes a spec for.
    - the whole LAYER's components -> the mock rule. A callee is mocked if and only
      if it is in that set. Anything outside it (a private helper, an inline public
      function) has no spec of its own, so it must run inline or its branches are
      exercised nowhere.

    The mock rule must not be narrowed to the document's components. A callee in
    another component of the same layer still has a spec of its own, in that
    component's document, so the tester stubs it. Narrowing it made every
    cross-component callee look like an unspecced helper and silently inlined it:
    dropped from Precondition, its return value dropped from Input, and its
    `Successfully called mock functions` line dropped from Expected Results.

    The layer is the ceiling, and it has to be stated explicitly: a run covers one
    layer, and a callee outside it belongs to a different deliverable. Passing None
    would mean "everything parsed", which equals the layer only when the parse was
    itself layer-scoped -- on a full multi-layer parse it reaches across layers.
    """
    spec_ids = set()
    for unit_key, unit_info in units_data.items():
        if allowed_components and KEY_SEP in unit_key:
            if unit_key.split(KEY_SEP, 1)[0].lower() not in allowed_components:
                continue
        if not (unit_info.get("fileName") or "").endswith(".cpp"):
            continue
        for fid in unit_info.get("functionIds", []) or []:
            f = functions_data.get(fid)
            if not f:
                continue
            if (f.get("visibility") or "").lower() == "private":
                continue
            if _is_header((f.get("location") or {}).get("file", "")):
                continue
            spec_ids.add(fid)
    return spec_ids


def _layer_components(config, allowed_components):
    """Every component of the layer(s) owning `allowed_components`, lowercased.

    The mock rule's scope. Returns None when the layer cannot be resolved — no
    `layers` config, no selected components, or names that match nothing — which
    falls back to "everything parsed". That is the only safe default: under-scoping
    here silently drops mocks, which is the failure this scope exists to prevent.
    """
    layers_cfg = (config or {}).get("layers") or {}
    if not layers_cfg or not allowed_components:
        return None
    wanted = {(c or "").replace(" ", "-").lower() for c in allowed_components}
    scope = set()
    for layer_cfg in layers_cfg.values():
        comps = set()
        for grp in ((layer_cfg or {}).get("groups") or {}).values():
            if isinstance(grp, dict):
                comps |= {(k or "").replace(" ", "-").lower() for k in grp}
        if comps & wanted:
            scope |= comps
    return scope or None


def _mocked_callee_ids(func, functions_data, spec_ids):
    """Every callee this spec stubs: the direct ones with a spec of their own, plus
    those reached **through a callee that runs inline**.

    Follow the real execution path and stop at each stub. A callee with no spec of
    its own is not mocked, so it really executes -- and a call it makes to a function
    that *does* have a spec really happens, and must be stubbed here too. Looking at
    direct callees only missed those: the tester never mocked them, so the real
    function linked in and the test quietly stopped being a unit test.

    Example: `utilChain` calls `utilNorm`, which has no spec and so runs inline;
    `utilNorm` calls `utilCompute`, which has its own spec. `utilCompute()` belongs
    in `utilChain`'s mock list even though `utilChain` never names it.
    """
    mocked, seen = set(), set()
    stack = list(func.get("callsIds") or [])
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        if cid in spec_ids:      # a stub: it does not run, so do not walk into it
            mocked.add(cid)
            continue
        callee = functions_data.get(cid)
        if not callee:           # unnameable library call -- left out (wiki)
            continue
        stack.extend(callee.get("callsIds") or [])
    return mocked


def _mock_functions(func, functions_data, spec_ids):
    """Callees to stub, written `name()` — exactly those with a spec of their own."""
    names = set()
    for cid in _mocked_callee_ids(func, functions_data, spec_ids):
        callee = functions_data.get(cid)
        if not callee:
            continue
        nm = short_name(callee.get("qualifiedName", "")) or ""
        if nm:
            names.add(f"{nm}()")
    return sorted(names)


def _mock_return_entries(func, functions_data, spec_ids, dd):
    """Input entries for mocked callees that return a value.

    A `void` mock has nothing to set, so it is named in the Precondition but
    does not appear in Input.
    """
    seen, out = set(), []
    for cid in sorted(_mocked_callee_ids(func, functions_data, spec_ids)):
        callee = functions_data.get(cid)
        if not callee:
            continue
        ret = (callee.get("returnType") or "").strip()
        if not ret or ret.lower() == "void":
            continue
        nm = short_name(callee.get("qualifiedName", "")) or ""
        if not nm or nm in seen:
            continue
        seen.add(nm)
        out.append({"kind": "mockReturn", "name": f"{nm}()", "type": ret,
                    "text": _ranged(ret, f"{nm}()", dd)})
    return out


def _global_ids(func, which, functions_data, spec_ids):
    """Global ids for 'reads' or 'writes': the function's own, plus those reached
    through the callees that run **inline**.

    The model's `<which>GlobalIdsTransitive` spans the entire call graph and cannot
    be used here: it also carries globals touched only by *mocked* callees. A mock is
    a stub — it never executes, so its globals are not preconditions of this spec, and
    naming them tells the tester to set up state the test can never reach. The wiki
    scopes it deliberately: globals are "the function's, plus its inlined helpers'".

    So walk the callee chain and stop at every mock boundary — the mirror of
    `_mocked_callee_ids`. Recursing through the inlined callees, rather than reading
    their transitive field, keeps that boundary honoured at any depth.
    """
    out = set(func.get(f"{which}GlobalIds") or [])
    seen = set()
    stack = [cid for cid in (func.get("callsIds") or []) if cid not in spec_ids]
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        callee = functions_data.get(cid)
        if not callee:
            continue
        out |= set(callee.get(f"{which}GlobalIds") or [])
        stack.extend(c for c in (callee.get("callsIds") or []) if c not in spec_ids)
    return out


def _global_name(gid, g):
    return short_name(g.get("qualifiedName", "")) or gid.split(KEY_SEP)[-1]


def _build_spec(fid, func, unit_key, unit_name, functions_data,
                global_variables_data, spec_ids, dd):
    qn = func.get("qualifiedName", "")
    name = short_name(qn)
    params = func.get("parameters") or []
    reads = _global_ids(func, "reads", functions_data, spec_ids)
    writes = _global_ids(func, "writes", functions_data, spec_ids)

    # ---- Precondition: names only, no values, no ranges -------------------
    pre_globals = []
    for gid in sorted(reads | writes):
        g = global_variables_data.get(gid)
        if not g:
            continue
        pre_globals.append({"globalId": gid, "name": _global_name(gid, g),
                            "type": g.get("type", ""),
                            "text": _decl(g.get("type", ""), _global_name(gid, g))})
    precondition = {
        "mockFunctions": _mock_functions(func, functions_data, spec_ids),
        "parameters": [{"name": p.get("name", ""), "type": p.get("type", ""),
                        "text": _decl(p.get("type", ""), p.get("name", ""))}
                       for p in params],
        "globals": pre_globals,
    }

    # ---- Input: the read side of the Precondition, with ranges ------------
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
    input_entries += _mock_return_entries(func, functions_data, spec_ids, dd)

    # ---- Expected Results -------------------------------------------------
    out_params = [{"kind": "outParameter", "name": p.get("name", ""),
                   "type": p.get("type", ""),
                   "text": _ranged(p.get("type", ""), p.get("name", ""), dd)}
                  for p in params if _is_out_parameter(p)]
    written_globals = []
    for gid in sorted(writes):
        g = global_variables_data.get(gid)
        if not g:
            continue
        gname = _global_name(gid, g)
        written_globals.append({"kind": "global", "globalId": gid, "name": gname,
                                "type": g.get("type", ""),
                                "text": _ranged(g.get("type", ""), gname, dd)})

    spec = {
        "functionId": fid,
        "interfaceId": func.get("interfaceId", ""),
        "testCaseId": _test_case_id(func),
        "name": name,
        "qualifiedName": qn,
        "unitKey": unit_key,
        "unitName": unit_name,
        "location": dict(func.get("location", {})),
        "returnType": func.get("returnType", ""),
        "generationMethod": GENERATION_METHOD,
        "precondition": precondition,
        "input": {"entries": input_entries, "isVoid": not input_entries},
        "expected": {
            "mockFunctions": precondition["mockFunctions"],
            # One entry per return, each naming the step it comes from. Needs the
            # control-flow graph, so the CFG pass fills it.
            "returns": [],
            "outParameters": out_params,
            "globals": written_globals,
        },
        # Numbered transcription of the flowchart -- filled by the CFG pass.
        "testSteps": [],
    }
    if func.get("description"):
        spec["description"] = func["description"]
    return spec


def _build_test_specs(units_data, functions_data, global_variables_data,
                      data_dictionary=None, *, allowed_components=None,
                      mock_components=None):
    dd = data_dictionary or {}
    # Mockability is scoped to the LAYER; which functions this document writes a
    # spec for is scoped to its components. See _spec_function_ids.
    spec_ids = _spec_function_ids(units_data, functions_data, mock_components)
    doc_ids = _spec_function_ids(units_data, functions_data, allowed_components)
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
                  for uk, u in units_data.items()}

    result = {"unitNames": {}}
    for unit_key, unit_info in units_data.items():
        unit_name = unit_names[unit_key]
        specs = []
        for fid in sorted(unit_info.get("functionIds", []) or [],
                          key=lambda x: functions_data.get(x, {})
                                        .get("location", {}).get("line", 0)):
            if fid not in doc_ids:
                continue
            func = functions_data.get(fid)
            if not func:
                continue
            specs.append(_build_spec(fid, func, unit_key, unit_name, functions_data,
                                     global_variables_data, spec_ids, dd))
        if specs:
            result[unit_key] = {"name": unit_name, "functions": specs}
    result["unitNames"] = {k: unit_names[k] for k in result if k != "unitNames"}
    return result


@register("testSpecs")
def run(model, output_dir, model_dir, config):
    allowed_components = {m.lower() for m in (config.get("_analyzerAllowedComponents") or [])}
    test_specs = _build_test_specs(
        model.get("units", {}),
        model.get("functions", {}),
        model.get("globalVariables", {}),
        model.get("dataDictionary", {}),
        allowed_components=allowed_components,
        mock_components=_layer_components(config, allowed_components),
    )
    # Test Steps + the per-return Expected entries come from the flowchart
    # engine's CFG (Phase 3 runs `flowcharts` before `testSpecs` for swe4).
    from .test_steps import attach as _attach_steps
    filled = _attach_steps(test_specs, output_dir)
    if filled:
        log("transcribed control flow into steps for %d function(s)" % filled,
            component="testSpecs")

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "test_specs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(test_specs, f, indent=2)
    spec_count = sum(len(v.get("functions", [])) for k, v in test_specs.items()
                     if k != "unitNames")
    unit_count = len([k for k in test_specs if k != "unitNames"])
    log("%s (%d units, %d function specs)" % (out_path, unit_count, spec_count),
        component="testSpecs")
