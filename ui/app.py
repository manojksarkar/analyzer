"""
C++ Analyzer - DOCX Generator UI
Run with: streamlit run ui/app.py
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from string import Template
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from core.config import get_flat_groups as _get_flat_groups  # noqa: E402

CONFIG_JSON = ROOT / "config" / "config.json"
LAST_RUN = ROOT / "config" / "last_run.json"
PHASE_NAMES = {1: "Parse", 2: "Derive", 3: "Views", 4: "Export"}


def _pick_folder(key: str):
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    path = filedialog.askdirectory()
    root.destroy()
    if path:
        st.session_state[key] = path


def _strip_comments(text: str) -> str:
    result: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\" and i + 1 < len(text):
                result.append(c)
                i += 1
                result.append(text[i])
            elif c == '"':
                in_string = False
                result.append(c)
            else:
                result.append(c)
        else:
            if c == '"':
                in_string = True
                result.append(c)
            elif c == "/" and i + 1 < len(text) and text[i + 1] == "/":
                while i < len(text) and text[i] != "\n":
                    i += 1
                continue
            else:
                result.append(c)
        i += 1
    return "".join(result)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(_strip_comments(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _merged_config() -> dict[str, Any]:
    return _load_json(CONFIG_JSON)


def _model_roots() -> list[Path]:
    model_dir = ROOT / "model"
    if not model_dir.exists():
        return []
    roots = sorted(p for p in model_dir.iterdir() if p.is_dir() and (p / "functions.json").exists())
    return roots or [model_dir]


def _load_model_file(name: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for root in _model_roots():
        data = _load_json(root / name)
        if not isinstance(data, dict):
            continue
        if name == "components.json":
            for comp, cdata in data.items():
                if comp not in merged:
                    merged[comp] = cdata
                    continue
                for list_key in ("units", "headerFiles"):
                    existing = merged[comp].setdefault(list_key, [])
                    for item in cdata.get(list_key, []):
                        if item not in existing:
                            existing.append(item)
        else:
            merged.update(data)
    return merged


def _model_file_for_function(fid: str) -> Path:
    for root in _model_roots():
        path = root / "functions.json"
        if fid in _load_json(path):
            return path
    return ROOT / "model" / "functions.json"


def _load_last_run() -> dict[str, Any]:
    return _load_json(LAST_RUN)


def _save_last_run():
    LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN.write_text(
        json.dumps({"project_path": st.session_state.get("project_path", "")}, indent=2),
        encoding="utf-8",
    )


def _init():
    if st.session_state.get("_init_done"):
        return

    cfg = _merged_config()
    clang = cfg.get("clang", {})
    llm = cfg.get("llm", {})
    views = cfg.get("views", {})
    export = cfg.get("export", {})
    ui = cfg.get("ui", {})
    layers_raw = cfg.get("layers", {})
    sample = ROOT / "SampleCppProject"
    last = _load_last_run()

    st.session_state.setdefault("project_path", last.get("project_path") or (str(sample) if sample.exists() else ""))
    st.session_state.setdefault("ui_theme", ui.get("theme", "Dark"))
    st.session_state.setdefault("llvm_lib", clang.get("llvmLibPath", ""))
    st.session_state.setdefault("clang_include", clang.get("clangIncludePath", ""))
    args = clang.get("clangArgs", [])
    st.session_state.setdefault("clang_args", " ".join(args) if isinstance(args, list) else str(args))

    st.session_state["_layers_raw"] = layers_raw
    group_to_layer = {
        gname: lname
        for lname, ldata in layers_raw.items()
        for gname in (ldata.get("groups") or {}).keys()
    }
    st.session_state["_group_to_layer"] = group_to_layer

    gid = cid = pid = 0
    groups: list[dict[str, Any]] = []
    gid_to_layer: dict[int, str] = {}
    flat_groups = _get_flat_groups(cfg)
    default_layer = next(iter(layers_raw.keys()), "Layer1")
    for gname, mods in flat_groups.items():
        components_list = []
        for cname, paths_raw in mods.items():
            paths_raw = paths_raw if isinstance(paths_raw, list) else ([paths_raw] if paths_raw else [""])
            paths = [{"pid": pid + i, "path": p} for i, p in enumerate(paths_raw)]
            pid += len(paths)
            components_list.append({"cid": cid, "comp": cname, "paths": paths})
            cid += 1
        groups.append({"gid": gid, "name": gname, "components": components_list})
        gid_to_layer[gid] = group_to_layer.get(gname, default_layer)
        gid += 1
    st.session_state["groups"] = groups
    st.session_state["_next_gid"] = gid
    st.session_state["_next_cid"] = cid
    st.session_state["_next_pid"] = pid
    st.session_state["_gid_to_layer"] = gid_to_layer

    ud = views.get("unitDiagrams", {})
    fc = views.get("flowcharts", {})
    bd = views.get("behaviourDiagram", {})
    msd = views.get("componentStaticDiagram", {})
    st.session_state.setdefault("v_unit_png", bool(ud.get("renderPng", True)))
    st.session_state.setdefault("v_flow_png", bool(fc.get("renderPng", True)))
    st.session_state.setdefault("v_flow_script", fc.get("scriptPath", "fake_flowchart_generator.py"))
    st.session_state.setdefault("v_behav_png", bool(bd.get("renderPng", True)))
    st.session_state.setdefault("v_msd_enabled", bool(msd.get("enabled", True)))
    st.session_state.setdefault("v_msd_png", bool(msd.get("renderPng", True)))
    st.session_state.setdefault("v_msd_width", float(msd.get("widthInches", 5.5)))
    st.session_state.setdefault("export_docx_path", export.get("docxPath", "output/software_detailed_design_{group}.docx"))
    st.session_state.setdefault("export_font_size", int(export.get("docxFontSize", 8)))

    enrichment = llm.get("enrichment", {})
    st.session_state.setdefault("llm_descriptions", bool(llm.get("descriptions", False)))
    st.session_state.setdefault("llm_behav_names", bool(llm.get("behaviourNames", False)))
    st.session_state.setdefault("llm_summarize", bool(llm.get("summarize", False)))
    st.session_state.setdefault("llm_provider", llm.get("provider", "ollama"))
    st.session_state.setdefault("llm_url", llm.get("baseUrl", "http://localhost:11434"))
    st.session_state.setdefault("llm_api_key", llm.get("apiKey", ""))
    st.session_state.setdefault("llm_model", llm.get("defaultModel", "llama"))
    st.session_state.setdefault("llm_timeout", int(llm.get("timeoutSeconds", 120)))
    st.session_state.setdefault("llm_ctx", int(llm.get("numCtx", 8192)))
    st.session_state.setdefault("llm_retries", int(llm.get("retries", 1)))
    st.session_state.setdefault("llm_max_ctx_tokens", "" if llm.get("maxContextTokens") is None else str(llm.get("maxContextTokens")))
    st.session_state.setdefault("llm_few_shot_dir", llm.get("fewShotExamplesDir", "few_shot_examples"))
    st.session_state.setdefault("llm_cache_version", int(llm.get("cacheVersion", 1)))
    st.session_state.setdefault("llm_enr_two_pass", bool(enrichment.get("twoPassDescriptions", False)))
    st.session_state.setdefault("llm_enr_self_review", bool(enrichment.get("selfReview", False)))
    st.session_state.setdefault("llm_enr_ensemble", bool(enrichment.get("ensemble", False)))
    st.session_state.setdefault("llm_enr_cfg_simplify", bool(enrichment.get("cfgSimplification", False)))
    st.session_state.setdefault("llm_enr_var_enrich", bool(enrichment.get("variableEnrichment", True)))
    st.session_state.setdefault("llm_custom_headers", json.dumps(llm.get("customHeaders", {}) or {}, indent=2))
    st.session_state["_init_done"] = True


def _add_group():
    gid = st.session_state["_next_gid"]
    cid = st.session_state["_next_cid"]
    pid = st.session_state["_next_pid"]
    st.session_state["groups"].append({"gid": gid, "name": "", "components": [{"cid": cid, "comp": "", "paths": [{"pid": pid, "path": ""}]}]})
    layers_raw = st.session_state.get("_layers_raw", {})
    st.session_state.setdefault("_gid_to_layer", {})[gid] = next(iter(layers_raw.keys()), "Layer1")
    st.session_state["_next_gid"] = gid + 1
    st.session_state["_next_cid"] = cid + 1
    st.session_state["_next_pid"] = pid + 1


def _remove_group(gid: int):
    st.session_state["groups"] = [g for g in st.session_state["groups"] if g["gid"] != gid]


def _add_component(gid: int):
    cid = st.session_state["_next_cid"]
    pid = st.session_state["_next_pid"]
    for group in st.session_state["groups"]:
        if group["gid"] == gid:
            group["components"].append({"cid": cid, "comp": "", "paths": [{"pid": pid, "path": ""}]})
    st.session_state["_next_cid"] = cid + 1
    st.session_state["_next_pid"] = pid + 1


def _remove_component(gid: int, cid: int):
    for group in st.session_state["groups"]:
        if group["gid"] == gid:
            group["components"] = [c for c in group["components"] if c["cid"] != cid]


def _add_path(cid: int):
    pid = st.session_state["_next_pid"]
    for group in st.session_state["groups"]:
        for comp in group["components"]:
            if comp["cid"] == cid:
                comp["paths"].append({"pid": pid, "path": ""})
    st.session_state["_next_pid"] = pid + 1


def _remove_path(cid: int, pid: int):
    for group in st.session_state["groups"]:
        for comp in group["components"]:
            if comp["cid"] == cid:
                comp["paths"] = [p for p in comp["paths"] if p["pid"] != pid]


def _groups_to_layers_config() -> dict[str, Any]:
    layers_raw = st.session_state.get("_layers_raw", {})
    gid_to_layer = st.session_state.get("_gid_to_layer", {})
    result = {lname: {"path": ldata.get("path", lname), "groups": {}} for lname, ldata in layers_raw.items()}
    if not result:
        result["Layer1"] = {"path": "Layer1", "groups": {}}
    default_layer = next(iter(result.keys()))
    for group in st.session_state.get("groups", []):
        gid = group["gid"]
        gname = st.session_state.get(f"g{gid}_name", group["name"]).strip()
        if not gname:
            continue
        comps: dict[str, Any] = {}
        for comp in group["components"]:
            cid = comp["cid"]
            cname = st.session_state.get(f"c{cid}_name", comp["comp"]).strip()
            if not cname:
                continue
            paths = [st.session_state.get(f"p{p['pid']}_path", p["path"]).strip() for p in comp["paths"]]
            paths = [p for p in paths if p]
            if paths:
                comps[cname] = paths[0] if len(paths) == 1 else paths
        if not comps:
            continue
        lname = gid_to_layer.get(gid, default_layer)
        if lname not in result:
            lname = default_layer
        prefix = result[lname]["path"].rstrip("/") + "/"

        def strip_layer(path: str) -> str:
            return path[len(prefix):] if path.startswith(prefix) else path

        result[lname]["groups"][gname] = {
            cname: [strip_layer(p) for p in value] if isinstance(value, list) else strip_layer(value)
            for cname, value in comps.items()
        }
    return result


def _write_config():
    cfg: dict[str, Any] = {}
    clang: dict[str, Any] = {}
    if st.session_state.get("llvm_lib", "").strip():
        clang["llvmLibPath"] = st.session_state["llvm_lib"].strip()
    if st.session_state.get("clang_include", "").strip():
        clang["clangIncludePath"] = st.session_state["clang_include"].strip()
    args = [a for a in st.session_state.get("clang_args", "").split() if a]
    if args:
        clang["clangArgs"] = args
    if clang:
        cfg["clang"] = clang

    cfg["views"] = {
        "interfaceTables": True,
        "unitDiagrams": {"renderPng": st.session_state["v_unit_png"]},
        "flowcharts": {**( {"scriptPath": st.session_state["v_flow_script"]} if st.session_state.get("v_flow_script", "").strip() else {}), "renderPng": st.session_state["v_flow_png"]},
        "behaviourDiagram": {"renderPng": st.session_state["v_behav_png"]},
        "componentStaticDiagram": {"enabled": st.session_state["v_msd_enabled"], "renderPng": st.session_state["v_msd_png"], "widthInches": st.session_state["v_msd_width"]},
    }
    cfg["export"] = {
        "docxPath": st.session_state.get("export_docx_path", "").strip() or "output/software_detailed_design_{group}.docx",
        "docxFontSize": st.session_state["export_font_size"],
    }
    cfg["layers"] = _groups_to_layers_config()

    provider = st.session_state.get("llm_provider", "ollama")
    llm_block: dict[str, Any] = {
        "descriptions": st.session_state.get("llm_descriptions", False),
        "behaviourNames": st.session_state.get("llm_behav_names", False),
        "summarize": st.session_state.get("llm_summarize", False),
        "provider": provider,
        "baseUrl": st.session_state.get("llm_url", "").strip() or "http://localhost:11434",
        "defaultModel": st.session_state.get("llm_model", "").strip() or "llama",
        "timeoutSeconds": st.session_state.get("llm_timeout", 120),
        "numCtx": st.session_state.get("llm_ctx", 8192),
        "retries": st.session_state.get("llm_retries", 1),
        **({"fewShotExamplesDir": st.session_state["llm_few_shot_dir"]} if st.session_state.get("llm_few_shot_dir", "").strip() else {}),
        "cacheVersion": st.session_state.get("llm_cache_version", 1),
        "enrichment": {
            "twoPassDescriptions": st.session_state.get("llm_enr_two_pass", False),
            "selfReview": st.session_state.get("llm_enr_self_review", False),
            "ensemble": st.session_state.get("llm_enr_ensemble", False),
            "cfgSimplification": st.session_state.get("llm_enr_cfg_simplify", False),
            "variableEnrichment": st.session_state.get("llm_enr_var_enrich", True),
        },
    }
    max_ctx = (st.session_state.get("llm_max_ctx_tokens") or "").strip()
    llm_block["maxContextTokens"] = int(max_ctx) if max_ctx.isdigit() else None
    if provider == "openai":
        llm_block["apiKey"] = st.session_state.get("llm_api_key", "")
    try:
        headers = json.loads(st.session_state.get("llm_custom_headers", "{}") or "{}")
    except json.JSONDecodeError:
        headers = {}
    if headers:
        llm_block["customHeaders"] = headers
    cfg["llm"] = llm_block
    cfg["ui"] = {"theme": st.session_state.get("ui_theme", "Dark")}

    CONFIG_JSON.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _save_last_run()


@st.cache_resource
def _get_runs() -> dict[str, Any]:
    return {}


def _run_state() -> dict[str, Any]:
    runs = _get_runs()
    sid = st.session_state.setdefault("_sid", str(uuid.uuid4()))
    runs.setdefault(sid, {"lines": [], "running": False, "returncode": None, "proc": None, "cmd": ""})
    return runs[sid]


def _pipeline_thread(cmd: list[str], sid: str):
    state = _get_runs()[sid]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT), bufsize=1)
        state["proc"] = proc
        for raw in iter(proc.stdout.readline, ""):
            state["lines"].append(raw.rstrip())
        proc.wait()
        state["returncode"] = proc.returncode
    except Exception as exc:
        state["lines"].append(f"ERROR: {exc}")
        state["returncode"] = -1
    finally:
        state["running"] = False


def _start_pipeline(cmd: list[str], run_type: str):
    state = _run_state()
    state.update(lines=[], running=True, returncode=None, proc=None, cmd=" ".join(cmd))
    st.session_state["_run_type"] = run_type
    st.session_state["_switch_to_log"] = True
    threading.Thread(target=_pipeline_thread, args=(cmd, st.session_state["_sid"]), daemon=True).start()


def _stop_pipeline():
    state = _run_state()
    proc = state.get("proc")
    if proc:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        except Exception:
            proc.kill()
    state.update(running=False, returncode=-1)
    state["lines"].append("-- stopped by user --")


def _run_full(selected_group: str | None):
    project_path = (st.session_state.get("project_path") or "").strip()
    if not project_path or not Path(project_path).exists():
        st.error("Invalid project path")
        return
    _write_config()
    cmd = [sys.executable, str(ROOT / "run.py")]
    if selected_group:
        cmd += ["--selected-group", selected_group]
    cmd.append(project_path)
    _start_pipeline(cmd, "full")


def _run_export(selected_group: str | None):
    project_path = (st.session_state.get("project_path") or "").strip()
    if not project_path or not Path(project_path).exists():
        st.error("Invalid project path")
        return
    _write_config()
    cmd = [sys.executable, str(ROOT / "run.py"), "--from-phase", "4", "--use-model"]
    if selected_group:
        cmd += ["--selected-group", selected_group]
    cmd.append(project_path)
    _start_pipeline(cmd, "export")


def _save_function_description(fid: str, description: str):
    funcs_path = _model_file_for_function(fid)
    funcs = _load_json(funcs_path)
    if fid in funcs:
        funcs[fid]["description"] = description
        funcs_path.write_text(json.dumps(funcs, indent=2), encoding="utf-8")
    output_dir = ROOT / "output"
    for iface_path in output_dir.rglob("interface_tables.json") if output_dir.exists() else []:
        iface = _load_json(iface_path)
        changed = False
        for key, unit in iface.items():
            if key == "unitNames" or not isinstance(unit, dict):
                continue
            for entry in unit.get("entries", []):
                if entry.get("functionId") == fid:
                    entry["description"] = description
                    changed = True
        if changed:
            iface_path.write_text(json.dumps(iface, indent=2), encoding="utf-8")


@st.dialog("Function", width="large")
def _function_dialog(fid: str, units_all: dict[str, Any], funcs_all: dict[str, Any]):
    entry = funcs_all.get(fid)
    if not entry:
        st.info("No data for this function.")
        return
    parts = fid.split("|")
    fname = entry.get("qualifiedName", parts[2] if len(parts) > 2 else fid)
    params = entry.get("parameters", [])
    sig_params = []
    for param in params:
        sig_params.append(f"{param.get('type', '')} {param.get('name', '')}".strip() if isinstance(param, dict) else str(param))
    signature = f"{entry.get('returnType', '')} {fname}({', '.join(sig_params)})"
    st.markdown(f"### `{fname}`")
    pills = [entry.get("interfaceId"), entry.get("direction"), entry.get("visibility")]
    st.caption("  |  ".join(p for p in pills if p))
    left, right = st.columns([1.1, 1.8], gap="medium")
    with left:
        st.code(signature, language="cpp")
        desc = st.text_area("Description", value=entry.get("description", ""), height=130, key=f"desc_{fid}")
        if st.button("Save", key=f"save_{fid}", type="primary"):
            _save_function_description(fid, desc)
            st.success("Saved")
        calls = [c.split("|")[2] for c in entry.get("callsIds", []) if "|" in c]
        called_by = [c.split("|")[2] for c in entry.get("calledByIds", []) if "|" in c]
        if calls:
            st.caption("Calls")
            st.write(", ".join(calls))
        if called_by:
            st.caption("Called by")
            st.write(", ".join(called_by))
    with right:
        unit_name = ""
        for unit in units_all.values():
            if fid in unit.get("functionIds", []):
                unit_name = unit.get("name", "")
                break
        fname2 = parts[2] if len(parts) > 2 else ""
        matches = sorted((ROOT / "output").glob(f"*/flowcharts/{unit_name}_{fname2}.png")) if unit_name and fname2 else []
        png_path = matches[0] if matches else None
        st.markdown("**Flowchart**")
        if png_path:
            img_b64 = base64.b64encode(png_path.read_bytes()).decode()
            components.html(
                f"""
                <div style="height:520px;background:#0d0d11;border:1px solid rgba(255,255,255,0.07);border-radius:8px;overflow:auto;display:flex;align-items:center;justify-content:center;">
                    <img src="data:image/png;base64,{img_b64}" style="max-width:100%;max-height:100%;">
                </div>
                """,
                height=540,
            )
        else:
            st.info("No flowchart available for this function.")



def _set_group_dialog_index(index: int):
    st.session_state["_group_dialog_index"] = index


@st.dialog("Component Groups", width="large")
def _groups_dialog():
    groups = st.session_state.get("groups", [])
    st.session_state.setdefault("_group_dialog_index", 0)
    selected = min(st.session_state["_group_dialog_index"], max(0, len(groups) - 1))
    st.session_state["_group_dialog_index"] = selected
    left, right = st.columns([1, 2.5], gap="medium")
    with left:
        st.caption("Groups")
        for i, group in enumerate(groups):
            gid = group["gid"]
            name = st.session_state.get(f"g{gid}_name", group["name"]).strip() or "(unnamed)"
            meta = f"{len(group['components'])} comps"
            layer = st.session_state.get("_gid_to_layer", {}).get(gid)
            if layer:
                meta += f" | {layer}"
            st.button(f"{name}  |  {meta}", key=f"group_select_{i}", type="primary" if selected == i else "secondary", on_click=_set_group_dialog_index, args=(i,), use_container_width=True)
        st.divider()
        st.button("+ Add Group", on_click=_add_group, use_container_width=True)
    with right:
        if not groups:
            st.info("No groups yet.")
        else:
            group = groups[selected]
            gid = group["gid"]
            h1, h2 = st.columns([4, 1])
            with h1:
                st.text_input("Group name", key=f"g{gid}_name", value=group["name"], label_visibility="collapsed")
            with h2:
                if st.button("Delete", key=f"delete_group_{gid}"):
                    _remove_group(gid)
                    st.rerun()
            st.divider()
            for comp in group["components"]:
                cid = comp["cid"]
                with st.expander(st.session_state.get(f"c{cid}_name", comp["comp"]).strip() or "(unnamed)", expanded=True):
                    c1, c2 = st.columns([4, 1])
                    c1.text_input("Component", key=f"c{cid}_name", value=comp["comp"], label_visibility="collapsed")
                    c2.button("-", key=f"delete_comp_{cid}", on_click=_remove_component, args=(gid, cid))
                    for path in comp["paths"]:
                        pid = path["pid"]
                        p1, p2 = st.columns([5, 1])
                        p1.text_input("Path", key=f"p{pid}_path", value=path["path"], label_visibility="collapsed")
                        p2.button("x", key=f"delete_path_{pid}", on_click=_remove_path, args=(cid, pid), disabled=len(comp["paths"]) <= 1)
                    st.button("+ path", key=f"add_path_{cid}", on_click=_add_path, args=(cid,))
            st.button("+ component", key=f"add_comp_{gid}", on_click=_add_component, args=(gid,), use_container_width=True)
    st.divider()
    if st.button("Save", type="primary", use_container_width=True):
        _write_config()
        st.rerun()


def _set_settings_nav(nav: str):
    st.session_state["_settings_nav"] = nav


@st.dialog("Settings", width="large")
def _settings_dialog():
    st.session_state.setdefault("_settings_nav", "LLM")
    nav = st.session_state["_settings_nav"]
    nav_col, content_col = st.columns([1, 3], gap="medium")
    with nav_col:
        for section in ("Appearance", "LLM", "Parser", "Views & Export", "Config"):
            st.button(section, key=f"settings_{section}", type="primary" if nav == section else "secondary", on_click=_set_settings_nav, args=(section,), use_container_width=True)
    with content_col:
        if nav == "Appearance":
            st.markdown("**Theme**")
            st.radio("Theme", ["Dark", "Light"], key="ui_theme", horizontal=True, label_visibility="collapsed")
        elif nav == "LLM":
            st.markdown("**Features**")
            f1, f2, f3 = st.columns(3)
            f1.toggle("Descriptions", key="llm_descriptions")
            f2.toggle("Behaviour names", key="llm_behav_names")
            f3.toggle("Call-graph summary", key="llm_summarize")
            st.markdown("**Connection**")
            c1, c2 = st.columns([1, 2])
            c1.radio("Provider", ["ollama", "openai"], key="llm_provider")
            c2.text_input("Model", key="llm_model")
            st.text_input("Base URL", key="llm_url")
            if st.session_state.get("llm_provider") == "openai":
                st.text_input("API Key", key="llm_api_key", type="password")
            with st.expander("Advanced"):
                a1, a2, a3 = st.columns(3)
                a1.number_input("Timeout", key="llm_timeout", min_value=10)
                a2.number_input("Retries", key="llm_retries", min_value=0, max_value=10)
                a3.number_input("Context", key="llm_ctx", min_value=512)
                st.text_input("Max tokens", key="llm_max_ctx_tokens")
                e1, e2, e3 = st.columns(3)
                e1.checkbox("Two-pass", key="llm_enr_two_pass")
                e1.checkbox("Self-review", key="llm_enr_self_review")
                e2.checkbox("Ensemble", key="llm_enr_ensemble")
                e2.checkbox("CFG simplify", key="llm_enr_cfg_simplify")
                e3.checkbox("Variable enrichment", key="llm_enr_var_enrich")
                st.text_input("Few-shot dir", key="llm_few_shot_dir")
                st.number_input("Cache version", key="llm_cache_version", min_value=1)
                st.text_area("Custom headers (JSON)", key="llm_custom_headers", height=80)
        elif nav == "Parser":
            st.text_input("LLVM lib", key="llvm_lib")
            st.text_input("Clang include", key="clang_include")
            st.text_input("Extra args", key="clang_args")
        elif nav == "Views & Export":
            d1, d2 = st.columns(2)
            d1.toggle("Unit PNG", key="v_unit_png")
            d1.toggle("Flowchart PNG", key="v_flow_png")
            d1.text_input("Flowchart script", key="v_flow_script")
            d2.toggle("Behaviour PNG", key="v_behav_png")
            d2.toggle("Static diagram", key="v_msd_enabled")
            d2.toggle("Static PNG", key="v_msd_png")
            d2.number_input("Static width", key="v_msd_width", min_value=1.0, max_value=20.0, step=0.5)
            st.divider()
            st.text_input("DOCX path", key="export_docx_path")
            st.number_input("Font size", key="export_font_size", min_value=6, max_value=16)
        else:
            st.json(_merged_config())
    st.divider()
    if st.button("Save settings", type="primary", use_container_width=True):
        _write_config()
        st.rerun()


st.set_page_config(page_title="C++ Analyzer", page_icon="C", layout="wide")
_init()

_theme = st.session_state.get("ui_theme", "Dark")
if _theme == "Light":
    _colors = {
        "app_bg": "#f5f5f7",
        "side_bg": "#ffffff",
        "top_bg": "#ffffff",
        "tab_bg": "#ffffff",
        "row_bg": "#eeeef1",
        "text": "#18181b",
        "muted": "rgba(24,24,27,0.45)",
        "faint": "rgba(24,24,27,0.30)",
        "border": "rgba(0,0,0,0.08)",
        "border_soft": "rgba(0,0,0,0.05)",
        "control_bg": "#ffffff",
        "input_bg": "#f4f4f6",
        "hover_bg": "rgba(99,102,241,0.06)",
        "status_bg": "#ffffff",
        "panel_bg": "#f4f4f6",
    }
else:
    _colors = {
        "app_bg": "#0a0a0c",
        "side_bg": "#111115",
        "top_bg": "#111115",
        "tab_bg": "#0f0f12",
        "row_bg": "#131318",
        "text": "#e4e4e7",
        "muted": "rgba(228,228,231,0.45)",
        "faint": "rgba(228,228,231,0.30)",
        "border": "rgba(255,255,255,0.08)",
        "border_soft": "rgba(255,255,255,0.05)",
        "control_bg": "transparent",
        "input_bg": "rgba(255,255,255,0.04)",
        "hover_bg": "rgba(255,255,255,0.035)",
        "status_bg": "#0d0d10",
        "panel_bg": "#0d0d10",
    }

st.markdown(
    Template("""
<style>
:root {
  --app-bg:$app_bg;
  --side-bg:$side_bg;
  --top-bg:$top_bg;
  --tab-bg:$tab_bg;
  --row-bg:$row_bg;
  --text:$text;
  --muted:$muted;
  --faint:$faint;
  --border:$border;
  --border-soft:$border_soft;
  --control-bg:$control_bg;
  --input-bg:$input_bg;
  --hover-bg:$hover_bg;
  --status-bg:$status_bg;
  --panel-bg:$panel_bg;
  --primary-color:#6366f1 !important;
}
/* ── hide native chrome ── */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeaderActionElements"] { display:none !important; }
/* ── app shell ── */
section.main, [data-testid="stMain"] { background:var(--app-bg) !important; overflow:hidden !important; }
.block-container, [data-testid="stMainBlockContainer"] { max-width:100% !important; padding:3.25rem 0 1.5rem 0 !important; background:transparent !important; }
/* ── two-column layout ── */
[data-testid="stHorizontalBlock"] { gap:0 !important; align-items:stretch !important; }
[data-testid="stHorizontalBlock"] > div:first-child { background:var(--side-bg) !important; border-right:1px solid var(--border) !important; min-height:calc(100vh - 3.25rem) !important; max-height:calc(100vh - 3.25rem) !important; overflow-y:auto !important; padding:0.75rem 0.875rem 3rem !important; box-sizing:border-box !important; }
[data-testid="stHorizontalBlock"] > div:last-child { background:var(--app-bg) !important; min-height:calc(100vh - 3.25rem) !important; max-height:calc(100vh - 3.25rem) !important; overflow:hidden !important; padding:0 !important; }
[data-testid="stHorizontalBlock"] > div:last-child [role="tabpanel"] { max-height:calc(100vh - 7rem) !important; overflow-y:auto !important; padding-bottom:2rem !important; }
/* ── sidebar section labels ── */
[data-testid="stCaptionContainer"] p { font-size:9px !important; font-weight:700 !important; letter-spacing:1.5px !important; text-transform:uppercase !important; color:var(--faint) !important; margin:0.85rem 0 0.3rem !important; }
/* ── sidebar dividers ── */
[data-testid="stHorizontalBlock"] > div:first-child hr { border-color:var(--border-soft) !important; margin:0.5rem 0 !important; }
/* ── selectbox ── */
[data-baseweb="select"] > div { background:var(--input-bg) !important; border-color:var(--border) !important; color:var(--text) !important; }
[data-baseweb="select"] span { color:var(--text) !important; }
[data-baseweb="select"] svg { color:var(--muted) !important; fill:var(--muted) !important; }
/* ── tabs ── */
[data-baseweb="tab-list"] { background:var(--tab-bg) !important; border-bottom:1px solid var(--border) !important; height:42px !important; padding:0 1.5rem !important; gap:1.5rem !important; }
[data-baseweb="tab"] { height:42px !important; color:var(--muted) !important; font-size:0.82rem !important; font-weight:500 !important; padding:0 !important; }
[data-baseweb="tab"][aria-selected="true"] { color:var(--text) !important; }
[data-baseweb="tab-highlight"] { background:#6366f1 !important; height:2px !important; }
/* ── generic buttons ── */
button[kind="primary"], button[kind="primaryFormSubmit"] { background:#6366f1 !important; border-color:#6366f1 !important; color:#fff !important; }
button[kind="secondary"] { background:var(--control-bg) !important; border:1px solid var(--border) !important; color:var(--text) !important; }
button[kind="secondary"]:hover { border-color:var(--muted) !important; color:var(--text) !important; background:var(--hover-bg) !important; }
input, textarea { background:var(--input-bg) !important; border-color:var(--border) !important; color:var(--text) !important; }
/* ── group expander (tree header row) ── */
[role="tabpanel"] [data-testid="stExpander"] { border:0 !important; border-radius:0 !important; background:transparent !important; box-shadow:none !important; margin:0 0 2px 0 !important; }
[role="tabpanel"] [data-testid="stExpander"] > details > summary { background:var(--row-bg) !important; border-radius:0 !important; border-bottom:1px solid var(--border-soft) !important; height:36px !important; min-height:36px !important; padding:0 1rem 0 2rem !important; color:var(--text) !important; font-size:0.72rem !important; font-weight:700 !important; text-transform:uppercase !important; letter-spacing:0.1em !important; display:flex !important; align-items:center !important; }
[role="tabpanel"] [data-testid="stExpander"] > details > summary:hover { background:color-mix(in srgb, var(--row-bg) 85%, white 15%) !important; }
[role="tabpanel"] [data-testid="stExpander"] > details > summary > span { display:flex !important; align-items:center !important; gap:0.5rem !important; }
/* colored diamond marker per group index */
[role="tabpanel"] [data-testid="stExpander"] > details > summary::before { content:"◆"; font-size:7px; margin-right:6px; color:#6366f1; }
/* count badge after group name */
[role="tabpanel"] [data-testid="stExpander"] > details > summary > span:last-child { background:rgba(99,102,241,0.15) !important; color:rgba(99,102,241,0.9) !important; font-size:9px !important; font-weight:700 !important; border-radius:8px !important; padding:1px 7px !important; margin-left:6px !important; letter-spacing:0 !important; }
/* ── component rows ── */
[class*="st-key-comp_"] button { background:transparent !important; border:0 !important; border-bottom:1px solid var(--border-soft) !important; border-radius:0 !important; color:var(--muted) !important; display:flex !important; justify-content:space-between !important; align-items:center !important; text-align:left !important; padding:0 1.25rem 0 2.5rem !important; height:34px !important; min-height:34px !important; width:100% !important; }
[class*="st-key-comp_"] button p { text-align:left !important; flex:1 !important; }
[class*="st-key-comp_"] button::before { content:"◇"; font-size:11px; color:var(--faint); position:absolute; left:1.25rem; }
[class*="st-key-comp_"] button::after { content:"›"; font-size:14px; color:var(--faint); margin-left:auto; flex-shrink:0; }
[class*="st-key-comp_"] button:hover { background:var(--hover-bg) !important; color:var(--text) !important; }
[class*="st-key-comp_"] button:hover::after { color:var(--muted); }
/* ── Run / Export / Stop — sidebar action buttons ── */
[class*="st-key-_run_trigger"] button, [class*="st-key-_stop_btn"] button { height:38px !important; min-height:38px !important; border-radius:8px !important; font-size:0.84rem !important; font-weight:600 !important; letter-spacing:0.01em !important; }
[class*="st-key-_export_trigger"] button { height:38px !important; min-height:38px !important; border-radius:8px !important; font-size:0.84rem !important; background:transparent !important; border:1px solid var(--border) !important; color:var(--muted) !important; }
[class*="st-key-_export_trigger"] button:hover { border-color:var(--muted) !important; color:var(--text) !important; background:var(--hover-bg) !important; }
/* ── settings FAB (top-right header) ── */
.st-key-_settings_fab { position:fixed !important; top:12px !important; right:16px !important; z-index:100000 !important; height:0 !important; overflow:visible !important; }
.st-key-_settings_fab button { width:30px !important; height:30px !important; min-height:30px !important; border-radius:6px !important; padding:0 !important; background:transparent !important; border:none !important; color:var(--muted) !important; font-size:1.1rem !important; }
.st-key-_settings_fab button:hover { color:var(--text) !important; background:var(--hover-bg) !important; }
/* ── theme toggle (bottom-right status bar) ── */
.st-key-_theme_toggle { position:fixed !important; bottom:0 !important; right:0 !important; height:0 !important; z-index:100001 !important; overflow:visible !important; }
.st-key-_theme_toggle button { height:28px !important; min-height:28px !important; background:transparent !important; border:none !important; color:var(--muted) !important; font-size:10.5px !important; padding:0 12px !important; border-radius:0 !important; transform:translateY(-28px) !important; display:block !important; }
.st-key-_theme_toggle button:hover { color:var(--text) !important; background:transparent !important; }
/* ── inner tab-panel columns: reset outer sidebar bleed-through ── */
[role="tabpanel"] [data-testid="stHorizontalBlock"] > div { background:transparent !important; border:none !important; min-height:auto !important; max-height:none !important; overflow:visible !important; padding:0 !important; }
[role="tabpanel"] [data-testid="stHorizontalBlock"] > div:last-child { background:var(--panel-bg) !important; border-left:1px solid var(--border) !important; overflow-y:auto !important; max-height:calc(100vh - 7rem) !important; }
/* ── visibility filter — pill-style segmented control ── */
[class*="st-key-_fn_vis_filter"] { padding:0.45rem 1rem 0.35rem; border-bottom:1px solid var(--border); }
[class*="st-key-_fn_vis_filter"] [data-testid="stRadio"] > div { display:flex !important; gap:4px !important; flex-direction:row !important; }
[class*="st-key-_fn_vis_filter"] [data-testid="stRadio"] label { display:flex !important; align-items:center !important; justify-content:center !important; height:24px !important; padding:0 10px !important; border-radius:5px !important; cursor:pointer !important; font-size:0.72rem !important; font-weight:500 !important; border:1px solid var(--border) !important; color:var(--muted) !important; background:transparent !important; gap:0 !important; }
[class*="st-key-_fn_vis_filter"] [data-testid="stRadio"] label:has(input:checked) { background:#6366f1 !important; color:#fff !important; border-color:#6366f1 !important; }
[class*="st-key-_fn_vis_filter"] [data-testid="stRadio"] label:hover:not(:has(input:checked)) { border-color:var(--muted) !important; color:var(--text) !important; }
[class*="st-key-_fn_vis_filter"] [data-testid="stRadio"] label > span:first-child { display:none !important; }
[class*="st-key-_fn_vis_filter"] [data-testid="stRadio"] label > div { display:none !important; }
[class*="st-key-_fn_vis_filter"] [data-testid="stRadio"] label > p { font-size:0.72rem !important; font-weight:500 !important; margin:0 !important; }
/* ── function rows in detail panel ── */
[class*="st-key-fn_"] button { background:var(--input-bg) !important; border:1px solid var(--border) !important; border-radius:6px !important; color:var(--muted) !important; text-align:left !important; justify-content:flex-start !important; padding:0 1rem !important; height:32px !important; min-height:32px !important; font-size:0.78rem !important; width:100% !important; }
[class*="st-key-fn_"] button p, [class*="st-key-fn_"] button * { text-align:left !important; }
[class*="st-key-fn_"] button:hover { border-color:var(--muted) !important; color:var(--text) !important; background:var(--hover-bg) !important; }
/* ── dialog ── */
div[role="dialog"] { max-width:min(95vw, 1400px) !important; width:min(95vw, 1400px) !important; }
</style>
""").safe_substitute(**_colors),
    unsafe_allow_html=True,
)

_rs = _run_state()
running = _rs["running"]
log_lines: list[str] = _rs["lines"]
returncode = _rs["returncode"]

_proj_crumb = Path((st.session_state.get("project_path") or "")).name or ""
st.markdown(
    f"""
<div id="v3-md-header" style="position:fixed;top:0;left:0;right:0;height:52px;background:{_colors["top_bg"]};border-bottom:1px solid {_colors["border"]};z-index:99999;font-family:'Segoe UI',system-ui,sans-serif;display:flex;align-items:center;padding:0 56px 0 16px;box-sizing:border-box;">
  <div style="width:24px;height:24px;background:#6366f1;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:800;flex-shrink:0;">C</div>
  <div style="font-size:14px;font-weight:700;color:{_colors["text"]};margin-left:12px;white-space:nowrap;letter-spacing:-0.2px;">C++ Analyzer</div>
  {"" if not _proj_crumb else f'<div style="width:1px;height:16px;background:{_colors["border"]};margin:0 12px;flex-shrink:0;"></div><div style="font-size:12px;color:{_colors["muted"]};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:300px;">{_proj_crumb}</div>'}
</div>
""",
    unsafe_allow_html=True,
)

col_left, col_right = st.columns([5, 17])

with col_left:
    # ── 1 · PROJECT PATH ──
    st.caption("Project path")
    project_value = (st.session_state.get("project_path") or "").strip()
    project_name = Path(project_value).name if project_value else "-"
    st.markdown(
        f'<div style="background:{_colors["input_bg"]};border:1px solid {_colors["border"]};border-radius:7px;padding:0.42rem 0.75rem;font-size:10.5px;color:{_colors["muted"]};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{project_value}">.../{project_name}</div>',
        unsafe_allow_html=True,
    )
    st.button("Browse...", key="_browse_project", on_click=_pick_folder, args=("project_path",), use_container_width=True)

    st.divider()

    # ── 2 · GROUP ──
    group_names = [st.session_state.get(f"g{g['gid']}_name", g["name"]).strip() for g in st.session_state.get("groups", [])]
    group_names = [g for g in group_names if g]
    st.caption("Group")
    selected = st.selectbox("Select group", ["All"] + group_names if group_names else ["All"], key="export_group_sel", label_visibility="collapsed")
    st.button("✎ Edit groups", key="_edit_groups_btn", on_click=_groups_dialog, use_container_width=True)
    selected_group = None if selected == "All" else selected

    st.divider()

    # ── 3 · STATUS ──
    if running:
        dot, label = "#f59e0b", "Running"
    elif returncode == 0:
        dot, label = "#22c55e", "Done"
    elif returncode is not None:
        dot, label = "#ef4444", "Failed"
    else:
        dot, label = "#22c55e", "Ready"
    st.caption("Status")
    st.markdown(
        f'<div style="display:inline-flex;align-items:center;gap:7px;background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);border-radius:11px;padding:0.28rem 0.75rem;"><span style="width:7px;height:7px;border-radius:50%;background:{dot};"></span><span style="font-size:0.78rem;font-weight:600;color:{dot};">{label}</span></div>',
        unsafe_allow_html=True,
    )
    if running:
        log_text = "\n".join(log_lines)
        phases_done = sum(f"Phase {n}" in log_text for n in [1, 2, 3, 4])
        st.progress(phases_done / 4)
        st.caption(PHASE_NAMES.get(min(phases_done + 1, 4), ""))

    st.divider()

    # ── 4 · ACTIONS ──
    if running:
        st.button("⏹  Stop", key="_stop_btn", on_click=_stop_pipeline, use_container_width=True)
    else:
        st.button("▶  Run", key="_run_trigger", type="primary", on_click=lambda: _run_full(selected_group), use_container_width=True)
        st.button("↑  Export DOCX", key="_export_trigger", type="secondary", on_click=lambda: _run_export(selected_group), use_container_width=True)

    # ── 5 · OUTPUT ──
    docx_files = sorted((ROOT / "output").rglob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True) if (ROOT / "output").exists() else []
    if docx_files:
        st.divider()
        st.caption("Output")
        for docx in docx_files:
            with open(docx, "rb") as fh:
                st.download_button(docx.name, fh, file_name=docx.name, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", key=f"download_{docx}", use_container_width=True)

    _all_groups = st.session_state.get("groups", [])
    _total_comps = sum(len(g["components"]) for g in _all_groups)
    _sb_group_txt = selected_group or "All groups"
    st.markdown(
        f'<div id="v2-status-bar" style="position:fixed;bottom:0;left:0;right:0;height:28px;background:{_colors["status_bg"]};border-top:1px solid {_colors["border"]};display:flex;align-items:center;padding:0 16px;box-sizing:border-box;font-family:\'Segoe UI\',system-ui,sans-serif;font-size:10.5px;z-index:9998;pointer-events:none;">'
        f'<span style="width:7px;height:7px;border-radius:50%;background:{dot};margin-right:8px;flex-shrink:0;"></span>'
        f'<span style="color:{_colors["muted"]};">{label}</span>'
        f'<span style="width:1px;height:14px;background:{_colors["border"]};margin:0 12px;"></span>'
        f'<span style="color:{_colors["faint"]};">{_sb_group_txt}  ·  {_total_comps} components  ·  Phase 1–4</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

with col_right:
    tab_groups, tab_output = st.tabs(["Components Groups", "Pipeline Output"])
    if st.session_state.pop("_switch_to_log", False):
        components.html("<script>setTimeout(()=>{for(const t of window.parent.document.querySelectorAll('[data-baseweb=\"tab\"]')){if(t.textContent.trim()==='Pipeline Output')t.click();}},100);</script>", height=0)

with tab_groups:
    units_all = _load_model_file("units.json")
    components_all = _load_model_file("components.json")
    funcs_all = _load_model_file("functions.json")
    groups = st.session_state.get("groups", [])

    list_col, panel_col = st.columns([10, 11])

    with list_col:
        if not groups:
            st.info("No component groups configured.")
        else:
            for index, group in enumerate(groups):
                gid = group["gid"]
                gname = st.session_state.get(f"g{gid}_name", group["name"]).strip() or "(unnamed)"
                visible = []
                for comp in group["components"]:
                    cname = st.session_state.get(f"c{comp['cid']}_name", comp["comp"]).strip()
                    if not cname:
                        continue
                    fn_count = sum(len(units_all.get(uid, {}).get("functionIds", [])) for uid in components_all.get(cname, {}).get("units", []))
                    visible.append((comp["cid"], cname, fn_count))
                with st.expander(f"{gname}  {len(visible)}", expanded=True, key=f"group_{index}"):
                    if not visible:
                        st.markdown('<div style="padding:0.5rem 2.5rem;color:rgba(228,228,231,0.28);font-size:0.78rem;">No parsed components. Run the pipeline.</div>', unsafe_allow_html=True)
                    for cid, cname, fn_count in visible:
                        _fn_label = f"{fn_count} fn" if fn_count else ""
                        if st.button(f"{cname}{'  ' + _fn_label if _fn_label else ''}", key=f"comp_{cid}", use_container_width=True):
                            st.session_state["_selected_comp"] = cname

    with panel_col:
        selected_comp = st.session_state.get("_selected_comp")
        if not selected_comp:
            st.markdown(
                f'<div style="height:60vh;display:flex;align-items:center;justify-content:center;color:{_colors["faint"]};font-size:0.82rem;font-family:\'Segoe UI\',system-ui,sans-serif;">Select a component to view details</div>',
                unsafe_allow_html=True,
            )
        else:
            unit_ids = components_all.get(selected_comp, {}).get("units", [])
            total_fn = sum(len(units_all.get(uid, {}).get("functionIds", [])) for uid in unit_ids)
            num_units = len([uid for uid in unit_ids if units_all.get(uid, {}).get("functionIds")])
            comp_group = ""
            for _g in st.session_state.get("groups", []):
                for _c in _g["components"]:
                    if st.session_state.get(f"c{_c['cid']}_name", _c["comp"]).strip() == selected_comp:
                        comp_group = st.session_state.get(f"g{_g['gid']}_name", _g["name"]).strip()
                        break
                if comp_group:
                    break
            subtitle = f"{comp_group}  ·  {total_fn} function{'s' if total_fn != 1 else ''} across {num_units} unit{'s' if num_units != 1 else ''}"
            st.markdown(
                f'<div style="background:{_colors["side_bg"]};border-bottom:1px solid {_colors["border"]};padding:0.6rem 1rem 0.5rem;font-family:\'Segoe UI\',system-ui,sans-serif;">'
                f'<div style="font-size:14px;font-weight:700;color:{_colors["text"]};">{selected_comp}</div>'
                f'<div style="font-size:10.5px;color:{_colors["faint"]};margin-top:2px;">{subtitle}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            vis_filter = st.radio(
                "Filter",
                ["All", "Public", "Private"],
                horizontal=True,
                key="_fn_vis_filter",
                label_visibility="collapsed",
            )
            fn_to_open = None
            for uid in unit_ids:
                unit = units_all.get(uid, {})
                fids = unit.get("functionIds", [])
                if not fids:
                    continue
                filtered_fids = [
                    fid for fid in fids
                    if vis_filter == "All"
                    or funcs_all.get(fid, {}).get("visibility", "public").lower() == vis_filter.lower()
                ]
                if not filtered_fids:
                    continue
                unit_name = unit.get("name", uid)
                st.markdown(
                    f'<div style="font-size:9px;font-weight:700;letter-spacing:1.4px;color:{_colors["faint"]};text-transform:uppercase;padding:0.6rem 1rem 0.25rem;font-family:\'Segoe UI\',system-ui,sans-serif;">{unit_name}</div>',
                    unsafe_allow_html=True,
                )
                for fid in filtered_fids:
                    fn_entry = funcs_all.get(fid, {})
                    fname = fid.split("|")[2] if "|" in fid and len(fid.split("|")) > 2 else fid
                    vis = fn_entry.get("visibility", "")
                    vis_tag = "  [pub]" if vis == "public" else "  [priv]" if vis == "private" else ""
                    label = f"{fname}(){vis_tag if vis_filter == 'All' else ''}"
                    if st.button(label, key=f"fn_{fid}", use_container_width=True):
                        fn_to_open = fid
            if fn_to_open:
                _function_dialog(fn_to_open, units_all, funcs_all)

with tab_output:
    if _rs.get("cmd"):
        st.code(_rs["cmd"], language="bash")
    if log_lines:
        st.code("\n".join(reversed(log_lines[-120:])), language="bash")
    else:
        st.markdown('<div style="height:60vh;display:flex;align-items:center;justify-content:center;color:rgba(228,228,231,0.45);">No output yet</div>', unsafe_allow_html=True)

st.button("⚙", key="_settings_fab", on_click=_settings_dialog)

def _toggle_theme():
    current = st.session_state.get("ui_theme", "Dark")
    st.session_state["ui_theme"] = "Light" if current == "Dark" else "Dark"

_theme_icon = "☀" if _theme == "Dark" else "🌙"
_theme_label = "Light" if _theme == "Dark" else "Dark"
st.button(f"{_theme_icon}  {_theme_label}", key="_theme_toggle", on_click=_toggle_theme)

if running:
    time.sleep(0.8)
    st.rerun()

if st.session_state.get("_init_done"):
    _write_config()
