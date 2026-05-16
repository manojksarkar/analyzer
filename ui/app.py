"""
C++ Analyzer - DOCX Generator UI (Improved)
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
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

# -----------------------------------------------------------------------------
# Constants & Configuration
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from core.config import get_flat_groups as _get_flat_groups

CONFIG_JSON = ROOT / "config" / "config.json"
LAST_RUN = ROOT / "config" / "last_run.json"
PHASE_NAMES = {1: "Parse", 2: "Derive", 3: "Views", 4: "Export"}

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------
def _pick_folder(key: str):
    """Open folder picker dialog (tkinter)."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    path = filedialog.askdirectory()
    root.destroy()
    if path:
        st.session_state[key] = path


def _pick_relative_folder(key: str, base: str = ""):
    """Open folder picker and store path relative to base (or project_path)."""
    import tkinter as tk
    from tkinter import filedialog

    base_path = Path(base) if base else Path(st.session_state.get("project_path", "") or "")
    initial = str(base_path) if base_path.exists() else None

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    path = filedialog.askdirectory(initialdir=initial)
    root.destroy()
    if path:
        try:
            rel = Path(path).relative_to(base_path)
            st.session_state[key] = str(rel).replace("\\", "/")
        except ValueError:
            st.session_state[key] = str(Path(path)).replace("\\", "/")


def _strip_comments(text: str) -> str:
    """Strip C++ style comments from JSON content."""
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
    """Load JSON file with comment stripping."""
    try:
        return json.loads(_strip_comments(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _save_json(path: Path, data: dict[str, Any]):
    """Save JSON safely."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


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


def _save_function_edits(fid: str, description: str, visibility: str):
    """Save function description and visibility to the correct model file."""
    funcs_path = _model_file_for_function(fid)
    funcs = _load_json(funcs_path)
    if fid in funcs:
        funcs[fid]["description"] = description
        funcs[fid]["visibility"] = visibility
        _save_json(funcs_path, funcs)

    # Also update interface tables if they exist
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
                    entry["visibility"] = visibility
                    changed = True
        if changed:
            _save_json(iface_path, iface)


# -----------------------------------------------------------------------------
# Model & Config Management
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_units_all() -> dict[str, Any]:
    return _load_model_file("units.json")


@st.cache_data(show_spinner=False)
def get_components_all() -> dict[str, Any]:
    return _load_model_file("components.json")


@st.cache_data(show_spinner=False)
def get_funcs_all() -> dict[str, Any]:
    return _load_model_file("functions.json")


def _init():
    """Initialize session state and config."""
    if st.session_state.get("_init_done"):
        return

    cfg = _merged_config()
    clang = cfg.get("clang", {})
    llm = cfg.get("llm", {})
    views = cfg.get("views", {})
    ui = cfg.get("ui", {})
    layers_raw = cfg.get("layers", {})
    sample = ROOT / "SampleCppProject"
    last = _load_last_run()

    # Basic settings
    st.session_state.setdefault("project_path", last.get("project_path") or (str(sample) if sample.exists() else ""))
    st.session_state.setdefault("ui_theme", ui.get("theme", "Dark"))
    st.session_state.setdefault("llvm_lib", clang.get("llvmLibPath", ""))
    st.session_state.setdefault("clang_include", clang.get("clangIncludePath", ""))
    args = clang.get("clangArgs", [])
    st.session_state.setdefault("clang_args", " ".join(args) if isinstance(args, list) else str(args))

    # Layer mapping
    st.session_state["_layers_raw"] = layers_raw
    group_to_layer = {
        gname: lname
        for lname, ldata in layers_raw.items()
        for gname in (ldata.get("groups") or {}).keys()
    }
    st.session_state["_group_to_layer"] = group_to_layer

    # Build groups from config — iterate raw layers so paths stay layer-relative (no prefix)
    gid = cid = pid = 0
    groups: list[dict[str, Any]] = []
    gid_to_layer: dict[int, str] = {}
    default_layer = next(iter(layers_raw.keys()), "Layer1")
    for lname, ldata in layers_raw.items():
        for gname, mods in (ldata.get("groups") or {}).items():
            if not isinstance(mods, dict):
                continue
            components_list = []
            for cname, paths_raw in mods.items():
                paths_raw = paths_raw if isinstance(paths_raw, list) else ([paths_raw] if paths_raw else [""])
                paths = [{"pid": pid + i, "path": p} for i, p in enumerate(paths_raw)]
                pid += len(paths)
                components_list.append({"cid": cid, "comp": cname, "paths": paths})
                cid += 1
            groups.append({"gid": gid, "name": gname, "components": components_list})
            gid_to_layer[gid] = lname
            gid += 1

    st.session_state["groups"] = groups
    st.session_state["_next_gid"] = gid
    st.session_state["_next_cid"] = cid
    st.session_state["_next_pid"] = pid
    st.session_state["_gid_to_layer"] = gid_to_layer

    # View settings
    st.session_state.setdefault("v_unit", bool(views.get("unitDiagrams", True)))
    st.session_state.setdefault("v_flow", bool(views.get("flowcharts", True)))
    st.session_state.setdefault("v_behav", bool(views.get("behaviourDiagram", True)))
    st.session_state.setdefault("v_msd", bool(views.get("componentStaticDiagram", True)))

    # LLM settings
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
    st.session_state.setdefault("_doc_type", "SDDD")
    st.session_state["_init_done"] = True


def _groups_to_layers_config() -> dict[str, Any]:
    """Convert current groups UI state to layers config format."""
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
            paths = [p["path"].strip() for p in comp["paths"]]
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
    """Write current UI settings to config.json."""
    cfg: dict[str, Any] = {}

    # Clang
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

    # Views & Export
    cfg["views"] = {
        "interfaceTables": True,
        "unitDiagrams": st.session_state["v_unit"],
        "flowcharts": st.session_state["v_flow"],
        "behaviourDiagram": st.session_state["v_behav"],
        "componentStaticDiagram": st.session_state["v_msd"],
    }
    cfg["layers"] = _groups_to_layers_config()

    # LLM
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

    # UI
    cfg["ui"] = {"theme": st.session_state.get("ui_theme", "Dark")}

    _save_json(CONFIG_JSON, cfg)
    _save_last_run()


# -----------------------------------------------------------------------------
# Pipeline Execution
# -----------------------------------------------------------------------------
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
    st.toast("Pipeline stopped", icon="⏹")


def _run_full(selected_group: str | None, doc_type: str = "SDDD"):
    project_path = (st.session_state.get("project_path") or "").strip()
    if not project_path or not Path(project_path).exists():
        st.error("Invalid project path", icon="❌")
        return
    _write_config()
    cmd = [sys.executable, str(ROOT / "run.py")]
    if doc_type != "SDDD":
        cmd += ["--doc-type", doc_type.lower()]
    if selected_group and doc_type in ("SDDD", "Both"):
        cmd += ["--selected-group", selected_group]
    cmd.append(project_path)
    _start_pipeline(cmd, "full")
    st.toast(f"Pipeline started: {doc_type}", icon="▶")


def _run_export(selected_group: str | None, doc_type: str = "SDDD"):
    project_path = (st.session_state.get("project_path") or "").strip()
    if not project_path or not Path(project_path).exists():
        st.error("Invalid project path", icon="❌")
        return
    _write_config()
    cmd = [sys.executable, str(ROOT / "run.py"), "--from-phase", "4", "--use-model"]
    if doc_type != "SDDD":
        cmd += ["--doc-type", doc_type.lower()]
    if selected_group and doc_type in ("SDDD", "Both"):
        cmd += ["--selected-group", selected_group]
    cmd.append(project_path)
    _start_pipeline(cmd, "export")
    st.toast("Export started (phase 4)", icon="📄")


# -----------------------------------------------------------------------------
# UI Dialogs & Popovers
# -----------------------------------------------------------------------------
@st.dialog("Function Details", width="large")
def _function_dialog(fid: str):
    entry = get_funcs_all().get(fid)
    if not entry: return

    _dark = st.session_state.get("ui_theme", "Dark") == "Dark"
    _dlg_bg     = "#0e1117"          if _dark else "#ffffff"
    _dlg_border = "#262730"          if _dark else "rgba(0,0,0,0.10)"
    _lbl_color  = "#777"             if _dark else "#999"
    _ti_bg, _ti_fg, _ti_bd = ("#262730", "#808495", "#3e404a") if _dark else ("#f0f0f4", "#666677", "#ddd")
    _to_bg, _to_fg, _to_bd = ("#1a2c1e", "#4ade80", "#2d4a34") if _dark else ("#e8f5e9", "#2e7d32", "#c8e6c9")
    _tp_bg, _tp_fg, _tp_bd = ("#2c241a", "#fbbf24", "#4a3d2d") if _dark else ("#fff3e0", "#e65100", "#ffe0b2")
    _hint_col   = "#555"             if _dark else "#bbb"

    st.markdown(f"""
        <style>
        .f-label {{ font-size:0.65rem; font-weight:700; color:{_lbl_color}; margin:10px 0 2px 0; text-transform:uppercase; letter-spacing:0.05em; }}
        .f-tags  {{ display:flex; gap:6px; margin-bottom:12px; }}
        .f-tag   {{ padding:1px 8px; border-radius:4px; font-size:0.7rem; font-family:monospace; }}
        .t-iface {{ background:{_ti_bg}; color:{_ti_fg}; border:1px solid {_ti_bd}; }}
        .t-out   {{ background:{_to_bg}; color:{_to_fg}; border:1px solid {_to_bd}; }}
        .t-pub   {{ background:{_tp_bg}; color:{_tp_fg}; border:1px solid {_tp_bd}; }}
        [data-testid="stForm"] {{ border:none; padding:0; }}
        div[data-testid="stTextArea"] textarea {{ font-family:monospace; font-size:0.85rem; }}
        </style>
    """, unsafe_allow_html=True)

    # --- Header ---
    st.subheader(f"`{entry.get('qualifiedName', fid.split('|')[-1])}`")
    
    # Tag Row
    st.markdown(f"""
        <div class="f-tags">
            <span class="f-tag t-iface">{entry.get('interfaceId', 'net_iface')}</span>
            <span class="f-tag t-out">{entry.get('direction', 'outbound')}</span>
            <span class="f-tag t-pub">{entry.get('visibility', 'public')}</span>
        </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1.8], gap="medium")

    with col1:
        # Signature
        st.markdown('<div class="f-label">Signature</div>', unsafe_allow_html=True)
        st.code(f"{entry.get('returnType', 'bool')} {entry.get('name', 'func')}(...)", language="cpp")

        # Description
        st.markdown('<div class="f-label">Description</div>', unsafe_allow_html=True)
        desc = st.text_area("##", value=entry.get("description", ""), 
                            height=120, label_visibility="collapsed", key=f"tx_{fid}")
        
        # Visibility Edit
        st.markdown('<div class="f-label" style="margin-top:10px;">Visibility</div>', unsafe_allow_html=True)
        current_vis = entry.get("visibility", "default").lower()
        vis_options = ["public", "private", "protected", "default"]
        if current_vis not in vis_options:
            vis_options.append(current_vis)
        new_vis = st.selectbox("Visibility", vis_options, index=vis_options.index(current_vis), key=f"vis_{fid}", label_visibility="collapsed")
        
        if st.button("Save", type="primary", use_container_width=True):
            _save_function_edits(fid, desc, new_vis)
            get_funcs_all.clear()
            st.success("Saved")

        # Metadata lists
        for label, key in [("Calls", "callsIds"), ("Called By", "calledByIds")]:
            items = [i.split("|")[-1] for i in entry.get(key, [])]
            if items:
                st.markdown(f'<div class="f-label">{label}</div>', unsafe_allow_html=True)
                st.caption(" · ".join(items))

    with col2:
        st.markdown('<div class="f-label" style="margin-top:0;">Flowchart</div>', unsafe_allow_html=True)
        
        # Determine Path
        unit_name = next((u.get("name", "") for u in get_units_all().values() if fid in u.get("functionIds", [])), "")
        fname = fid.split("|")[2] if "|" in fid else ""
        img_path = list((ROOT / "output").glob(f"**/flowcharts/{unit_name}_{fname}.png"))

        if img_path and img_path[0].exists():
            b64_img = base64.b64encode(img_path[0].read_bytes()).decode()
            components.html(f"""
                <body style="margin:0; background:{_dlg_bg}; display:flex; justify-content:center; align-items:center; height:500px; font-family:sans-serif;">
                    <div id="canvas" style="width:100%; height:100%; overflow:hidden; cursor:grab; display:flex; align-items:center; justify-content:center; position:relative; user-select:none; border:1px solid {_dlg_border}; border-radius:8px; box-sizing:border-box;">
                        <img id="flow" src="data:image/png;base64,{b64_img}" style="max-width:95%; max-height:95%; transform-origin:center; pointer-events:none;">
                        <div id="hint" style="position:absolute; bottom:10px; right:10px; color:{_hint_col}; font-size:10px; pointer-events:none;">DRAG TO PAN • SCROLL TO ZOOM</div>
                    </div>
                </body>
                <script>
                    const img = document.getElementById('flow');
                    const canvas = document.getElementById('canvas');
                    
                    let scale = 1;
                    let tx = 0;
                    let ty = 0;
                    let isDragging = false;
                    let startX, startY;

                    // Apply transformations
                    const update = () => {{
                        img.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{scale}})`;
                    }};

                    // Zoom Logic
                    canvas.onwheel = e => {{
                        e.preventDefault();
                        const delta = e.deltaY > 0 ? 0.9 : 1.1;
                        scale = Math.min(Math.max(scale * delta, 0.3), 5);
                        update();
                    }};

                    // Pan Logic
                    canvas.onmousedown = e => {{
                        isDragging = true;
                        canvas.style.cursor = 'grabbing';
                        startX = e.clientX - tx;
                        startY = e.clientY - ty;
                    }};

                    window.onmousemove = e => {{
                        if (!isDragging) return;
                        tx = e.clientX - startX;
                        ty = e.clientY - startY;
                        update();
                    }};

                    window.onmouseup = () => {{
                        isDragging = false;
                        canvas.style.cursor = 'grab';
                    }};

                    // Double Click Reset
                    canvas.ondblclick = () => {{
                        scale = 1; tx = 0; ty = 0;
                        update();
                    }};
                </script>
            """, height=500)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("No flowchart found.")

def _set_group_dialog_index(index: int):
    st.session_state["_group_dialog_index"] = index


@st.dialog("Component Groups", width="large")
def _groups_dialog():
    # ── Force compact scrolling with CSS ──
    st.markdown(
        """
        <style>
        /* Dialog body fixed height + scroll */
        div[role="dialog"] > div:first-child {
            max-height: 70vh !important;
            overflow-y: auto !important;
            padding: 0.25rem 0.75rem 0.5rem 0.75rem !important;
        }
        div[role="dialog"] {
            padding: 0 !important;
        }
        /* Remove all extra margins/paddings from Streamlit blocks */
        div[role="dialog"] .stMarkdown,
        div[role="dialog"] .stVerticalBlock,
        div[role="dialog"] .stHorizontalBlock,
        div[role="dialog"] .stElementContainer {
            margin: 0 !important;
            padding: 0 !important;
            gap: 0 !important;
        }
        div[role="dialog"] [data-testid="column"] {
            padding: 0 0.25rem !important;
        }
        div[role="dialog"] .stButton button {
            min-height: 28px !important;
            margin: 0.1rem 0 !important;
        }
        div[role="dialog"] hr {
            margin: 0.3rem 0 !important;
        }
        div[role="dialog"] .stTextInput > div {
            margin-bottom: 0.2rem !important;
        }
        div[role="dialog"] [data-testid="stExpander"] {
            margin: 0 0 0.25rem 0 !important;
            padding: 0 !important;
        }
        div[role="dialog"] [data-testid="stExpander"] details {
            margin: 0 !important;
        }
        div[role="dialog"] [data-testid="stExpander"] summary {
            padding: 0.2rem 0.5rem !important;
            min-height: 32px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Initialise state ──
    layers_raw = st.session_state.get("_layers_raw", {})
    layer_names = list(layers_raw.keys())
    if not layer_names:
        layers_raw["Layer1"] = {"path": "Layer1", "groups": {}}
        layer_names = ["Layer1"]
        st.session_state["_layers_raw"] = layers_raw

    st.session_state.setdefault("_selected_layer", layer_names[0])
    selected_layer = st.session_state["_selected_layer"]
    if selected_layer not in layer_names:
        selected_layer = layer_names[0]
        st.session_state["_selected_layer"] = selected_layer

    gid_to_layer = st.session_state.get("_gid_to_layer", {})

    # ── Layout: left layers, right groups ──
    left_col, right_col = st.columns([1, 2.5], gap="medium")

    # ======================= LEFT PANEL: LAYERS =======================
    with left_col:
        st.markdown(
            '<div style="font-size:10px; font-weight:700; letter-spacing:1.5px; color:var(--faint); margin-bottom:12px;">🗂️ LAYERS</div>',
            unsafe_allow_html=True,
        )

        # Simple callback – only updates state
        def _set_selected_layer(lname: str):
            st.session_state["_selected_layer"] = lname

        for lname in layer_names:
            display = st.session_state.get(f"lname_{lname}", lname)
            n_groups = sum(1 for ln in gid_to_layer.values() if ln == lname)
            st.button(
                f"{display}  ·  {n_groups} grp",
                key=f"layer_btn_{lname}",   # stable key using raw layer name
                type="primary" if selected_layer == lname else "secondary",
                use_container_width=True,
                on_click=_set_selected_layer,
                args=(lname,)
            )
        st.divider()
        if st.button("➕ Add Layer", key="add_layer_btn", use_container_width=True):
            _add_layer()

    # ======================= RIGHT PANEL: GROUPS IN SELECTED LAYER =======================
    with right_col:
        # Layer name + path + delete (if >1 layer)
        col_name, col_del = st.columns([3, 1])
        with col_name:
            new_name = st.text_input(
                "Layer name",
                value=st.session_state.get(f"lname_{selected_layer}", selected_layer),
                key=f"lname_{selected_layer}",
                label_visibility="collapsed"
            )
        with col_del:
            if len(layer_names) > 1:
                if st.button("🗑️ Delete", key=f"del_layer_{selected_layer}", use_container_width=True):
                    _delete_layer(selected_layer)
                    st.rerun()
        _lpath_cols = st.columns([4, 1])
        with _lpath_cols[0]:
            new_path = st.text_input(
                "Subdirectory path",
                value=layers_raw[selected_layer].get("path", selected_layer),
                key=f"lpath_{selected_layer}",
                placeholder="relative to project root",
                label_visibility="collapsed",
            )
        with _lpath_cols[1]:
            st.button(
                "📂",
                key=f"browse_lpath_{selected_layer}",
                on_click=_pick_relative_folder,
                args=(f"lpath_{selected_layer}",),
                use_container_width=True,
                help="Browse for folder",
            )
        st.session_state["_layers_raw"][selected_layer]["path"] = new_path if new_path else selected_layer

        st.markdown("---")

        # ── GROUPS in this layer ──
        groups = st.session_state.get("groups", [])
        groups_in_layer = [g for g in groups if gid_to_layer.get(g["gid"]) == selected_layer]

        if not groups_in_layer:
            st.info("No groups assigned to this layer.")
        else:
            for group in groups_in_layer:
                gid = group["gid"]
                gname_key = f"g{gid}_name"
                current_gname = st.session_state.get(gname_key, group["name"]).strip()
                if not current_gname:
                    current_gname = "(unnamed)"
                with st.expander(f"📁 {current_gname}  ({len(group['components'])} comps)", expanded=False):
                    # Group name & delete
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.text_input("Group name", value=group["name"], key=gname_key, label_visibility="collapsed")
                    with c2:
                        if st.button("Delete", key=f"del_group_{gid}"):
                            _remove_group(gid)
                            st.rerun()
                    # Layer selector (reassign group)
                    current_layer = gid_to_layer.get(gid, selected_layer)
                    new_layer = st.selectbox(
                        "Layer",
                        layer_names,
                        index=layer_names.index(current_layer) if current_layer in layer_names else 0,
                        key=f"g{gid}_layer_sel"
                    )
                    if new_layer != current_layer:
                        gid_to_layer[gid] = new_layer
                        st.session_state["_gid_to_layer"] = gid_to_layer
                        st.rerun()
                    # Components
                    st.markdown("**Components**")
                    for comp in group["components"]:
                        cid = comp["cid"]
                        comp_name_key = f"c{cid}_name"
                        col_c1, col_c2 = st.columns([4, 1])
                        with col_c1:
                            st.text_input(
                                "Component name",
                                value=comp["comp"],
                                key=comp_name_key,
                                label_visibility="collapsed",
                                placeholder="Component name"
                            )
                        with col_c2:
                            st.button("✖", key=f"del_comp_{cid}", on_click=_remove_component, args=(gid, cid))
                        for path in comp["paths"]:
                            pid = path["pid"]
                            pa, pb = st.columns([5, 1])
                            with pa:
                                st.caption(path["path"] or "—")
                            with pb:
                                st.button("✕", key=f"del_path_{pid}", on_click=_remove_path, args=(cid, pid), disabled=len(comp["paths"]) <= 1)
                        st.button("➕ Add path", key=f"add_path_{cid}", on_click=_add_path_browse, args=(cid,))
                        st.divider()
                    st.button("➕ Add component", key=f"add_comp_{gid}", on_click=_add_component, args=(gid,), use_container_width=True)

        # Add new group button
        st.markdown("---")
        if st.button("➕ Add new group", key="add_new_group_btn", use_container_width=True):
            _add_group()
            new_gid = st.session_state["_next_gid"] - 1
            gid_to_layer[new_gid] = selected_layer
            st.session_state["_gid_to_layer"] = gid_to_layer
            st.rerun()

    # ── SAVE & CLOSE ──
    st.divider()
    if st.button("💾 Save & Close", type="primary", use_container_width=True):
        # Persist layer renames and paths
        final_layers = {}
        for lname in list(st.session_state["_layers_raw"].keys()):
            new_display = st.session_state.get(f"lname_{lname}", lname).strip()
            if not new_display:
                new_display = lname
            final_layers[new_display] = {
                "path": st.session_state.get(f"lpath_{lname}", lname).strip() or lname,
                "groups": {}
            }
        st.session_state["_layers_raw"] = final_layers
        # Update gid_to_layer with new layer names
        old_to_new = {old: new for old, new in zip(layer_names, [st.session_state.get(f"lname_{ln}", ln).strip() or ln for ln in layer_names])}
        st.session_state["_gid_to_layer"] = {gid: old_to_new.get(ln, ln) for gid, ln in gid_to_layer.items()}
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
        for section in ("LLM", "Parser", "Views & Export", "Config"):
            st.button(
                section,
                key=f"settings_{section}",
                type="primary" if nav == section else "secondary",
                on_click=_set_settings_nav,
                args=(section,),
                use_container_width=True,
            )

    with content_col:
        if nav == "Appearance":
            st.session_state["_settings_nav"] = "LLM"
            st.rerun()

        if nav == "LLM" or nav == "Appearance":
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

            with st.expander("Advanced LLM Settings"):
                a1, a2, a3 = st.columns(3)
                a1.number_input("Timeout (sec)", key="llm_timeout", min_value=10)
                a2.number_input("Retries", key="llm_retries", min_value=0, max_value=10)
                a3.number_input("Context size", key="llm_ctx", min_value=512)
                st.text_input("Max tokens", key="llm_max_ctx_tokens")
                e1, e2, e3 = st.columns(3)
                e1.checkbox("Two-pass descriptions", key="llm_enr_two_pass")
                e1.checkbox("Self-review", key="llm_enr_self_review")
                e2.checkbox("Ensemble", key="llm_enr_ensemble")
                e2.checkbox("CFG simplification", key="llm_enr_cfg_simplify")
                e3.checkbox("Variable enrichment", key="llm_enr_var_enrich")
                st.text_input("Few-shot examples dir", key="llm_few_shot_dir")
                st.number_input("Cache version", key="llm_cache_version", min_value=1)
                st.text_area("Custom headers (JSON)", key="llm_custom_headers", height=80)

        elif nav == "Parser":
            st.text_input("LLVM lib path", key="llvm_lib")
            st.text_input("Clang include path", key="clang_include")
            st.text_input("Extra clang arguments", key="clang_args")

        elif nav == "Views & Export":
            d1, d2 = st.columns(2)
            d1.toggle("Unit diagrams", key="v_unit")
            d1.toggle("Flowcharts", key="v_flow")
            d2.toggle("Behaviour diagrams", key="v_behav")
            d2.toggle("Static component diagram", key="v_msd")

        else:  # Config
            st.json(_merged_config())

    st.divider()
    if st.button("Save Settings", type="primary", use_container_width=True):
        _write_config()
        st.toast("Settings saved", icon="💾")
        st.rerun()


# -----------------------------------------------------------------------------
# Group Management Helpers
# -----------------------------------------------------------------------------
def _add_group():
    gid = st.session_state["_next_gid"]
    cid = st.session_state["_next_cid"]
    pid = st.session_state["_next_pid"]
    st.session_state["groups"].append({
        "gid": gid,
        "name": "",
        "components": [{"cid": cid, "comp": "", "paths": [{"pid": pid, "path": ""}]}]
    })
    layers_raw = st.session_state.get("_layers_raw", {})
    st.session_state.setdefault("_gid_to_layer", {})[gid] = next(iter(layers_raw.keys()), "Layer1")
    st.session_state["_next_gid"] = gid + 1
    st.session_state["_next_cid"] = cid + 1
    st.session_state["_next_pid"] = pid + 1


def _remove_group(gid: int):
    st.session_state["groups"] = [g for g in st.session_state["groups"] if g["gid"] != gid]


def _add_layer():
    layers_raw = dict(st.session_state.get("_layers_raw", {}))
    i = 1
    while f"Layer{i}" in layers_raw:
        i += 1
    new_key = f"Layer{i}"
    layers_raw[new_key] = {"path": new_key, "groups": {}}
    st.session_state["_layers_raw"] = layers_raw
    st.session_state["_layers_tab_sel"] = new_key


def _delete_layer(layer_key: str):
    layers_raw = dict(st.session_state.get("_layers_raw", {}))
    if len(layers_raw) <= 1:
        return
    del layers_raw[layer_key]
    st.session_state["_layers_raw"] = layers_raw
    fallback = next(iter(layers_raw.keys()))
    gid_to_layer = dict(st.session_state.get("_gid_to_layer", {}))
    for gid, ln in gid_to_layer.items():
        if ln == layer_key:
            gid_to_layer[gid] = fallback
    st.session_state["_gid_to_layer"] = gid_to_layer
    st.session_state["_layers_tab_sel"] = fallback


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


def _add_path_browse(cid: int):
    """Open folder picker and add the selected path; does nothing on cancel."""
    import tkinter as tk
    from tkinter import filedialog

    _proj = st.session_state.get("project_path", "") or ""
    _layers_raw = st.session_state.get("_layers_raw", {})
    _selected_layer = st.session_state.get("_selected_layer", "")
    _layer_path = _layers_raw.get(_selected_layer, {}).get("path", "")

    base_path = Path(_proj) / _layer_path if _proj and _layer_path else (Path(_proj) if _proj else Path("."))
    initial = str(base_path) if base_path.exists() else None

    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    chosen = filedialog.askdirectory(initialdir=initial)
    root.destroy()

    if not chosen:
        return

    try:
        rel_str = str(Path(chosen).relative_to(base_path)).replace("\\", "/")
    except ValueError:
        rel_str = str(Path(chosen)).replace("\\", "/")

    pid = st.session_state["_next_pid"]
    for group in st.session_state["groups"]:
        for comp in group["components"]:
            if comp["cid"] == cid:
                comp["paths"].append({"pid": pid, "path": rel_str})
    st.session_state["_next_pid"] = pid + 1


def _remove_path(cid: int, pid: int):
    for group in st.session_state["groups"]:
        for comp in group["components"]:
            if comp["cid"] == cid:
                comp["paths"] = [p for p in comp["paths"] if p["pid"] != pid]


# -----------------------------------------------------------------------------
# Custom CSS
# -----------------------------------------------------------------------------
def _inject_css(colors: dict[str, str]):
    """Inject custom CSS for the UI."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

        :root {{
          --app-bg: {colors['app_bg']};
          --side-bg: {colors['side_bg']};
          --top-bg: {colors['top_bg']};
          --tab-bg: {colors['tab_bg']};
          --row-bg: {colors['row_bg']};
          --text: {colors['text']};
          --muted: {colors['muted']};
          --faint: {colors['faint']};
          --border: {colors['border']};
          --border-soft: {colors['border_soft']};
          --control-bg: {colors['control_bg']};
          --input-bg: {colors['input_bg']};
          --hover-bg: {colors['hover_bg']};
          --status-bg: {colors['status_bg']};
          --panel-bg: {colors['panel_bg']};
          --primary-color: #6366f1 !important;
          --primary-gradient: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%) !important;
        }}

        * {{
            font-family: 'Outfit', sans-serif !important;
            transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
        }}
        .material-icons, .material-symbols-rounded, .material-icons-outlined, [data-testid="stIconMaterial"], .st-emotion-cache-1n76uvr {{
            font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
        }}

        /* Hide native Streamlit chrome */
        [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeaderActionElements"] {{
            display: none !important;
        }}

        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(5px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}

        /* Main layout */
        section.main, [data-testid="stMain"] {{
            background: var(--app-bg) !important;
            overflow: hidden !important;
        }}
        .block-container, [data-testid="stMainBlockContainer"] {{
            max-width: 100% !important;
            padding: 3.25rem 0 1.5rem 0 !important;
            background: transparent !important;
            animation: fadeIn 0.4s ease-out forwards;
        }}

        /* Sidebar styling - Glassmorphism */
        [data-testid="stHorizontalBlock"] > div:first-child {{
            background: var(--side-bg) !important;
            backdrop-filter: blur(16px) !important;
            -webkit-backdrop-filter: blur(16px) !important;
            border-right: 1px solid var(--border) !important;
            min-height: calc(100vh - 3.25rem) !important;
            max-height: calc(100vh - 3.25rem) !important;
            overflow-y: auto !important;
            padding: 0.75rem 0.875rem 3rem !important;
        }}

        /* Main content area */
        [data-testid="stHorizontalBlock"] > div:last-child {{
            background: var(--app-bg) !important;
            min-height: calc(100vh - 3.25rem) !important;
            max-height: calc(100vh - 3.25rem) !important;
            overflow-x: hidden !important;
            overflow-y: auto !important;
        }}

        /* Tabs styling - Glassmorphism */
        [data-baseweb="tab-list"] {{
            background: var(--tab-bg) !important;
            backdrop-filter: blur(12px) !important;
            -webkit-backdrop-filter: blur(12px) !important;
            border-bottom: 1px solid var(--border) !important;
            height: 48px !important;
            padding: 0 1.5rem !important;
            gap: 2rem !important;
        }}
        [data-baseweb="tab"] {{
            height: 48px !important;
            color: var(--muted) !important;
            font-size: 0.85rem !important;
            font-weight: 500 !important;
        }}
        [data-baseweb="tab"][aria-selected="true"] {{
            color: var(--text) !important;
            font-weight: 600 !important;
        }}
        [data-baseweb="tab-highlight"] {{
            background: var(--primary-gradient) !important;
            height: 3px !important;
            border-radius: 3px 3px 0 0 !important;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }}

        /* Buttons */
        button[kind="primary"] {{
            background: var(--primary-gradient) !important;
            border: none !important;
            color: #fff !important;
            border-radius: 8px !important;
            box-shadow: 0 2px 6px rgba(99,102,241,0.2) !important;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }}
        button[kind="primary"]:hover {{
            transform: translateY(-1px) scale(1.02) !important;
            box-shadow: 0 4px 12px rgba(99,102,241,0.4) !important;
        }}
        button[kind="secondary"] {{
            background: var(--control-bg) !important;
            border: 1px solid var(--border) !important;
            color: var(--text) !important;
            border-radius: 8px !important;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }}
        button[kind="secondary"]:hover {{
            border-color: var(--muted) !important;
            background: var(--hover-bg) !important;
            transform: translateY(-1px) !important;
        }}

        /* Inputs */
        input, textarea {{
            background: var(--input-bg) !important;
            border: 1px solid var(--border) !important;
            border-radius: 6px !important;
            color: var(--text) !important;
            transition: all 0.2s ease !important;
        }}
        input:focus, textarea:focus {{
            border-color: #6366f1 !important;
            box-shadow: 0 0 0 1px #6366f1 !important;
        }}

        /* Expanders for component groups */
        [role="tabpanel"] [data-testid="stExpander"] {{
            border: 0 !important;
            border-radius: 8px !important;
            background: transparent !important;
            margin: 0 0 4px 0 !important;
            overflow: hidden !important;
        }}
        [role="tabpanel"] [data-testid="stExpander"] > details > summary {{
            background: var(--row-bg) !important;
            border-bottom: 1px solid var(--border-soft) !important;
            height: 40px !important;
            padding: 0 1rem 0 2rem !important;
            color: var(--text) !important;
            font-size: 0.75rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.5px !important;
            transition: background-color 0.2s ease !important;
        }}
        [role="tabpanel"] [data-testid="stExpander"] > details > summary:hover {{
            background: var(--hover-bg) !important;
        }}

        /* Component buttons */
        [class*="st-key-comp_"] button {{
            background: transparent !important;
            border: 0 !important;
            border-bottom: 1px solid var(--border-soft) !important;
            border-radius: 0 !important;
            color: var(--muted) !important;
            text-align: left !important;
            padding: 0 1.25rem 0 2.5rem !important;
            height: 34px !important;
        }}
        [class*="st-key-comp_"] button:hover {{
            background: var(--hover-bg) !important;
            color: var(--text) !important;
        }}
        [class*="st-key-comp_"] button::before {{
            content: "◇";
            font-size: 11px;
            color: var(--faint);
            position: absolute;
            left: 1.25rem;
        }}

        /* Function buttons */
        [class*="st-key-fn_"] button {{
            background: var(--input-bg) !important;
            border: 1px solid var(--border) !important;
            border-radius: 6px !important;
            text-align: left !important;
            padding: 0 1rem !important;
            height: 32px !important;
            font-size: 0.78rem !important;
            width: 100% !important;
        }}
        [class*="st-key-fn_"] button:hover {{
            border-color: var(--muted) !important;
            background: var(--hover-bg) !important;
        }}

        /* Status badge */
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 7px;
            border-radius: 11px;
            padding: 0.28rem 0.75rem;
        }}

        /* Floating buttons */
        .st-key-_settings_fab, .st-key-_theme_toggle {{
            position: fixed !important;
            z-index: 100000 !important;
        }}
        .st-key-_settings_fab {{
            top: 8px !important;
            right: 16px !important;
        }}
        .st-key-_theme_toggle {{
            top: 8px !important;
            right: 64px !important;
        }}
        .st-key-_settings_fab button, .st-key-_theme_toggle button {{
            border-radius: 50% !important;
            width: 36px !important;
            height: 36px !important;
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            font-size: 1.1rem !important;
            background: var(--control-bg) !important;
            border: 1px solid var(--border) !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15) !important;
            backdrop-filter: blur(8px) !important;
            -webkit-backdrop-filter: blur(8px) !important;
        }}
        .st-key-_settings_fab button:hover, .st-key-_theme_toggle button:hover {{
            background: var(--hover-bg) !important;
            transform: scale(1.05) !important;
        }}

        /* Dialog */
        div[role="dialog"] {{
            max-width: min(95vw, 1400px) !important;
            width: min(95vw, 1400px) !important;
            background: {colors["side_bg"]} !important;
        }}
        div[role="dialog"] > div {{
            background: {colors["side_bg"]} !important;
        }}
        /* Reset outer sidebar column styles bleeding into dialog columns */
        div[role="dialog"] [data-testid="stHorizontalBlock"] > div {{
            background: transparent !important;
            border: none !important;
            min-height: auto !important;
            max-height: none !important;
            overflow: visible !important;
            padding: 0.25rem 0.5rem !important;
        }}
        div[role="dialog"] [data-testid="stHorizontalBlock"] > div:first-child {{
            border-right: 1px solid {colors["border"]} !important;
            padding-right: 0.75rem !important;
        }}
        [data-testid="stModal"] > div {{
            background: rgba(0,0,0,0.55) !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------
# Main UI
# -----------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="C++ Analyzer", page_icon="⚙️", layout="wide")
    _init()

    # Theme handling
    _theme = st.session_state.get("ui_theme", "Dark")
    if _theme == "Light":
        colors = {
            "app_bg": "#fafafa",
            "side_bg": "rgba(255,255,255,0.85)",
            "top_bg": "rgba(255,255,255,0.85)",
            "tab_bg": "rgba(255,255,255,0.8)",
            "row_bg": "#f4f4f5",
            "text": "#09090b",
            "muted": "rgba(9,9,11,0.6)",
            "faint": "rgba(9,9,11,0.35)",
            "border": "rgba(0,0,0,0.1)",
            "border_soft": "rgba(0,0,0,0.06)",
            "control_bg": "#ffffff",
            "input_bg": "#f4f4f5",
            "hover_bg": "rgba(99,102,241,0.1)",
            "status_bg": "rgba(255,255,255,0.85)",
            "panel_bg": "#f4f4f5",
        }
    else:
        colors = {
            "app_bg": "#000000",
            "side_bg": "rgba(9,9,11,0.85)",
            "top_bg": "rgba(9,9,11,0.85)",
            "tab_bg": "rgba(9,9,11,0.8)",
            "row_bg": "#18181b",
            "text": "#fafafa",
            "muted": "rgba(250,250,250,0.6)",
            "faint": "rgba(250,250,250,0.35)",
            "border": "rgba(255,255,255,0.12)",
            "border_soft": "rgba(255,255,255,0.06)",
            "control_bg": "transparent",
            "input_bg": "rgba(255,255,255,0.05)",
            "hover_bg": "rgba(255,255,255,0.06)",
            "status_bg": "rgba(9,9,11,0.85)",
            "panel_bg": "#09090b",
        }

    _inject_css(colors)

    # Header
    _proj_crumb = Path((st.session_state.get("project_path") or "")).name or ""
    st.markdown(
        f"""
        <div style="position:fixed;top:0;left:0;right:0;height:52px;background:{colors["top_bg"]};backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-bottom:1px solid {colors["border"]};z-index:99999;display:flex;align-items:center;padding:0 56px 0 16px;">
            <div style="width:24px;height:24px;background:linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:800;box-shadow:0 2px 4px rgba(99,102,241,0.3);">✓</div>
            <div style="font-size:14px;font-weight:700;color:{colors["text"]};margin-left:12px;">C++ Analyzer</div>
            {f'<div style="width:1px;height:16px;background:{colors["border"]};margin:0 12px;"></div><div style="font-size:12px;color:{colors["muted"]};overflow:hidden;text-overflow:ellipsis;max-width:300px;">{_proj_crumb}</div>' if _proj_crumb else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([5, 17])

    # ----- Left Sidebar -----
    with col_left:
        # ----- Compact Project Path -----
        st.markdown(
            f'<div style="font-size:9px; font-weight:600; letter-spacing:1px; color:{colors["faint"]}; margin-bottom:4px;">📁 PROJECT</div>',
            unsafe_allow_html=True,
        )
        project_value = (st.session_state.get("project_path") or "").strip()
        project_name = Path(project_value).name if project_value else "-"
        st.markdown(
            f'<div style="background:{colors["input_bg"]};border:1px solid {colors["border"]};border-radius:6px;padding:0.3rem 0.6rem;font-size:10px;color:{colors["muted"]};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">.../{project_name}</div>',
            unsafe_allow_html=True,
        )
        st.button("Browse...", key="_browse_project", on_click=_pick_folder, args=("project_path",), use_container_width=True)

        # ----- Document Type (compact radio) -----
        st.markdown(
            f'<div style="font-size:9px; font-weight:600; letter-spacing:1px; color:{colors["faint"]}; margin:10px 0 4px 0;">📄 DOC TYPE</div>',
            unsafe_allow_html=True,
        )
        doc_type = st.radio("Doc type", ["SDDD", "SAD", "Both"], key="_doc_type", horizontal=True, label_visibility="collapsed")

        # ----- Group Selection (if applicable) -----
        group_names = [st.session_state.get(f"g{g['gid']}_name", g["name"]).strip() for g in st.session_state.get("groups", [])]
        group_names = [g for g in group_names if g]
        selected_group = None
        if doc_type != "SAD":
            st.markdown(
                f'<div style="font-size:9px; font-weight:600; letter-spacing:1px; color:{colors["faint"]}; margin:10px 0 4px 0;">🎯 GROUP</div>',
                unsafe_allow_html=True,
            )
            selected = st.selectbox("Select group", ["All"] + group_names if group_names else ["All"], key="export_group_sel", label_visibility="collapsed")
            st.button("✏️ Edit Groups", key="_edit_groups_btn", on_click=_groups_dialog, use_container_width=True)
            selected_group = None if selected == "All" else selected

        # ----- Compact Status & Progress -----
        st.markdown(
            f'<div style="font-size:9px; font-weight:600; letter-spacing:1px; color:{colors["faint"]}; margin:10px 0 4px 0;">⚡ STATUS</div>',
            unsafe_allow_html=True,
        )
        _rs = _run_state()
        running = _rs["running"]
        returncode = _rs["returncode"]
        if running:
            dot, label = "#f59e0b", "Running"
        elif returncode == 0:
            dot, label = "#22c55e", "Done"
        elif returncode is not None:
            dot, label = "#ef4444", "Failed"
        else:
            dot, label = "#22c55e", "Ready"

        st.markdown(
            f'<div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.25);border-radius:16px;display:inline-flex;align-items:center;gap:6px;padding:2px 10px;margin-bottom:6px;">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{dot};"></span>'
            f'<span style="font-size:0.7rem;font-weight:600;color:{dot};">{label}</span></div>',
            unsafe_allow_html=True,
        )

        if running:
            log_text = "\n".join(_rs["lines"])
            phases_done = sum(f"Phase {n}" in log_text for n in [1, 2, 3, 4])
            st.progress(phases_done / 4)
            st.caption(PHASE_NAMES.get(min(phases_done + 1, 4), ""))

        # ----- Actions -----
        st.markdown(
            f'<div style="font-size:9px; font-weight:600; letter-spacing:1px; color:{colors["faint"]}; margin:10px 0 6px 0;">🎬 ACTIONS</div>',
            unsafe_allow_html=True,
        )
        if running:
            st.button("⏹  Stop", key="_stop_btn", on_click=_stop_pipeline, use_container_width=True)
        else:
            st.button("▶  Run", key="_run_trigger", type="primary", on_click=lambda: _run_full(selected_group, doc_type), use_container_width=True)
            st.button("↑  Export DOCX", key="_export_trigger", type="secondary", on_click=lambda: _run_export(selected_group, doc_type), use_container_width=True)

        # ----- Output Downloads (compact list) -----
        docx_files = sorted((ROOT / "output").rglob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True) if (ROOT / "output").exists() else []
        if docx_files:
            st.markdown(
                f'<div style="font-size:9px; font-weight:600; letter-spacing:1px; color:{colors["faint"]}; margin:10px 0 4px 0;">📥 OUTPUT</div>',
                unsafe_allow_html=True,
            )
            for docx in docx_files[:3]:  # limit to 3 most recent
                with open(docx, "rb") as fh:
                    st.download_button(
                        docx.name,
                        fh,
                        file_name=docx.name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"download_{docx}",
                        use_container_width=True,
                    )

        # ----- Bottom status bar (already compact) -----
        total_groups = len(st.session_state.get("groups", []))
        total_comps = sum(len(g["components"]) for g in st.session_state.get("groups", []))
        group_label = selected_group or "All groups"
        st.markdown(
            f'<div style="position:fixed;bottom:0;left:0;right:0;height:28px;background:{colors["status_bg"]};backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border-top:1px solid {colors["border"]};display:flex;align-items:center;padding:0 12px;font-size:9px;z-index:9998;">'
            f'<span style="width:6px;height:6px;border-radius:50%;background:{dot};margin-right:6px;"></span>'
            f'<span style="color:{colors["muted"]};">{label}</span>'
            f'<span style="width:1px;height:12px;background:{colors["border"]};margin:0 8px;"></span>'
            f'<span style="color:{colors["faint"]};">{group_label} · {total_groups}g · {total_comps}c</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ----- Right Content Area -----
    with col_right:
        # Cache loaded data
        units_all = get_units_all()
        components_all = get_components_all()
        funcs_all = get_funcs_all()

        tab_groups, tab_arch, tab_output = st.tabs(["📦 Component Groups", "🏗 Architecture", "📋 Pipeline Output"])

        # Auto-switch to Output tab when pipeline starts
        if st.session_state.pop("_switch_to_log", False):
            components.html("<script>setTimeout(()=>{for(const t of window.parent.document.querySelectorAll('[data-baseweb=\"tab\"]')){if(t.textContent.trim()==='Pipeline Output')t.click();}},100);</script>", height=0)

        # Tab 1: Component Groups
        with tab_groups:
            groups = st.session_state.get("groups", [])
            if not groups:
                st.info("No component groups configured. Click 'Edit Groups' to add groups and components.")
            else:
                list_col, panel_col = st.columns([10, 11])

                with list_col:
                    _gid_to_layer = st.session_state.get("_gid_to_layer", {})
                    _layers_raw = st.session_state.get("_layers_raw", {})

                    # Group by layer
                    _layer_to_groups: dict[str, list] = {ln: [] for ln in _layers_raw}
                    _ungrouped = []
                    for g in groups:
                        ln = _gid_to_layer.get(g["gid"])
                        if ln and ln in _layer_to_groups:
                            _layer_to_groups[ln].append(g)
                        else:
                            _ungrouped.append(g)

                    render_order = [(ln, _layer_to_groups[ln]) for ln in _layers_raw if _layer_to_groups[ln]]
                    if _ungrouped:
                        render_order.append(("", _ungrouped))

                    exp_index = 0
                    for layer_label, layer_groups in render_order:
                        if layer_label:
                            st.markdown(
                                f'<div style="font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{colors["faint"]};padding:0.7rem 0 0.25rem;">{layer_label}</div>',
                                unsafe_allow_html=True,
                            )
                        for group in layer_groups:
                            gid = group["gid"]
                            gname = st.session_state.get(f"g{gid}_name", group["name"]).strip() or "(unnamed)"
                            visible_comps = []
                            for comp in group["components"]:
                                cname = st.session_state.get(f"c{comp['cid']}_name", comp["comp"]).strip()
                                if not cname:
                                    continue
                                fn_count = sum(len(units_all.get(uid, {}).get("functionIds", [])) for uid in components_all.get(cname, {}).get("units", []))
                                visible_comps.append((comp["cid"], cname, fn_count))

                            with st.expander(f"{gname}  ({len(visible_comps)})", expanded=True, key=f"group_{exp_index}"):
                                if not visible_comps:
                                    st.markdown(f'<div style="padding:0.5rem 2.5rem;color:{colors["faint"]};font-size:0.78rem;">No parsed components. Run pipeline first.</div>', unsafe_allow_html=True)
                                for cid, cname, fn_count in visible_comps:
                                    btn_label = f"{cname}  ({fn_count} fn)"
                                    if st.button(btn_label, key=f"comp_{cid}", use_container_width=True):
                                        st.session_state["_selected_comp"] = cname
                            exp_index += 1

                with panel_col:
                    selected_comp = st.session_state.get("_selected_comp")
                    if not selected_comp:
                        st.markdown(
                            f'<div style="height:60vh;display:flex;align-items:center;justify-content:center;color:{colors["faint"]};font-size:0.82rem;">Select a component from the left to view details</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        # Component details header
                        unit_ids = components_all.get(selected_comp, {}).get("units", [])
                        total_fn = sum(len(units_all.get(uid, {}).get("functionIds", [])) for uid in unit_ids)
                        num_units = len([uid for uid in unit_ids if units_all.get(uid, {}).get("functionIds")])

                        # Find which group contains this component
                        comp_group = ""
                        for g in st.session_state.get("groups", []):
                            for c in g["components"]:
                                if st.session_state.get(f"c{c['cid']}_name", c["comp"]).strip() == selected_comp:
                                    comp_group = st.session_state.get(f"g{g['gid']}_name", g["name"]).strip()
                                    break
                            if comp_group:
                                break

                        st.markdown(
                            f'<div style="background:{colors["side_bg"]};border-bottom:1px solid {colors["border"]};padding:0.6rem 1rem 0.5rem;">'
                            f'<div style="font-size:14px;font-weight:700;color:{colors["text"]};">{selected_comp}</div>'
                            f'<div style="font-size:10.5px;color:{colors["faint"]};">{comp_group}  ·  {total_fn} function{"s" if total_fn != 1 else ""} across {num_units} unit{"s" if num_units != 1 else ""}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                        # Filter functions
                        vis_filter = st.radio(
                            "Filter",
                            ["All", "Non-Private", "Private"],
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
                                or (vis_filter == "Private" and funcs_all.get(fid, {}).get("visibility", "default").lower() == "private")
                                or (vis_filter == "Non-Private" and funcs_all.get(fid, {}).get("visibility", "default").lower() != "private")
                            ]
                            if not filtered_fids:
                                continue

                            unit_name = unit.get("name", uid)
                            st.markdown(
                                f'<div style="font-size:9px;font-weight:700;letter-spacing:1.4px;color:{colors["faint"]};text-transform:uppercase;padding:0.6rem 1rem 0.25rem;">{unit_name}</div>',
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
                            _function_dialog(fn_to_open)

        # Tab 2: Architecture
        with tab_arch:
            add_dir = ROOT / "output" / "sad" / "layer_static_diagrams"
            layer_data_path = add_dir / "_layer_static_data.json"
            layer_data = _load_json(layer_data_path) if layer_data_path.exists() else {}

            if not layer_data:
                st.markdown(
                    f'<div style="height:60vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;color:{colors["faint"]};">'
                    f'<div style="font-size:0.9rem;font-weight:600;">No architecture output yet</div>'
                    f'<div style="font-size:0.78rem;">Select doc type <b>SAD</b> or <b>Both</b> and run the pipeline.</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                for layer_name, layer_info in layer_data.items():
                    st.markdown(
                        f'<div style="font-size:13px;font-weight:700;color:{colors["text"]};padding:1rem 1.5rem 0.4rem;">{layer_name}</div>',
                        unsafe_allow_html=True,
                    )

                    # Static diagram
                    png_path = add_dir / f"{layer_name}_static.png"
                    svg_path = add_dir / f"{layer_name}_static.svg"
                    if png_path.exists():
                        st.image(str(png_path), use_container_width=True)
                    elif svg_path.exists():
                        with open(svg_path, "r", encoding="utf-8") as f:
                            svg_content = f.read()
                        components.html(
                            f'<div style="background:#ffffff;border:1px solid rgba(0,0,0,0.08);border-radius:8px;padding:16px;">{svg_content}</div>',
                            height=380,
                            scrolling=True,
                        )

                    # Component table
                    groups_info = layer_info.get("groups", {})
                    if groups_info:
                        st.markdown(
                            f'<div style="font-size:9px;font-weight:700;letter-spacing:1.4px;color:{colors["faint"]};text-transform:uppercase;padding:0.5rem 1.5rem 0.25rem;">Component Details</div>',
                            unsafe_allow_html=True,
                        )
                        rows = []
                        for gname, comps in groups_info.items():
                            for cname, cdata in comps.items() if isinstance(comps, dict) else []:
                                desc = cdata.get("description", "") if isinstance(cdata, dict) else ""
                                units = cdata.get("units", []) if isinstance(cdata, dict) else []
                                rows.append({"Group": gname, "Component": cname, "Units": len(units), "Description": desc or "—"})
                        if rows:
                            import pandas as pd
                            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    st.divider()

        # Tab 3: Pipeline Output
        with tab_output:
            rs = _run_state()
            if rs.get("cmd"):
                st.code(rs["cmd"], language="bash")
            if rs.get("lines"):
                st.code("\n".join(reversed(rs["lines"][-120:])), language="bash")
            else:
                st.markdown(
                    f'<div style="height:60vh;display:flex;align-items:center;justify-content:center;color:{colors["faint"]};">No output yet. Run the pipeline to see logs.</div>',
                    unsafe_allow_html=True,
                )

    # Floating buttons
    st.button("⚙️", key="_settings_fab", on_click=_settings_dialog)

    def _toggle_theme():
        current = st.session_state.get("ui_theme", "Dark")
        st.session_state["ui_theme"] = "Light" if current == "Dark" else "Dark"

    theme_icon = "☀️" if _theme == "Dark" else "🌙"
    st.button(f"{theme_icon}", key="_theme_toggle", on_click=_toggle_theme, help="Toggle Theme")

    # Auto-refresh when pipeline running
    current_running = _run_state()["running"]
    if current_running:
        time.sleep(0.5)
        st.rerun()
    elif running:
        # Pipeline finished between render start and here — one final rerun to show completion
        st.rerun()

    if st.session_state.get("_init_done"):
        _write_config()


if __name__ == "__main__":
    main()