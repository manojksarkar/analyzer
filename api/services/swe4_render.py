"""SWE.4 render — the Software Unit Test Specification of one component, as its DOCX has it.

Builds the same {cover, toc, sections, meta} payload as ``doc_render.build_render`` from the
component's ``test_specs.json`` (the testSpecs view), chapter for chapter as
``engine/swe4_exporter.py`` writes the DOCX:

  1 Introduction                       1.1 Purpose / 1.2 Scope / 1.3 Terms
  2 Software Unit Test Specification
    2.N <Component>
      2.N.U <Unit>
        2.N.U.F <Unit>-<Function>      one ``test_spec`` section: Table A + Table B
      2.N.(U+1) Dynamic Behaviour      one ``test_spec`` section per interaction
  3 Code Metric, Coding Rule, Test Coverage
  Appendix A. Reference

A ``test_spec`` section carries the spec twice: ``test_spec`` (structured — lists, nested steps,
the step each expected result names) for the page, and ``table`` (the DOCX cell texts, Table A's
six fields then Table B's eight) so Compare diffs it like any other table. The cell texts are
the exporter's own; tests/api/test_swe4_render_matches_docx.py holds the two together.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .doc_render import _flatten_toc, _load_abbreviations, _sec, _view_json, render_config

KEY_SEP = "|"
# Top-level keys of test_specs.json that are not units (engine/views/test_specs.py).
_RESERVED = ("unitNames", "dynamicSpecs")

TABLE_A = ("Eval. Equipment Name", "Precondition", "Input", "Test Steps", "Expected Results",
           "Test Platform")
TABLE_B = ("Test Case ID", "Alias Test ID", "Priority", "Risk", "Test Method", "Test Environment",
           "Test Case Generation Method", "Linked Work Items")

NO_STEPS = "Not available (no control-flow graph for this function)"


# ── the DOCX's cell texts (engine/swe4_exporter.py) ───────────────────────────

def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i}) {t}" for i, t in enumerate(items, start=1))


def _precondition_items(pre: dict) -> dict:
    return {"mocks": list(pre.get("mockFunctions") or []),
            "parameters": [p.get("text", "") for p in pre.get("parameters") or []],
            "globals": [g.get("text", "") for g in pre.get("globals") or []]}


def _precondition_text(items: dict) -> str:
    entries = []
    if items["mocks"]:
        entries.append("Mock functions: " + ", ".join(items["mocks"]))
    if items["parameters"]:
        entries.append("Parameters: " + ", ".join(items["parameters"]))
    if items["globals"]:
        entries.append("Globals: " + ", ".join(items["globals"]))
    return _numbered(entries) if entries else "None"


def _step_numbers(entry: dict) -> list[str]:
    return list(entry.get("steps") or ([entry["step"]] if entry.get("step") else []))


def _expected_items(exp: dict) -> list[dict]:
    """Mocks first, then the cross-unit calls, the returns, and what is written — each with
    the step(s) the CFG attributed it to."""
    items: list[dict] = []
    mocks = exp.get("mockFunctions") or []
    if mocks:
        items.append({"text": "Successfully called mock functions " + ", ".join(mocks), "steps": []})
    for c in exp.get("crossUnitCalls") or []:
        items.append({"text": f"Successfully called {c.get('text', '')}", "steps": _step_numbers(c)})
    for r in exp.get("returns") or []:
        items.append({"text": r.get("text", ""), "steps": _step_numbers(r)})
    for w in (exp.get("outParameters") or []) + (exp.get("globals") or []):
        items.append({"text": f"Successfully updated {w.get('text', '')}", "steps": _step_numbers(w)})
    return items


def _expected_note(return_type: str) -> str:
    rt = (return_type or "").strip()
    if rt and rt.lower() != "void":
        return f"Not available (no control-flow graph attributed the `{rt}` return of this function)"
    return "No return value; no global side effects"


def _expected_text(items: list[dict], return_type: str) -> str:
    if not items:
        return _expected_note(return_type)
    def suffix(nums):
        return f" in step{'s' if len(nums) > 1 else ''} {', '.join(nums)}" if nums else ""
    return _numbered([f"{it['text']}{suffix(it['steps'])}" for it in items])


def _steps_text(steps: list[dict]) -> str:
    if not steps:
        return NO_STEPS
    return "\n".join(f"{'    ' * s['number'].count('.')}{s['number']}) {s['text']}" for s in steps)


# ── one spec ───────────────────────────────────────────────────────────────────

def _spec_name(spec: dict) -> str:
    return spec.get("qualifiedName") or spec.get("name", "")


def _test_spec(spec: dict, cfg: dict) -> dict:
    pre = _precondition_items(spec.get("precondition") or {})
    inputs = [e.get("text", "") for e in (spec.get("input") or {}).get("entries") or []]
    steps = [{"number": str(s.get("number", "")), "text": s.get("text", "")}
             for s in spec.get("testSteps") or []]
    expected = _expected_items(spec.get("expected") or {})
    rt = spec.get("returnType", "") or ""
    return {
        "test_case_id": spec.get("testCaseId", ""),
        "generation_method": spec.get("generationMethod", ""),
        "return_type": rt,
        "equipment": cfg.get("evalEquipmentName", "Emulator"),
        "platform": cfg.get("testPlatform", "VectorCAST"),
        "priority": cfg.get("priorityDefault", "Medium"),
        "environment": cfg.get("testEnvironment", "Emulator"),
        "precondition": pre,
        "inputs": inputs,
        "steps": steps,
        "expected": expected,
        "expected_note": None if expected else _expected_note(rt),
    }


def _table(ts: dict) -> dict:
    """Table A's six cells then Table B's eight, as the DOCX prints them."""
    a = [ts["equipment"], _precondition_text(ts["precondition"]),
         _numbered(ts["inputs"]) if ts["inputs"] else "VOID",
         _steps_text(ts["steps"]), _expected_text(ts["expected"], ts["return_type"]),
         ts["platform"]]
    b = [ts["test_case_id"], "-", ts["priority"], "-", "-", ts["environment"],
         ts["generation_method"], "-"]
    return {"headers": ["Field", "Value"],
            "rows": [[k, str(v)] for k, v in zip(TABLE_A + TABLE_B, a + b)]}


def _spec_section(sid: str, number: str, title: str, spec: dict, cfg: dict) -> dict:
    ts = _test_spec(spec, cfg)
    d = _sec(sid, number, title, 4, type="test_spec",
             content=spec.get("description") or None, table=_table(ts))
    d["test_spec"] = ts
    return d


def _sid(number: str) -> str:
    return "s4-" + number.replace(".", "-")


def _load_specs(output_reader: Optional[Any], group_dir: Optional[Path], group: str) -> dict:
    """The component's test_specs.json: Postgres first, then the version's output on disk."""
    if group_dir is not None:
        return _view_json(output_reader, group_dir, "test_specs.json") or {}
    if output_reader is not None and group:
        txt = output_reader.read_text(f"{group}/test_specs.json")
        if txt:
            try:
                return json.loads(txt)
            except ValueError:
                return {}
    return {}


# ── the document ───────────────────────────────────────────────────────────────

def build_swe4_render(doc: Any, project: Any, version: Any, group_dir: Optional[Path],
                      *, model_reader: Optional[Any] = None,
                      output_reader: Optional[Any] = None) -> dict:
    from core.config import display_name

    data = _load_specs(output_reader, group_dir, doc.group or "")
    config = render_config(version)
    cfg = ((config.get("docx") or {}).get("swe4") or {})
    intro_cfg = cfg.get("introduction") or {}
    meta_data = model_reader.load("metadata") if model_reader is not None else {}
    project_name = (meta_data or {}).get("projectName") or project.name

    by_component: dict[str, list] = {}
    for unit_key, unit in data.items():
        if unit_key in _RESERVED or not isinstance(unit, dict):
            continue
        functions = unit.get("functions") or []
        if functions:
            by_component.setdefault(unit_key.split(KEY_SEP, 1)[0], []).append(
                (unit.get("name", unit_key.split(KEY_SEP)[-1]), functions))
    dynamic = data.get("dynamicSpecs") or {}
    components = sorted(set(by_component) | set(dynamic))

    def label(comp: str) -> str:
        return display_name(comp).replace("-", " ")

    # 1 Introduction
    scope = intro_cfg.get("scopeIntro", "[Scope of the unit test specification.]").replace(
        "{project_name}", project_name)
    bullets = "\n".join(f"• {label(c)}" for c in components)
    scope_text = "\n".join(t for t in (scope, bullets, intro_cfg.get("scopeBody", "")) if t)
    abbreviations = _load_abbreviations(config)
    terms = (_sec("intro-terms", "1.3", "Terms, Abbreviations and Definitions", 2, type="table",
                  table={"headers": ["Term", "Description"],
                         "rows": [[k, v] for k, v in sorted(abbreviations.items())]})
             if abbreviations else
             _sec("intro-terms", "1.3", "Terms, Abbreviations and Definitions", 2,
                  content="[Terms, abbreviations and definitions.]"))
    intro = _sec("intro", "1", "Introduction", 1, children=[
        _sec("intro-purpose", "1.1", "Purpose", 2,
             content=intro_cfg.get("purpose", "[Purpose of this document.]").replace(
                 "{project_name}", project_name)),
        _sec("intro-scope", "1.2", "Scope", 2, content=scope_text),
        terms,
    ])

    # 2 Software Unit Test Specification
    comp_secs: list[dict] = []
    n_units = n_specs = n_dyn = 0
    mocks: set[str] = set()
    for ci, comp in enumerate(components, start=1):
        sec = f"2.{ci}"
        units = sorted(by_component.get(comp) or [], key=lambda t: t[0])
        unit_secs: list[dict] = []
        for ui, (unit_name, functions) in enumerate(units, start=1):
            num = f"{sec}.{ui}"
            specs = sorted(functions, key=lambda s: (s.get("location") or {}).get("line", 0))
            children = []
            for fi, spec in enumerate(specs, start=1):
                children.append(_spec_section(_sid(f"{num}.{fi}"), f"{num}.{fi}",
                                              f"{unit_name}-{_spec_name(spec)}", spec, cfg))
                mocks.update((spec.get("precondition") or {}).get("mockFunctions") or [])
            n_specs += len(specs)
            unit_secs.append(_sec(_sid(num), num, unit_name, 3, children=children))
        n_units += len(units)
        interactions = sorted(dynamic.get(comp) or [],
                              key=lambda s: (s.get("unitName", ""), s.get("name", "")))
        if interactions:
            num = f"{sec}.{len(units) + 1}"
            children = []
            for di, spec in enumerate(interactions, start=1):
                title = f"{spec.get('unitName', '')} - {_spec_name(spec)} ({spec.get('entryPoint', '')})"
                children.append(_spec_section(_sid(f"{num}.{di}"), f"{num}.{di}", title, spec, cfg))
                mocks.update((spec.get("precondition") or {}).get("mockFunctions") or [])
            n_dyn += len(interactions)
            unit_secs.append(_sec(_sid(num), num, "Dynamic Behaviour", 3, children=children))
        comp_secs.append(_sec(_sid(sec), sec, label(comp), 2, children=unit_secs))

    sections = [
        intro,
        _sec("test_spec", "2", "Software Unit Test Specification", 1, children=comp_secs),
        _sec("metrics", "3", "Code Metric, Coding Rule, Test Coverage", 1,
             content="[Code metrics, coding-rule compliance, and test-coverage results.]"),
        _sec("appendix-a", "Appendix A.", "Reference", 1),
    ]
    cover = {
        "project_name": project_name,
        "subtitle": "Software Unit Test Specification",
        "version": version.tag if version else doc.version_id,
        "layer": doc.layer,
        "group": doc.group,
        "standard": project.compliance_standard,
        "process": doc.process,
        "generated_at": doc.updated_at.isoformat(),
    }
    meta = {
        "pipeline_data_available": bool(data),
        "model_data_available": bool(data),
        "source": "pipeline" if data else "model",
        "layers": [doc.layer] if doc.layer else [],
        "components": components,
        "units_total": n_units,
        "functions_total": n_specs,
        "globals_total": 0,
    }
    summary = {
        "units": n_units, "function_specs": n_specs, "dynamic_specs": n_dyn,
        "mocks": len(mocks),
        "equipment": cfg.get("evalEquipmentName", "Emulator"),
        "platform": cfg.get("testPlatform", "VectorCAST"),
    }
    return {"cover": cover, "toc": _flatten_toc(sections), "sections": sections, "meta": meta,
            "test_summary": summary}
