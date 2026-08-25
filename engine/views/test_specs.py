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
    - the whole LAYER's components -> **one arm of** the mock rule: a callee in that
      set has a spec of its own, so it is stubbed. It is not the whole rule -- a
      callee outside the unit under test is stubbed whether or not it has a spec.
      See `_mocked_callee_ids`.

    That arm must not be narrowed to the document's components. A callee in another
    component of the same layer still has a spec of its own, in that component's
    document, so the tester stubs it. Narrowing it made every cross-component callee
    look like an unspecced helper and silently inlined it: dropped from Precondition,
    its return value dropped from Input, and its `Successfully called mock functions`
    line dropped from Expected Results.

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


def _unit_of(units_data):
    """`fid -> unit_key`. Functions carry no unit membership of their own, and the
    mock rule turns on whether a callee is *this unit's* code, so it needs the
    reverse index."""
    index = {}
    for unit_key, unit_info in units_data.items():
        for fid in unit_info.get("functionIds", []) or []:
            index[fid] = unit_key
    return index


def _mocked_callee_ids(func, functions_data, spec_ids, unit_of, home_unit):
    """Every callee this spec stubs, plus those reached **through a callee that
    runs inline**.

    A callee is stubbed when either is true:

    - **it has a spec of its own** -- its branches are covered there, so running it
      here would only duplicate that coverage; or
    - **it belongs to a different unit** -- this is a unit test spec, not an
      integration one, so nothing outside the unit under test may execute.

    The second arm is what an "own spec" test alone cannot express. An inline public
    function is defined in a header and so gets no spec anywhere (wiki, "Who gets a
    spec"), but a header is included everywhere: one defined in *another* unit's
    header was being inlined into this spec -- its branches, its globals and its own
    callees folded into a unit test for code that does not belong to the unit. The
    same held for another unit's private function. Both are now stubbed.

    Only a callee that is **this unit's own and has no spec** runs inline: a
    same-unit private helper, or a same-unit inline header function. Those must
    execute, or their branches are exercised nowhere and coverage cannot reach 100%.

    Follow the real execution path and stop at each stub. A callee that runs inline
    really executes -- and a call *it* makes to something stubbable really happens,
    and must be stubbed here too. Looking at direct callees only missed those: the
    tester never mocked them, so the real function linked in and the test quietly
    stopped being a unit test.

    Example: `utilChain` calls `utilNorm`, a same-unit helper that runs inline;
    `utilNorm` calls `utilCompute`, which has its own spec. `utilCompute()` belongs
    in `utilChain`'s mock list even though `utilChain` never names it.

    A callee whose unit cannot be resolved counts as **outside** the unit: its file
    was never parsed, so it cannot be this unit's own code. Defaulting the other way
    would silently inline it, which is the failure this rule exists to prevent. It
    still has to be nameable to reach the document -- an unresolvable library call
    drops out downstream, as the wiki says.

    A unit key is path-based, so `Foo.h` and `Foo.cpp` are one unit: a header-only
    file with no `.cpp` is a unit of its own, and its inline functions are cross-unit
    to every caller outside it.
    """
    mocked, seen = set(), set()
    stack = list(func.get("callsIds") or [])
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        if cid in spec_ids or unit_of.get(cid) != home_unit:
            mocked.add(cid)      # a stub: it does not run, so do not walk into it
            continue
        callee = functions_data.get(cid)
        if not callee:           # unnameable library call -- left out (wiki)
            continue
        stack.extend(callee.get("callsIds") or [])
    return mocked


def _mock_functions(mocked_ids, functions_data):
    """Callees to stub, written `name()`. See `_mocked_callee_ids` for the rule."""
    names = set()
    for cid in mocked_ids:
        callee = functions_data.get(cid)
        if not callee:
            continue
        nm = short_name(callee.get("qualifiedName", "")) or ""
        if nm:
            names.add(f"{nm}()")
    return sorted(names)


def _bare_type(type_str):
    """`const MapEntry *` -> `MapEntry`, the form the data dictionary is keyed by."""
    t = (type_str or "").strip()
    for token in ("const", "volatile", "struct", "*", "&"):
        t = t.replace(token, " ")
    return " ".join(t.split())


def _mock_writeback_entries(func, mocked_ids, functions_data, dd):
    """Input entries for values a mocked callee writes back through a pointer.

    A stub does not just return — it fills in whatever it is handed. If the function
    then branches on one of those fields, the tester must make the stub write it, or
    the branch reads uninitialised memory and the test is nondeterministic. The wiki
    lists exactly these (`uint32_t e.lba`, `uint32_t e.ppn` in its worked example).

    Only the fields **this function actually reads** are listed. A mock can touch
    every field of the struct it receives, but a field the function never reads back
    cannot change its behaviour or its output, so listing it would hand the tester a
    dead input — a column to fill in that provably changes nothing. `readsFields`
    (parser) supplies that filter, matched on the base's declared type so a field
    name shared by two structs cannot match the wrong one.

    Known limitation: the filter is per-function, not per-decision. A field read
    anywhere in the body qualifies, where the wiki means one a branch depends on —
    narrowing that needs the CFG. The result is a superset, never a wrong entry.
    """
    reads = func.get("readsFields") or []
    if not reads:
        return []
    read_by_type = {}
    for r in reads:
        read_by_type.setdefault(r.get("structType", ""), {}).setdefault(
            r.get("field", ""), r.get("var", ""))

    seen, out = set(), []
    for cid in sorted(mocked_ids):
        callee = functions_data.get(cid)
        if not callee:
            continue
        for p in callee.get("parameters") or []:
            if not _is_out_parameter(p):
                continue
            fields_read = read_by_type.get(_bare_type(p.get("type")))
            if not fields_read:
                continue
            entry = dd.get(_bare_type(p.get("type")))
            dd_fields = {f.get("name"): f
                         for f in (entry or {}).get("fields", [])
                         if isinstance(entry, dict)}
            for fname, base_var in sorted(fields_read.items()):
                fld = dd_fields.get(fname)
                if not fld:          # not a data field of this struct
                    continue
                label = f"{base_var}.{fname}"
                if label in seen:
                    continue
                seen.add(label)
                ftype = fld.get("type", "")
                out.append({"kind": "mockWriteback", "name": label, "type": ftype,
                            "text": _ranged(ftype, label, dd)})
    return out


def _mock_return_entries(mocked_ids, functions_data, dd):
    """Input entries for mocked callees that return a value.

    A `void` mock has nothing to set, so it is named in the Precondition but
    does not appear in Input.
    """
    seen, out = set(), []
    for cid in sorted(mocked_ids):
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


def _global_ids(func, which, functions_data, mocked_ids):
    """Global ids for 'reads' or 'writes': the function's own, plus those reached
    through the callees that run **inline**.

    The model's `<which>GlobalIdsTransitive` spans the entire call graph and cannot
    be used here: it also carries globals touched only by *mocked* callees. A mock is
    a stub — it never executes, so its globals are not preconditions of this spec, and
    naming them tells the tester to set up state the test can never reach. The wiki
    scopes it deliberately: globals are "the function's, plus its inlined helpers'".

    So walk the callee chain and stop at every mock boundary — the mirror of
    `_mocked_callee_ids`, and it must use that function's own answer rather than
    re-deriving one. Recursing through the inlined callees, rather than reading their
    transitive field, keeps the boundary honoured at any depth.
    """
    out = set(func.get(f"{which}GlobalIds") or [])
    seen = set()
    stack = [cid for cid in (func.get("callsIds") or []) if cid not in mocked_ids]
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        callee = functions_data.get(cid)
        if not callee:
            continue
        out |= set(callee.get(f"{which}GlobalIds") or [])
        stack.extend(c for c in (callee.get("callsIds") or []) if c not in mocked_ids)
    return out


def _trace_derivation(name, func, functions_data, global_variables_data, mocked_ids,
                      precondition, input_entries):
    """Why each Precondition/Input entry is there -- and what was left out.

    DEBUG only (`--verbose`), and it returns before doing any work when DEBUG is
    off, so a normal run pays nothing. Exists because the derivation is otherwise
    only checkable by re-deriving it by hand: every bug found on 2026-08-19 was an
    entry that should not have been there, or one that should have been and was not.
    The `drop` lines are the useful ones -- exclusions are invisible in the document.
    """
    import logging
    from core.logging_setup import get_logger
    logger = get_logger("testSpecs")
    if not logger.isEnabledFor(logging.DEBUG):
        return

    def qn(fid):
        return short_name((functions_data.get(fid) or {}).get("qualifiedName", "")) or fid

    # Re-walk recording HOW each stub was reached: directly, or through which
    # inlined callee. Mirrors _mocked_callee_ids.
    via, seen = {}, set()
    stack = [(cid, None) for cid in (func.get("callsIds") or [])]
    while stack:
        cid, through = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        if cid in mocked_ids:
            via.setdefault(cid, through)
            continue
        callee = functions_data.get(cid)
        if not callee:
            continue
        stack.extend((c, cid) for c in (callee.get("callsIds") or []))

    lines = [f"derivation: {name}"]
    for m in precondition.get("mockFunctions") or []:
        fid = next((f for f in via if f"{qn(f)}()" == m), None)
        through = via.get(fid)
        lines.append(f"    mock  {m:<22} "
                     + (f"via inlined {qn(through)}" if through else "direct call"))
    for g in precondition.get("globals") or []:
        lines.append(f"    glob  {g.get('name',''):<22} read or written on the executed path")

    # Globals the model's transitive set carries but the mock boundary excluded.
    bounded = {g.get("globalId") for g in precondition.get("globals") or []}
    for which in ("reads", "writes"):
        for gid in (func.get(f"{which}GlobalIdsTransitive") or []):
            if gid in bounded:
                continue
            gv = global_variables_data.get(gid) or {}
            gname = short_name(gv.get("qualifiedName", "")) or gid
            reader = next((qn(c) for c in via
                           if gid in ((functions_data.get(c) or {}).get(f"{which}GlobalIds") or [])),
                          None)
            verb = "read" if which == "reads" else "written"
            lines.append(f"    drop  {gname:<22} "
                         + (f"only {verb} by mocked {reader}()" if reader
                            else f"only {verb} beyond the mock boundary"))
    for e in input_entries:
        kind = e.get("kind", "")
        why = {"parameter": "parameter", "global": "global read on the executed path",
               "mockReturn": "return value of a mocked callee",
               "mockWriteback": "field a mocked callee writes back, read here"}.get(kind, kind)
        lines.append(f"    in    {e.get('name',''):<22} {why}")
    logger.debug("\n".join(lines))


def _out_parameter_entries(func, params, dd):
    """Expected-Results entries for out-parameters the function actually writes.

    The signature alone only says a parameter *could* be written.
    `applyWithOperation(Operation* op, ...)` merely calls `op->apply(a, b)` and never
    modifies `op`, yet a signature-only rule asserted "Successfully updated
    Operation * op" -- a statement the tester writes as a check, watches fail, and
    then hunts for a defect that is not there.

    So the body decides, via `writesParams`: the pointer/reference parameters it is
    seen to write, by dereference (`*out = x`) or by field (`w->id = x`). The wiki
    asserts the whole parameter ("one entry per out-parameter written"), so no
    per-field breakdown is emitted.

    A parameter not in that set is not asserted. The key is omitted when empty, so a
    model parsed before it existed reads as "writes nothing" and its out-parameters
    go unasserted. That is the safe direction to fail: a missing assertion is a gap a
    reviewer can see, whereas an unprovable one costs a tester real time.
    Regenerating needs a full re-parse, not `--from-phase 2`.
    """
    written = set(func.get("writesParams") or [])
    return [{"kind": "outParameter", "name": p.get("name", ""),
             "type": p.get("type", ""),
             "text": _ranged(p.get("type", ""), p.get("name", ""), dd)}
            for p in params
            if _is_out_parameter(p) and p.get("name", "") in written]


def _global_name(gid, g):
    return short_name(g.get("qualifiedName", "")) or gid.split(KEY_SEP)[-1]


def _build_spec(fid, func, unit_key, unit_name, functions_data,
                global_variables_data, spec_ids, unit_of, dd):
    qn = func.get("qualifiedName", "")
    name = short_name(qn)
    params = func.get("parameters") or []
    # One walk, one boundary. Precondition, Input, the globals scope and the trace
    # all have to agree on where this spec stops executing -- when they each derived
    # it separately, a mocked callee's globals could still reach the Precondition.
    mocked_ids = _mocked_callee_ids(func, functions_data, spec_ids, unit_of, unit_key)
    reads = _global_ids(func, "reads", functions_data, mocked_ids)
    writes = _global_ids(func, "writes", functions_data, mocked_ids)

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
        "mockFunctions": _mock_functions(mocked_ids, functions_data),
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
    input_entries += _mock_return_entries(mocked_ids, functions_data, dd)
    input_entries += _mock_writeback_entries(func, mocked_ids, functions_data, dd)

    _trace_derivation(name, func, functions_data, global_variables_data, mocked_ids,
                      precondition, input_entries)

    # ---- Expected Results -------------------------------------------------
    out_params = _out_parameter_entries(func, params, dd)
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
    unit_of = _unit_of(units_data)
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
                                     global_variables_data, spec_ids, unit_of, dd))
        if specs:
            result[unit_key] = {"name": unit_name, "functions": specs}
    result["unitNames"] = {k: unit_names[k] for k in result if k != "unitNames"}
    return result


@register("testSpecs")
def run(model, output_dir, model_dir, config):
    allowed_components = {m.lower() for m in (config.get("_analyzerAllowedComponents") or [])}
    # Which SWE.4 spec kinds this run emits. Two independent switches rather than
    # one mode flag, so "function specs only" is expressible too. The flowchart
    # pass DERIVES its scope from these same keys (see
    # `flowcharts._spec_scope_function_ids`): Test Steps come only from a CFG, so
    # asking a user to keep `views.flowcharts` in step by hand would only offer a
    # way to request a document that cannot be built.
    _views = config.get("views", {}) or {}
    want_function_specs = _views.get("functionTestSpecs", True)
    want_dynamic_specs = _views.get("dynamicBehaviourSpecs", True)
    if not want_function_specs:
        test_specs = {"unitNames": {}}
    else:
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
    filled = _attach_steps(test_specs, output_dir) if want_function_specs else 0
    if filled:
        log("transcribed control flow into steps for %d function(s)" % filled,
            component="testSpecs")

    # Dynamic Behaviour test specs: one per interaction, scoped to the component
    # rather than the unit. Keyed beside the units, so every consumer that walks
    # this file's top-level keys skips it by name.
    from .dynamic_specs import DYNAMIC_KEY, build as _build_dynamic
    dynamic = {} if not want_dynamic_specs else _build_dynamic(
        model.get("units", {}),
        model.get("functions", {}),
        model.get("globalVariables", {}),
        model.get("components", {}),
        model.get("dataDictionary", {}),
        allowed_components=allowed_components,
        filter_mode=((config.get("views", {}) or {}).get("sequenceDiagrams", {}) or {})
                    .get("filterMode", "skip_within_unit"),
    )
    test_specs[DYNAMIC_KEY] = dynamic
    if dynamic:
        from .test_steps import attach_dynamic as _attach_dynamic
        units_data = model.get("units", {})
        unit_of = {fid: uk for uk, u in units_data.items()
                   for fid in (u.get("functionIds") or [])}
        unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
                      for uk, u in units_data.items()}
        dyn_filled = _attach_dynamic(dynamic, output_dir, model.get("functions", {}),
                                     unit_of, unit_names)
        if dyn_filled:
            log("transcribed %d interaction(s) with unit attribution" % dyn_filled,
                component="testSpecs")

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "test_specs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(test_specs, f, indent=2)
    _reserved = ("unitNames", DYNAMIC_KEY)
    spec_count = sum(len(v.get("functions", [])) for k, v in test_specs.items()
                     if k not in _reserved)
    unit_count = len([k for k in test_specs if k not in _reserved])
    dyn_count = sum(len(v) for v in dynamic.values())
    log("%s (%d units, %d function specs, %d dynamic behaviour specs)"
        % (out_path, unit_count, spec_count, dyn_count), component="testSpecs")
