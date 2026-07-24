"""Test-spec view (SWE.4): model -> output/<group>/test_specs.json.

Emits one deterministic test-spec scaffold per **public** function of each
source-backed (.cpp) unit — the Analysis-of-Requirements first cut. Everything
here is derived straight from the model (no sibling-view output, no LLM), so a
rerun on unchanged input is byte-identical (REQ-TC-07). The LLM-synthesised
fields — concrete input sets, expected values, and prose Test Steps — are left
as empty placeholders for the test-case enrichment pass (see llm_enrichment
`kind="test_case"`); this view only lays down the facts they build on.

Schema (mirrors interface_tables so the SWE.4 exporter can iterate the same
shape): {"unitNames": {unit_key: display}, <unit_key>: {name, functions: [...]}}.
See docs/spec/SWE4_SPEC.md (REQ-UT-02..09) for the contract.
"""
import json
import os

from .registry import register
from utils import get_range, log, short_name, KEY_SEP

# The first implementation emits exactly one generation method; it is a fixed
# code constant, NOT a config key (see docs/spec/SWE4_SPEC.md REQ-TC-08).
GENERATION_METHOD = "Analysis of Requirements"


def _strip_ext(name):
    if not name:
        return name
    base, ext = os.path.splitext(name)
    return base if ext else name


def _test_case_id(func):
    """Deterministic per-function Test Case ID (REQ-UT-09).

    Prefers the stable interfaceId; falls back to a sanitized qualifiedName so
    an ID exists even when a function has no interface entry.
    """
    iid = func.get("interfaceId") or ""
    if iid:
        return f"TC_{iid}"
    qn = func.get("qualifiedName") or "unknown"
    safe = "".join(ch if ch.isalnum() else "_" for ch in qn)
    return f"TC_{safe}"


def _mock_functions(func, functions_data):
    """Callees written as `name()` (REQ-UT-05). Only model-resolvable callees;
    external/library calls we cannot name are omitted. Sorted + de-duplicated."""
    names = set()
    for cid in func.get("callsIds") or []:
        callee = functions_data.get(cid)
        if not callee:
            continue
        nm = short_name(callee.get("qualifiedName", "")) or ""
        if nm:
            names.add(f"{nm}()")
    return sorted(names)


def _consumed_globals(func, global_variables_data, data_dict):
    """All globals the function reads or writes (transitively), with direction
    and declared initial value where one exists (REQ-UT-05)."""
    reads = set(func.get("readsGlobalIdsTransitive") or func.get("readsGlobalIds") or [])
    writes = set(func.get("writesGlobalIdsTransitive") or func.get("writesGlobalIds") or [])
    out = []
    for gid in sorted(reads | writes):
        g = global_variables_data.get(gid)
        if not g:
            continue
        if gid in reads and gid in writes:
            direction = "read/write"
        elif gid in writes:
            direction = "write"
        else:
            direction = "read"
        entry = {
            "globalId": gid,
            "name": short_name(g.get("qualifiedName", "")) or gid.split(KEY_SEP)[-1],
            "type": g.get("type", ""),
            "range": get_range(g.get("type", ""), data_dict),
            "direction": direction,
        }
        if g.get("value"):
            entry["value"] = g["value"]
        out.append(entry)
    return out


def _written_globals(func, global_variables_data, data_dict):
    """Globals the function writes — the state part of Expected Results (REQ-UT-08)."""
    writes = set(func.get("writesGlobalIdsTransitive") or func.get("writesGlobalIds") or [])
    out = []
    for gid in sorted(writes):
        g = global_variables_data.get(gid)
        if not g:
            continue
        entry = {
            "globalId": gid,
            "name": short_name(g.get("qualifiedName", "")) or gid.split(KEY_SEP)[-1],
            "type": g.get("type", ""),
        }
        if g.get("value"):
            entry["value"] = g["value"]
        out.append(entry)
    return out


def _build_test_specs(units_data, functions_data, global_variables_data,
                      data_dictionary=None, *, allowed_components=None):
    dd = data_dictionary or {}
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
                  for uk, u in units_data.items()}

    result = {"unitNames": unit_names}
    for unit_key, unit_info in units_data.items():
        if allowed_components:
            if KEY_SEP in unit_key and unit_key.split(KEY_SEP, 1)[0].lower() not in allowed_components:
                continue
        # Header-only units produce no spec section (mirrors SWE.3 unit scope).
        if not (unit_info.get("fileName") or "").endswith(".cpp"):
            continue
        unit_name_display = unit_info.get("name", unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key)
        specs = []
        for fid in sorted(unit_info.get("functionIds", []),
                         key=lambda x: functions_data.get(x, {}).get("location", {}).get("line", 0)):
            f = functions_data.get(fid)
            if not f:
                continue
            # Scope: public functions only (REQ-UT-02).
            if (f.get("visibility") or "").lower() == "private":
                continue
            qn = f.get("qualifiedName", "")
            name = short_name(qn)
            loc = dict(f.get("location", {}))
            if loc.get("file"):
                loc["file"] = _strip_ext(loc["file"])
            raw_params = f.get("parameters", [])
            params = [{"name": p.get("name", ""), "type": p.get("type", ""),
                       "range": get_range(p.get("type", ""), dd)} for p in raw_params]

            spec = {
                "functionId": fid,
                "interfaceId": f.get("interfaceId", ""),
                "testCaseId": _test_case_id(f),
                "name": name,
                "qualifiedName": qn,
                "unitKey": unit_key,
                "unitName": unit_name_display,
                "location": loc,
                "returnType": f.get("returnType", ""),
                "returnRange": get_range(f.get("returnType", ""), dd),
                "parameters": params,
                "generationMethod": GENERATION_METHOD,
                # Precondition (REQ-UT-05): mock callees + all params + consumed globals.
                "precondition": {
                    "mockFunctions": _mock_functions(f, functions_data),
                    "parameters": params,
                    "globals": _consumed_globals(f, global_variables_data, dd),
                },
                # Input (REQ-UT-06): VOID when parameterless; concrete sets are
                # filled by the test-case enrichment pass.
                "input": {
                    "isVoid": len(params) == 0,
                    "parameters": params,
                    "sets": [],
                },
                # Expected Results (REQ-UT-08): return + written globals; per-set
                # values filled by the enrichment pass.
                "expected": {
                    "returnType": f.get("returnType", ""),
                    "writesGlobals": _written_globals(f, global_variables_data, dd),
                    "sets": [],
                },
                # Test Steps (REQ-UT-07): descriptive prose, filled by enrichment.
                "testSteps": [],
            }
            if f.get("description"):
                spec["description"] = f["description"]
            specs.append(spec)
        result[unit_key] = {"name": unit_name_display, "functions": specs}
    result["unitNames"] = {k: unit_names[k] for k in result if k != "unitNames" and k in unit_names}
    return result


def _enrich_with_llm(test_specs, config):
    """Fill each spec's LLM-synthesised fields (input/expected sets, test steps)
    with grounded, cached test cases. Best-effort: any failure leaves the
    deterministic scaffold untouched, so the view still produces valid output.
    Runs only when summarization is enabled and a client is reachable."""
    if not (config or {}).get("llm", {}).get("summarize", True):
        return
    try:
        from llm_enrichment import get_test_cases
    except ImportError:
        return
    enriched = 0
    for key, unit in test_specs.items():
        if key == "unitNames" or not isinstance(unit, dict):
            continue
        for spec in unit.get("functions", []):
            try:
                cases = get_test_cases(spec, config)
            except Exception:  # never let enrichment break the view
                continue
            if cases.get("inputSets") or cases.get("testSteps"):
                spec["input"]["sets"] = cases.get("inputSets", [])
                spec["expected"]["sets"] = cases.get("expectedSets", [])
                spec["testSteps"] = cases.get("testSteps", [])
                enriched += 1
    if enriched:
        log("enriched %d function spec(s) with LLM test cases" % enriched, component="testSpecs")


@register("testSpecs")
def run(model, output_dir, model_dir, config):
    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    global_variables_data = model.get("globalVariables", {})
    data_dict = model.get("dataDictionary", {})
    allowed_components = {m.lower() for m in (config.get("_analyzerAllowedComponents") or [])}

    test_specs = _build_test_specs(
        units_data,
        functions_data,
        global_variables_data,
        data_dict,
        allowed_components=allowed_components,
    )
    _enrich_with_llm(test_specs, config)
    out_path = os.path.join(output_dir, "test_specs.json")
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(test_specs, f, indent=2)
    spec_count = sum(len(v.get("functions", [])) for k, v in test_specs.items() if k != "unitNames")
    unit_count = len([k for k in test_specs if k != "unitNames"])
    log("%s (%d units, %d function specs)" % (out_path, unit_count, spec_count),
        component="testSpecs")
