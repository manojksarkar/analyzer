"""The UT export in the TARGET format: one test-case file per unit, plus a hierarchy file.

Written to one project-level `output/ut/` folder; our own per-group
`ut_export.json` is kept exactly as it was (the user
asked for both: ours may turn out useful, and parts of our reading of the target
format may be wrong). Shapes follow docs/spec/ut_templates/; every mapping choice
below that the sample does not settle is listed in docs/spec/UT_EXPORT_SPEC.md
(Assumptions) and docs/spec/UT_EXPORT_READINESS.md (doubts / questions).

Pure functions: `ut_export.py` hands in the specs, the solved values and the
configuration, and writes what comes back. `tools/check_ut_json.py` validates the
result against the templates.

Naming, in one place:
  section      = a unit (per core; one core per layer today, so simply the unit)
  environment  = the unit's one test environment, named <LAYER>_<COMPONENT>_<UNIT>_TS
  test-case    = one file per environment: <environment>.json
"""
import os
import re

from .ut_paths import NONNULL, bare_type, display, is_pointer

FORMAT_VERSION = "1.0"
PROTOTYPE_UNIT = "uut_prototype_stubs"
KEY_SEP = "|"
LAYER_SEP = "."


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def ident(text):
    """A name safe inside an environment name: runs of non-alphanumerics -> `_`."""
    return re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")


def split_unit_key(unit_key):
    """`Layer1.Sample-Core|Core` -> ("Layer1", "Sample-Core", "Core").

    The component id carries its layer before the first `.` (layer names cannot
    contain one). A bare component id (no layer) gives layer "".
    """
    comp, _, unit = (unit_key or "").partition(KEY_SEP)
    layer, sep, name = comp.partition(LAYER_SEP)
    if not sep:
        return "", comp, unit
    return layer, name, unit


def environment_name(unit_key):
    layer, comp, unit = split_unit_key(unit_key)
    parts = [ident(p) for p in (layer, comp, unit) if ident(p)]
    return "_".join(parts + ["TS"])


def owner_of(entity_id, qualified_name=""):
    """The `unit` a function or global is reported under.

    A C++ member lives in its class (`Ns::Cls`), which is what the sample writes
    as unit (`<Namespace>::<ClassName>`). A free function or file-scope global has
    no class, so its ArtiFex unit (the file, `Core`) stands in -- an assumption.
    """
    qn = qualified_name or ""
    if "::" in qn:
        return qn.rpartition("::")[0]
    parts = (entity_id or "").split(KEY_SEP)
    return parts[1] if len(parts) > 1 else ""


def short(qualified_name):
    return (qualified_name or "").rpartition("::")[2]


# ---------------------------------------------------------------------------
# Test-case file
# ---------------------------------------------------------------------------

def _target(spec):
    """`target` for a spec: unit + function, and `class` + a flag for ctor / dtor."""
    qn = spec.get("qualifiedName") or spec.get("name", "")
    fname = short(qn)
    if "::" not in qn:
        return {"unit": owner_of(spec.get("functionId", ""), qn), "function": fname}
    cls = qn.rpartition("::")[0]
    cls_short = short(cls)
    if fname == cls_short:
        return {"unit": cls, "class": cls, "function": cls, "constructor": True}
    if fname == "~" + cls_short:
        return {"unit": cls, "class": cls, "function": "~" + cls, "destructor": True}
    return {"unit": cls, "function": fname}


def _stub_entry(mock, writebacks, values, ctx):
    """One `stubs[]` entry. `prototype` when the stub must write values back
    through a pointer (the function reads them after the call), `faked` otherwise
    -- the user's rule of 2026-09-24, unconfirmed by the format's owner."""
    qn = mock.get("qualifiedName") or mock.get("name", "")
    name = mock.get("name", "")
    mine = [w for w in writebacks if w.get("mock") == mock.get("functionId")]
    ret_type = (mock.get("returnType") or "").strip()
    if ret_type and ret_type != "void":
        v, s = values.get(f"{name}()", (None, None))
        returns = {"value": display(v, s, ret_type)}
    else:
        # The format has `returns` on every stub (never change the format), and a
        # void stub returns nothing: an empty value says so. Whether the format
        # owner writes void this way is an open question (UT_EXPORT_READINESS).
        returns = {"value": ""}
    if mine:
        entry = {"unit": PROTOTYPE_UNIT, "function": qn, "mode": "prototype"}
    else:
        entry = {"unit": owner_of(mock.get("functionId", ""), qn), "function": name,
                 "mode": "faked"}
    entry["returns"] = returns
    if mine:
        pv = {}
        for w in mine:
            v, s = values.get(w["label"], (None, None))
            pv[f"{w['param']}.{w['field']}"] = display(v, s, w.get("type", ""))
        entry["prototype_values"] = pv
    return entry


def _input_value(name, typ, values, ctx):
    """An input's `value`: the solved scalar, a struct object from solved fields,
    or null (unset pointer / nothing chosen)."""
    fields = {k: vs for k, vs in values.items()
              if (ctx.variables.get(k) or {}).get("kind") == "pfield"
              and ctx.variables[k].get("param") == name}
    if fields:
        return {"type": bare_type(typ),
                "fields": {ctx.variables[k]["field"]: display(v, s, ctx.variables[k].get("type", ""))
                           for k, (v, s) in sorted(fields.items())}}
    v, s = values.get(name, (None, None))
    return display(v, s, typ)


def build_case(case_id, case_name, spec, solution, ctx, writebacks, review):
    """One target-format case from one of our per-path cases."""
    values = (solution or {}).get("values") or {}
    pre = spec.get("precondition") or {}
    entries = (spec.get("input") or {}).get("entries") or []
    global_ids = {g.get("name"): g.get("globalId", "") for g in pre.get("globals") or []}

    # Every parameter, in signature order: the call needs all of them, the
    # out-parameters the document lists as outputs included (a null check on
    # one is a condition like any other).
    params = pre.get("parameters") or [{"name": e.get("name", ""), "type": e.get("type", "")}
                                       for e in entries if e.get("kind") == "parameter"]
    inputs = [{"param": p.get("name", ""),
               "value": _input_value(p.get("name", ""), p.get("type", ""), values, ctx)}
              for p in params]
    pre_globals = []
    for e in entries:
        if e.get("kind") == "global":
            v, s = values.get(e.get("name", ""), (None, None))
            gid = e.get("globalId") or global_ids.get(e.get("name"), "")
            pre_globals.append({"unit": owner_of(gid, e.get("name", "")),
                                "name": e.get("name", ""),
                                "value": display(v, s, e.get("type", "")) or ""})
    stubs = [_stub_entry(m, writebacks, values, ctx) for m in pre.get("mocks") or []]
    stub_units = {s["function"] if s["mode"] == "faked" else short(s["function"]): s
                  for s in stubs}

    expected = {"return": {"value": (solution or {}).get("return"), "derived_from": ""},
                "globals": [], "class_members": [], "stub_params": []}
    exp = spec.get("expected") or {}
    after = (solution or {}).get("globals") or {}
    for g in exp.get("globals") or []:
        val = after.get(g.get("name"))
        if val is None:
            continue       # not computed on this path -- see the case's notes
        expected["globals"].append({"unit": owner_of(g.get("globalId", ""), g.get("name", "")),
                                    "name": g.get("name", ""),
                                    "value": val if isinstance(val, str) else str(val),
                                    "derived_from": ""})
    for mock_name, params in (solution or {}).get("stubCalls") or []:
        if not params:
            continue
        stub = stub_units.get(mock_name) or {}
        expected["stub_params"].append({
            "unit": stub.get("unit", ""), "function": stub.get("function", mock_name),
            "params": {p: {"value": v if isinstance(v, str) else str(v).lower()}
                       for p, v in params.items()}})

    return {"id": case_id, "name": case_name, "level": "UT", "trace": "",
            "review": dict(review), "target": _target(spec),
            "preconditions": {"globals": pre_globals}, "stubs": stubs,
            "inputs": inputs, "expected": expected}


def build_testcase_file(env_name, cases, environment):
    return {"format_version": FORMAT_VERSION,
            "environment": {"name": env_name,
                            "flags": list(environment.get("flags") or []),
                            "probepoint": list(environment.get("probepoint") or []),
                            "usercode": list(environment.get("usercode") or [])},
            "cases": cases}


# ---------------------------------------------------------------------------
# Hierarchy file
# ---------------------------------------------------------------------------

_HEADER_EXT = (".h", ".hh", ".hpp", ".hxx", ".inl")


def is_header(path):
    return os.path.splitext(path or "")[1].lower() in _HEADER_EXT


def rel_dir(path, base_path):
    """`path` relative to the project root, forward slashes; unchanged when outside."""
    p = (path or "").replace("\\", "/")
    b = (base_path or "").replace("\\", "/").rstrip("/")
    if b and (p == b or p.startswith(b + "/")):
        rel = p[len(b):].lstrip("/")
        return rel or "."
    return p


def build_hierarchy(units, *, macros_by_layer, includes_by_layer, cores_by_layer,
                    library_dirs, env_overrides, base_path=""):
    """The project's one hierarchy file, for every unit that has a test-case file.

    `units`: [{"unitKey", "file"}] -- `file` is the unit's source file (project-
    relative), a header when the unit has no source. One section per unit, one
    environment per section (the user's reading: section = unit per core).
    """
    macros, layers = {}, {}
    for u in sorted(units, key=lambda u: u["unitKey"]):
        layer, comp, unit = split_unit_key(u["unitKey"])
        core = (cores_by_layer.get(layer) or [""])[0]
        key = f"{core or layer}Macros"
        bucket = macros.setdefault(key, [])
        for d in macros_by_layer.get(layer) or []:
            text = d[2:] if d.startswith("-D") else d
            if text not in bucket:
                bucket.append(text)
        lay = layers.get(layer)
        if lay is None:
            lay = layers[layer] = {
                "searchdirectories": [rel_dir(d, base_path) for d in includes_by_layer.get(layer) or []],
                "Librarydirectories": list(library_dirs.get(layer) or []),
                "Sections": {}}
        sections = lay["Sections"]
        name = unit if unit not in sections else f"{comp}.{unit}"
        env = environment_name(u["unitKey"])
        over = (env_overrides.get(env) or {}).get("hierarchy") or {}
        f = u.get("file") or ""
        sections[name] = {
            "SectionID": u["unitKey"],
            "SectionName": name,
            "TestEnvironments": {env: {
                "EnvironmentId": env,
                "EnvironmentName": env,
                "Filename": os.path.basename(f),
                "FilePath": f,
                "CoreType": core,
                "IsHeader": is_header(f),
                "Probepoint": list(over.get("Probepoint") or []),
                "usercode": list(over.get("usercode") or []),
                "Testcase": f"{env}.json",
            }},
        }
    return {"Macros": macros, "LayerMapping": layers}


def pointer_note(name, typ, value):
    """Note for an input the target format cannot carry: a pointer that must be valid."""
    if is_pointer(typ) and value == NONNULL:
        return f"`{name}` must point at a real object; the target format has no value for that"
    return None
