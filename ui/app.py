"""
C++ Analyzer — DOCX Generator UI
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

# ── constants ─────────────────────────────────────────────────────────────────

ROOT         = Path(__file__).resolve().parent.parent
CONFIG_JSON  = ROOT / "config" / "config.json"
CONFIG_LOCAL = ROOT / "config" / "config.local.json"
LAST_RUN     = ROOT / "config" / "last_run.json"

PHASE_NAMES = {1: "Parse", 2: "Derive", 3: "Views", 4: "Export"}

# ── path picker helpers ───────────────────────────────────────────────────────

def _pick_folder(key: str):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.wm_attributes("-topmost", True)
    path = filedialog.askdirectory(); root.destroy()
    if path:
        st.session_state[key] = path

def _pick_file(key: str, filetypes: list | None = None):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk(); root.withdraw(); root.wm_attributes("-topmost", True)
    path = filedialog.askopenfilename(filetypes=filetypes or [("All files", "*.*")]); root.destroy()
    if path:
        st.session_state[key] = path

def _path_row(label: str, key: str, is_dir: bool = False,
              filetypes: list | None = None, disabled: bool = False, help: str = ""):
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    with c1:
        st.text_input(label, key=key, disabled=disabled, help=help)
    with c2:
        st.button("Browse", key=f"_browse_{key}", disabled=disabled,
                  on_click=_pick_folder if is_dir else _pick_file,
                  args=(key,) if is_dir else (key, filetypes),
                  use_container_width=True)

# ── JSON helpers ──────────────────────────────────────────────────────────────

def _strip_comments(text: str) -> str:
    result: list[str] = []
    i, in_string = 0, False
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\" and i + 1 < len(text):
                result.append(c); i += 1; result.append(text[i])
            elif c == '"':
                in_string = False; result.append(c)
            else:
                result.append(c)
        else:
            if c == '"':
                in_string = True; result.append(c)
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
    base  = _load_json(CONFIG_JSON)
    local = _load_json(CONFIG_LOCAL)
    for k, v in local.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base

# ── session state init ────────────────────────────────────────────────────────

def _init():
    if st.session_state.get("_init_done"):
        return
    if not CONFIG_LOCAL.exists():
        base = _load_json(CONFIG_JSON)
        CONFIG_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_LOCAL.write_text(json.dumps(base, indent=2), encoding="utf-8")
    cfg    = _merged_config()
    clang  = cfg.get("clang", {})
    llm    = cfg.get("llm", {})
    views  = cfg.get("views", {})
    export = cfg.get("export", {})
    ud     = views.get("unitDiagrams", {})
    fc     = views.get("flowcharts", {})
    bd     = views.get("behaviourDiagram", {})
    msd    = views.get("moduleStaticDiagram", {})
    sample = ROOT / "SampleCppProject"

    last = _load_last_run()
    st.session_state.setdefault("project_path", last.get("project_path") or (str(sample) if sample.exists() else ""))

    st.session_state.setdefault("llvm_lib",      clang.get("llvmLibPath", ""))
    st.session_state.setdefault("clang_include", clang.get("clangIncludePath", ""))
    args = clang.get("clangArgs", [])
    st.session_state.setdefault("clang_args", " ".join(args) if isinstance(args, list) else str(args))

    st.session_state.setdefault("v_unit_png",    bool(ud.get("renderPng", True)))
    st.session_state.setdefault("v_flow_png",    bool(fc.get("renderPng", True)))
    st.session_state.setdefault("v_flow_script", fc.get("scriptPath", "fake_flowchart_generator.py"))
    st.session_state.setdefault("v_behav_png",   bool(bd.get("renderPng", True)))
    st.session_state.setdefault("v_msd_enabled", bool(msd.get("enabled", True)))
    st.session_state.setdefault("v_msd_png",     bool(msd.get("renderPng", True)))
    st.session_state.setdefault("v_msd_width",   float(msd.get("widthInches", 5.5)))

    st.session_state.setdefault("export_docx_path", export.get("docxPath", "output/software_detailed_design_{group}.docx"))
    st.session_state.setdefault("export_font_size", int(export.get("docxFontSize", 8)))

    mg = cfg.get("modulesGroups", {})
    gid = 0; mid = 0; pid = 0; groups: list[dict] = []
    for gname, mods in mg.items():
        g_modules = []
        for mname, mpath in mods.items():
            paths_list = mpath if isinstance(mpath, list) else ([mpath] if mpath else [""])
            paths = [{"pid": pid + i, "path": p} for i, p in enumerate(paths_list)]
            pid += len(paths_list)
            g_modules.append({"mid": mid, "mod": mname, "paths": paths})
            mid += 1
        groups.append({"gid": gid, "name": gname, "modules": g_modules})
        gid += 1
    st.session_state["groups"]    = groups
    st.session_state["_next_gid"] = gid
    st.session_state["_next_mid"] = mid
    st.session_state["_next_pid"] = pid

    enr = llm.get("enrichment", {})
    ch  = llm.get("customHeaders", {})
    st.session_state.setdefault("llm_descriptions",     bool(llm.get("descriptions",  False)))
    st.session_state.setdefault("llm_behav_names",      bool(llm.get("behaviourNames", False)))
    st.session_state.setdefault("llm_summarize",        bool(llm.get("summarize",      False)))
    st.session_state.setdefault("llm_provider",         llm.get("provider",      "ollama"))
    st.session_state.setdefault("llm_url",              llm.get("baseUrl",       "http://localhost:11434"))
    st.session_state.setdefault("llm_api_key",          llm.get("apiKey",        ""))
    st.session_state.setdefault("llm_model",            llm.get("defaultModel",  "llama"))
    st.session_state.setdefault("llm_timeout",          int(llm.get("timeoutSeconds", 120)))
    st.session_state.setdefault("llm_ctx",              int(llm.get("numCtx", 8192)))
    st.session_state.setdefault("llm_retries",          int(llm.get("retries", 1)))
    max_ctx = llm.get("maxContextTokens")
    st.session_state.setdefault("llm_max_ctx_tokens",   "" if max_ctx is None else str(max_ctx))
    st.session_state.setdefault("llm_abbrev_path",      llm.get("abbreviationsPath", "config/abbreviations.txt"))
    st.session_state.setdefault("llm_few_shot_dir",     llm.get("fewShotExamplesDir", "few_shot_examples"))
    st.session_state.setdefault("llm_cache_version",    int(llm.get("cacheVersion", 1)))
    st.session_state.setdefault("llm_enr_two_pass",     bool(enr.get("twoPassDescriptions", False)))
    st.session_state.setdefault("llm_enr_self_review",  bool(enr.get("selfReview",          False)))
    st.session_state.setdefault("llm_enr_ensemble",     bool(enr.get("ensemble",            False)))
    st.session_state.setdefault("llm_enr_cfg_simplify", bool(enr.get("cfgSimplification",   False)))
    st.session_state.setdefault("llm_enr_var_enrich",   bool(enr.get("variableEnrichment",  True)))
    st.session_state.setdefault("llm_custom_headers",   json.dumps(ch, indent=2) if ch else "{}")
    st.session_state["_init_done"] = True

# ── module group helpers ──────────────────────────────────────────────────────

def _add_group():
    gid = st.session_state["_next_gid"]; mid = st.session_state["_next_mid"]; pid = st.session_state["_next_pid"]
    st.session_state["groups"].append({"gid": gid, "name": "", "modules": [{"mid": mid, "mod": "", "paths": [{"pid": pid, "path": ""}]}]})
    st.session_state["_next_gid"] = gid + 1; st.session_state["_next_mid"] = mid + 1; st.session_state["_next_pid"] = pid + 1

def _remove_group(gid: int):
    st.session_state["groups"] = [g for g in st.session_state["groups"] if g["gid"] != gid]

def _add_module(gid: int):
    mid = st.session_state["_next_mid"]; pid = st.session_state["_next_pid"]
    for g in st.session_state["groups"]:
        if g["gid"] == gid:
            g["modules"].append({"mid": mid, "mod": "", "paths": [{"pid": pid, "path": ""}]})
    st.session_state["_next_mid"] = mid + 1; st.session_state["_next_pid"] = pid + 1

def _remove_module(gid: int, mid: int):
    for g in st.session_state["groups"]:
        if g["gid"] == gid:
            g["modules"] = [m for m in g["modules"] if m["mid"] != mid]

def _add_path(mid: int):
    pid = st.session_state["_next_pid"]
    for g in st.session_state["groups"]:
        for m in g["modules"]:
            if m["mid"] == mid:
                m["paths"].append({"pid": pid, "path": ""})
    st.session_state["_next_pid"] = pid + 1

def _remove_path(mid: int, pid: int):
    for g in st.session_state["groups"]:
        for m in g["modules"]:
            if m["mid"] == mid:
                m["paths"] = [p for p in m["paths"] if p["pid"] != pid]

def _groups_to_config() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for g in st.session_state.get("groups", []):
        gname = st.session_state.get(f"g{g['gid']}_name", g["name"]).strip()
        if not gname:
            continue
        mods: dict[str, Any] = {}
        for m in g["modules"]:
            mname = st.session_state.get(f"m{m['mid']}_name", m["mod"]).strip()
            if not mname:
                continue
            paths = [st.session_state.get(f"p{p['pid']}_path", p["path"]).strip() for p in m["paths"]]
            paths = [p for p in paths if p]
            if not paths:
                continue
            mods[mname] = paths[0] if len(paths) == 1 else paths
        if mods:
            result[gname] = mods
    return result

# ── config writer ─────────────────────────────────────────────────────────────

def _write_config_local():
    cfg: dict[str, Any] = {}
    clang: dict[str, Any] = {}
    if v := st.session_state.get("llvm_lib", "").strip():      clang["llvmLibPath"] = v
    if v := st.session_state.get("clang_include", "").strip(): clang["clangIncludePath"] = v
    extra = [a for a in st.session_state.get("clang_args", "").split() if a]
    if extra: clang["clangArgs"] = extra
    if clang: cfg["clang"] = clang

    cfg["views"] = {
        "interfaceTables": True,
        "unitDiagrams":    {"renderPng": st.session_state["v_unit_png"]},
        "flowcharts":      {"scriptPath": st.session_state["v_flow_script"], "renderPng": st.session_state["v_flow_png"]},
        "behaviourDiagram":    {"renderPng": st.session_state["v_behav_png"]},
        "moduleStaticDiagram": {"enabled": st.session_state["v_msd_enabled"], "renderPng": st.session_state["v_msd_png"], "widthInches": st.session_state["v_msd_width"]},
    }
    cfg["export"] = {"docxPath": st.session_state.get("export_docx_path", "").strip() or "output/software_detailed_design_{group}.docx", "docxFontSize": st.session_state["export_font_size"]}
    mg = _groups_to_config()
    if mg: cfg["modulesGroups"] = mg

    provider = st.session_state.get("llm_provider", "ollama")
    llm_block: dict[str, Any] = {
        "descriptions": st.session_state.get("llm_descriptions", False),
        "behaviourNames": st.session_state.get("llm_behav_names", False),
        "summarize": st.session_state.get("llm_summarize", False),
        "provider": provider,
        "baseUrl": st.session_state.get("llm_url", "").strip() or "http://localhost:11434",
        **({"defaultModel": m} if (m := st.session_state.get("llm_model", "").strip()) else {}),
        "timeoutSeconds": st.session_state.get("llm_timeout", 120),
        "numCtx": st.session_state.get("llm_ctx", 8192),
        "retries": st.session_state.get("llm_retries", 1),
        **({"abbreviationsPath":  v} if (v := st.session_state.get("llm_abbrev_path",  "").strip()) else {}),
        **({"fewShotExamplesDir": v} if (v := st.session_state.get("llm_few_shot_dir", "").strip()) else {}),
        "cacheVersion":       st.session_state.get("llm_cache_version", 1),
        "enrichment": {
            "twoPassDescriptions": st.session_state.get("llm_enr_two_pass",     False),
            "selfReview":          st.session_state.get("llm_enr_self_review",  False),
            "ensemble":            st.session_state.get("llm_enr_ensemble",     False),
            "cfgSimplification":   st.session_state.get("llm_enr_cfg_simplify", False),
            "variableEnrichment":  st.session_state.get("llm_enr_var_enrich",   True),
        },
    }
    if provider == "openai":
        llm_block["apiKey"] = st.session_state.get("llm_api_key", "")
    try:
        ch = json.loads(st.session_state.get("llm_custom_headers", "{}") or "{}")
    except json.JSONDecodeError:
        ch = {}
    if ch: llm_block["customHeaders"] = ch
    max_ctx = (st.session_state.get("llm_max_ctx_tokens") or "").strip()
    llm_block["maxContextTokens"] = int(max_ctx) if max_ctx.isdigit() else None
    cfg["llm"] = llm_block

    CONFIG_LOCAL.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _save_last_run()

def _save_last_run():
    data = {"project_path": st.session_state.get("project_path", ""), "from_phase": st.session_state.get("from_phase", 1)}
    LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN.write_text(json.dumps(data, indent=2), encoding="utf-8")

def _load_last_run() -> dict:
    return _load_json(LAST_RUN)

def _save_function_description(fid: str, description: str):
    funcs_path = ROOT / "model" / "functions.json"
    funcs = _load_json(funcs_path)
    if fid in funcs:
        funcs[fid]["description"] = description
        funcs_path.write_text(json.dumps(funcs, indent=2), encoding="utf-8")

    iface_path = ROOT / "output" / "interface_tables.json"
    iface = _load_json(iface_path)
    for key, unit in iface.items():
        if key == "unitNames" or not isinstance(unit, dict):
            continue
        for entry in unit.get("entries", []):
            if entry.get("functionId") == fid:
                entry["description"] = description
    iface_path.write_text(json.dumps(iface, indent=2), encoding="utf-8")

# ── pipeline helpers ──────────────────────────────────────────────────────────


@st.cache_resource
def _get_runs() -> dict:
    return {}

def _run_state() -> dict:
    runs = _get_runs()
    sid = st.session_state.setdefault("_sid", str(uuid.uuid4()))
    if sid not in runs:
        runs[sid] = {"lines": [], "running": False, "returncode": None, "proc": None, "cmd": ""}
    return runs[sid]

def _pipeline_thread(cmd: list[str], sid: str):
    state = _get_runs()[sid]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, cwd=str(ROOT), bufsize=1)
        state["proc"] = proc
        for raw in iter(proc.stdout.readline, ""):
            state["lines"].append(raw.rstrip())
        proc.wait()
        state["returncode"] = proc.returncode
    except Exception as exc:
        state["lines"].append(f"ERROR: {exc}"); state["returncode"] = -1
    finally:
        state["running"] = False

def _start_pipeline(cmd: list[str]):
    state = _run_state()
    state.update(lines=[], running=True, returncode=None, proc=None, cmd=" ".join(cmd))
    threading.Thread(target=_pipeline_thread, args=(cmd, st.session_state["_sid"]), daemon=True).start()

def _stop_pipeline():
    state = _run_state(); proc = state.get("proc")
    if proc:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        except Exception:
            proc.kill()
    state.update(running=False, returncode=-1)
    state["lines"].append("— stopped by user —")

def _run_full(selected_group):
    proj = (st.session_state.get("project_path") or "").strip()
    if not proj or not Path(proj).exists():
        st.error("Invalid project path")
        return

    _write_config_local()

    cmd = [sys.executable, str(ROOT / "run.py")]

    if not any(st.session_state.get(k) for k in (
        "llm_descriptions", "llm_behav_names", "llm_summarize"
    )):
        cmd.append("--no-llm-summarize")

    if selected_group:
        cmd += ["--selected-group", selected_group]

    cmd.append(proj)

    _start_pipeline(cmd)
    st.session_state["_switch_to_log"] = True
    st.session_state["_run_type"] = "full"


def _run_export(selected_group):
    proj = (st.session_state.get("project_path") or "").strip()
    if not proj or not Path(proj).exists():
        st.error("Invalid project path")
        return

    _write_config_local()

    cmd = [
        sys.executable,
        str(ROOT / "run.py"),
        "--from-phase", "4",
        "--use-model"
    ]

    if selected_group:
        cmd += ["--selected-group", selected_group]

    cmd.append(proj)

    _start_pipeline(cmd)
    st.session_state["_switch_to_log"] = True
    st.session_state["_run_type"] = "export"

@st.dialog("Function", width="extra-large")
def _function_dialog(fid: str, units_all, funcs_all):

    entry = funcs_all.get(fid)

    if not entry:
        st.info("No data for this function.")
        return

    parts = fid.split("|")
    fname = entry.get("qualifiedName", parts[2] if len(parts) > 2 else fid)

    # ───────────────────────── HEADER (COMPACT)
    st.markdown(f"## `{fname}()`")

    meta = " · ".join(filter(None, [
        entry.get("interfaceId"),
        entry.get("direction"),
        entry.get("visibility")
    ]))

    if meta:
        st.caption(meta)

    loc = entry.get("location", {})
    if loc:
        st.caption(f"{loc.get('file','?')}:{loc.get('line','?')}–{loc.get('endLine','?')}")

    st.divider()

    left, right = st.columns([1.2, 2.2], gap="medium")

    # ───────────────────────── LEFT — INSPECTOR
    with left:

        # ── signature (compact)
        params = entry.get("parameters", [])
        ret = entry.get("returnType", "")

        sig = []
        for p in params:
            if isinstance(p, dict):
                sig.append(f"{p.get('type','')} {p.get('name','')}".strip())
            else:
                sig.append(str(p))

        st.code(f"{ret} {fname}({', '.join(sig)})", language="cpp")

        # ── DESCRIPTION (PRIMARY EDIT)
        st.caption("Description")

        desc = st.text_area(
            "",
            value=entry.get("description", ""),
            placeholder="Describe function…",
            height=110,
            key=f"desc_{fid}"
        )

        if st.button("Save", key=f"save_desc_{fid}", type="primary"):
            _save_function_description(fid, desc)
            st.success("Saved")

        st.divider()

        # ── RELATIONS (COLLAPSIBLE STYLE)
        with st.expander("Calls", expanded=False):
            callee_ids = entry.get("callsIds", [])
            callee_names = [c.split("|")[2] for c in callee_ids if "|" in c]
            st.write(", ".join(callee_names) if callee_names else "—")

        with st.expander("Called by", expanded=False):
            caller_ids = entry.get("calledByIds", [])
            caller_names = [c.split("|")[2] for c in caller_ids if "|" in c]
            st.write(", ".join(caller_names) if caller_names else "—")

        # behaviour (compact)
        if entry.get("behaviourInputName") or entry.get("behaviourOutputName"):
            with st.expander("Behaviour", expanded=False):
                if entry.get("behaviourInputName"):
                    st.caption("Input")
                    st.write(entry["behaviourInputName"])
                if entry.get("behaviourOutputName"):
                    st.caption("Output")
                    st.write(entry["behaviourOutputName"])

    # ========================= RIGHT PANEL: FLOWCHART VIEWER =========================
    with right:
        unit_name = ""
        for u in units_all.values():
            if fid in u.get("functionIds", []):
                unit_name = u.get("name", "")
                break

        fname2 = parts[2] if len(parts) > 2 else ""
        png_path = ROOT / "output" / "flowcharts" / f"{unit_name}_{fname2}.png"

        st.markdown("**Flowchart**")
        if png_path.exists():
            img_b64 = base64.b64encode(png_path.read_bytes()).decode()
            # Improved canvas viewer with loading spinner and shadow
            st.markdown(
                f"""
                <style>
                .flowchart-container {{
                    background: #1e1e1e;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 8px 20px rgba(0,0,0,0.08);
                    margin-top: 6px;
                }}
                </style>
                <div class="flowchart-container">
                """, unsafe_allow_html=True
            )
            components.html(f"""
            <div style="width:100%; height:70vh; position:relative; background:#fff; border-radius:8px;">
              <div id="wrap" style="width:100%; height:100%; overflow:hidden; cursor:grab; user-select:none; display:flex; align-items:center; justify-content:center; position:relative;">
                <img id="img" src="data:image/png;base64,{img_b64}" style="max-width:100%; max-height:100%; transform-origin:center; pointer-events:none;">
                <div id="hint" style="position:absolute; bottom:10px; right:12px; font-size:11px; font-family:sans-serif; background:rgba(0,0,0,0.6); color:white; padding:3px 8px; border-radius:6px; opacity:0.45; transition:opacity 0.3s; pointer-events:none;">🖱️ scroll zoom · drag pan · double click reset</div>
              </div>
            </div>
            <script>
            (function() {{
              const wrap = document.getElementById('wrap');
              const img = document.getElementById('img');
              let scale = 1, tx = 0, ty = 0;
              let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
              function apply() {{
                img.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{scale}})`;
              }}
              wrap.addEventListener('wheel', function(e) {{
                e.preventDefault();
                scale += e.deltaY > 0 ? -0.1 : 0.1;
                scale = Math.min(Math.max(scale, 0.3), 8);
                apply();
              }}, {{ passive: false }});
              wrap.addEventListener('mousedown', function(e) {{
                dragging = true;
                sx = e.clientX; sy = e.clientY;
                ox = tx; oy = ty;
                wrap.style.cursor = 'grabbing';
              }});
              window.addEventListener('mousemove', function(e) {{
                if (!dragging) return;
                tx = ox + (e.clientX - sx);
                ty = oy + (e.clientY - sy);
                apply();
              }});
              window.addEventListener('mouseup', function() {{
                dragging = false;
                wrap.style.cursor = 'grab';
              }});
              wrap.addEventListener('dblclick', function() {{
                scale = 1; tx = 0; ty = 0;
                apply();
              }});
              setTimeout(() => {{
                const hint = document.getElementById('hint');
                if (hint) hint.style.opacity = '0';
              }}, 4000);
            }})();
            </script>
            """, height=600)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("📷 No flowchart available for this function.")


@st.dialog("Module Groups", width="large")
def _groups_dialog():
    groups = st.session_state.get("groups", [])

    # ── header actions ──
    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption("Define groups, modules, and paths")
    with c2:
        st.button("＋ Add Group", on_click=_add_group, use_container_width=True)

    if not groups:
        st.info("No groups yet")

    # ─────────────────────────────
    # GROUPS
    # ─────────────────────────────
    for g in groups:
        gid = g["gid"]

        with st.container(border=True):

            # ── group header ──
            g1, g2 = st.columns([5, 1])
            with g1:
                st.text_input(
                    "Group",
                    key=f"g{gid}_name",
                    value=g["name"],
                    placeholder="group-name",
                    label_visibility="collapsed"
                )
            with g2:
                st.button(
                    "✕",
                    key=f"del_g{gid}",
                    on_click=_remove_group,
                    args=(gid,),
                    use_container_width=True
                )

            # ── modules ──
            for m in g["modules"]:
                mid = m["mid"]

                m1, m2 = st.columns([5, 1])
                with m1:
                    st.text_input(
                        "Module",
                        key=f"m{mid}_name",
                        value=m["mod"],
                        placeholder="module-name",
                        label_visibility="collapsed"
                    )
                with m2:
                    st.button(
                        "–",
                        key=f"del_m{mid}",
                        on_click=_remove_module,
                        args=(gid, mid),
                        use_container_width=True
                    )

                # ── paths ──
                for p in m["paths"]:
                    pid = p["pid"]

                    p1, p2, p3 = st.columns([5, 1, 0.7])
                    with p1:
                        st.text_input(
                            "Path",
                            key=f"p{pid}_path",
                            value=p["path"],
                            placeholder="relative/path",
                            label_visibility="collapsed"
                        )
                    with p2:
                        st.button(
                            "…",
                            key=f"_browse_p{pid}",
                            on_click=_pick_folder,
                            args=(f"p{pid}_path",),
                            use_container_width=True
                        )
                    with p3:
                        st.button(
                            "✕",
                            key=f"del_p{pid}",
                            on_click=_remove_path,
                            args=(mid, pid),
                            disabled=len(m["paths"]) <= 1,
                            use_container_width=True
                        )

                # add path
                st.button(
                    "+ path",
                    key=f"add_p_{mid}",
                    on_click=_add_path,
                    args=(mid,)
                )

                st.markdown("")  # small spacing

            # add module
            st.button(
                "+ module",
                key=f"add_m_{gid}",
                on_click=_add_module,
                args=(gid,),
                use_container_width=True
            )

    st.divider()

    # ── footer ──
    c1, c2 = st.columns(2)
    with c1:
        st.button("Cancel", use_container_width=True, on_click=st.rerun)
    with c2:
        st.button(
            "Save",
            type="primary",
            use_container_width=True,
            on_click=lambda: (_write_config_local(), st.rerun())
        )

@st.dialog("Settings", width="large")
def _settings_dialog():
    cfg = _merged_config()

    tab_llm, tab_clang, tab_views, tab_preview = st.tabs(
        ["🧠 LLM", "⚙ Parser", "📊 Views & Export", "📄 Config"]
    )

    # ─────────────────────────────────────────────
    # LLM TAB
    # ─────────────────────────────────────────────
    with tab_llm:
        any_llm = any(st.session_state.get(k) for k in (
            "llm_descriptions", "llm_behav_names", "llm_summarize"
        ))
        is_openai = st.session_state.get("llm_provider") == "openai"

        # Features
        st.markdown("##### Features")
        f1, f2, f3 = st.columns(3)
        f1.toggle("Descriptions", key="llm_descriptions")
        f2.toggle("Behaviour names", key="llm_behav_names")
        f3.toggle("Call-graph summary", key="llm_summarize")

        st.divider()

        # Connection
        st.markdown("##### Connection")
        st.radio(
            "Provider",
            ["ollama", "openai"],
            key="llm_provider",
            horizontal=True,
            disabled=not any_llm
        )

        c1, c2 = st.columns([3, 1])
        c1.text_input(
            "Base URL",
            key="llm_url",
            placeholder="http://localhost:11434",
            disabled=not any_llm
        )
        c2.text_input("Model", key="llm_model", disabled=not any_llm)

        if is_openai:
            st.text_input(
                "API Key",
                key="llm_api_key",
                type="password",
                placeholder="sk-...",
                disabled=not any_llm
            )

        # Advanced (cleaned)
        with st.expander("Advanced Settings", expanded=False):

            st.markdown("###### Runtime")
            r1, r2, r3, r4 = st.columns(4)
            r1.number_input("Timeout", key="llm_timeout", min_value=10, disabled=not any_llm)
            r2.number_input("Retries", key="llm_retries", min_value=0, max_value=10, disabled=not any_llm)
            r3.number_input("Context", key="llm_ctx", min_value=512, disabled=not any_llm or is_openai)
            r4.text_input("Max tokens", key="llm_max_ctx_tokens", disabled=not any_llm)

            st.markdown("###### Enrichment")
            e1, e2, e3 = st.columns(3)
            e1.checkbox("Two-pass", key="llm_enr_two_pass", disabled=not any_llm)
            e1.checkbox("Self-review", key="llm_enr_self_review", disabled=not any_llm)
            e2.checkbox("Ensemble", key="llm_enr_ensemble", disabled=not any_llm)
            e2.checkbox("CFG simplify", key="llm_enr_cfg_simplify", disabled=not any_llm)
            e3.checkbox("Variable enrichment", key="llm_enr_var_enrich", disabled=not any_llm)

            st.markdown("###### Files")
            _path_row("Abbreviations", "llm_abbrev_path", disabled=not any_llm)
            _path_row("Few-shot dir", "llm_few_shot_dir", is_dir=True, disabled=not any_llm)
            st.number_input("Cache version", key="llm_cache_version", min_value=1, disabled=not any_llm)

            if is_openai and any_llm:
                st.text_area("Custom headers (JSON)", key="llm_custom_headers", height=80)

    # ─────────────────────────────────────────────
    # CLANG TAB
    # ─────────────────────────────────────────────
    with tab_clang:
        st.markdown("##### Parser Configuration")
        st.caption("Leave blank to use defaults from config.json")

        _path_row("LLVM lib", "llvm_lib")
        _path_row("Clang include", "clang_include", is_dir=True)

        st.text_input(
            "Extra args",
            key="clang_args",
            placeholder="-std=c++17 -DSOME_DEFINE"
        )

    # ─────────────────────────────────────────────
    # VIEWS TAB
    # ─────────────────────────────────────────────
    with tab_views:
        st.markdown("##### Diagram Settings")

        c1, c2 = st.columns(2)

        with c1:
            with st.container(border=True):
                st.markdown("**Unit Diagrams**")
                st.toggle("Render PNG", key="v_unit_png")

            with st.container(border=True):
                st.markdown("**Flowcharts**")
                st.toggle("Render PNG", key="v_flow_png")
                _path_row("Script", "v_flow_script")

        with c2:
            with st.container(border=True):
                st.markdown("**Behaviour Diagrams**")
                st.toggle("Render PNG", key="v_behav_png")

            with st.container(border=True):
                st.markdown("**Module Static Diagram**")
                st.toggle("Enabled", key="v_msd_enabled")
                msd_on = st.session_state.get("v_msd_enabled", True)

                st.toggle("Render PNG", key="v_msd_png", disabled=not msd_on)
                st.number_input(
                    "Width",
                    key="v_msd_width",
                    min_value=1.0,
                    max_value=20.0,
                    step=0.5,
                    disabled=not msd_on
                )

        st.divider()

        st.markdown("##### Export")
        e1, e2 = st.columns([3, 1])
        e1.text_input("DOCX path", key="export_docx_path")
        e2.number_input("Font size", key="export_font_size", min_value=6, max_value=16)

    # ─────────────────────────────────────────────
    # CONFIG PREVIEW
    # ─────────────────────────────────────────────
    with tab_preview:
        st.caption("Merged config (read-only)")
        st.json(cfg)

        if st.button("Reset to defaults"):
            if CONFIG_LOCAL.exists():
                CONFIG_LOCAL.unlink()
            st.session_state.pop("_init_done", None)
            st.rerun()

    # persist
    _write_config_local()

# ── page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="C++ Analyzer", page_icon="📄", layout="wide")
_init()

st.markdown("""
<style>

/* ─────────────────────────────────────────────
   MAIN LAYOUT
───────────────────────────────────────────── */

section.main, [data-testid="stMain"] {
    overflow: hidden !important;
    background: linear-gradient(
        to right,
        color-mix(in srgb, var(--secondary-background-color) 72%, #808080 28%) 50%,
        transparent 50%
    ) !important;
}

.block-container, [data-testid="stMainBlockContainer"] {
    background: transparent !important;
    overflow: hidden !important;
    max-width: 100% !important;
    padding-top: 4rem !important;
    padding-bottom: 0 !important;
}

/* App title */
[data-testid="stHeader"]::before {
    content: "C++ Analyzer";
    position: absolute;
    left: 1rem;
    top: 50%;
    transform: translateY(-50%);
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    pointer-events: none;
}

/* ─────────────────────────────────────────────
   SPLIT PANES (UNIFIED SYSTEM)
───────────────────────────────────────────── */

[data-testid="stHorizontalBlock"] {
    align-items: stretch !important;
}

/* BOTH PANES SAME RULES (NO FIRST/LAST CHILD) */
[data-testid="stHorizontalBlock"] > div {
    background: transparent !important;

    height: auto !important;
    min-height: unset !important;

    overflow-y: auto !important;
    max-height: calc(100vh - 5rem);

    padding: 1rem !important;
    box-sizing: border-box !important;
}

/* ─────────────────────────────────────────────
   GLOBAL SPACING SYSTEM (BOTH PANES)
───────────────────────────────────────────── */

[data-testid="stHorizontalBlock"] [data-testid="stVerticalBlock"] {
    gap: 0.5rem !important;
}

/* Card padding consistency */
[data-testid="stHorizontalBlock"] [data-testid="stVerticalBlockBorderWrapper"] > div {
    padding: 0.5rem 1rem !important;
}

/* Tight widgets */
[data-testid="stHorizontalBlock"] [data-testid="stElementContainer"] {
    padding-top: 0.1rem !important;
    padding-bottom: 0.1rem !important;
}

/* ─────────────────────────────────────────────
   CAPTIONS (GLOBAL)
───────────────────────────────────────────── */

[data-testid="stCaptionContainer"] p {
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.07em !important;
    text-transform: uppercase !important;
    opacity: 0.55 !important;
    margin: 0 0 0.35rem 0 !important;
}

/* ─────────────────────────────────────────────
   RIGHT PANEL SCROLL BEHAVIOR
───────────────────────────────────────────── */

[data-testid="stHorizontalBlock"] > div:last-child {
    overflow: hidden !important;
}

[data-testid="stHorizontalBlock"] > div:last-child [role="tabpanel"] {
    overflow-y: auto !important;
    max-height: calc(100vh - 11rem) !important;
}

/* ─────────────────────────────────────────────
   INPUT + BUTTON DENSITY
───────────────────────────────────────────── */

input, textarea {
    padding-top: 0.25rem !important;
    padding-bottom: 0.25rem !important;
}

button {
    white-space: nowrap !important;
}

/* ─────────────────────────────────────────────
   THEME
───────────────────────────────────────────── */

:root {
    --primary-color: #4F6EF7 !important;
}

/* Tabs */
[data-baseweb="tab-highlight"] {
    background-color: #4F6EF7 !important;
}
[data-baseweb="tab"][aria-selected="true"],
[data-baseweb="tab"]:hover {
    color: #4F6EF7 !important;
}
[data-baseweb="tab"]:focus {
    box-shadow: inset 0 -3px 0 0 #4F6EF7 !important;
}
[data-baseweb="tab-border"] {
    background-color: rgba(79, 110, 247, 0.2) !important;
}

/* Inputs */
input:focus, textarea:focus, [data-baseweb="input"]:focus-within {
    border-color: #4F6EF7 !important;
    box-shadow: 0 0 0 1px #4F6EF7 !important;
}

/* Links */
a { color: #4F6EF7 !important; }

/* Primary buttons */
button[kind="primary"],
button[kind="primaryFormSubmit"] {
    background-color: #4F6EF7 !important;
    border-color: #4F6EF7 !important;
    color: #fff !important;
}
button[kind="primary"]:hover,
button[kind="primaryFormSubmit"]:hover {
    background-color: #3B5BDB !important;
    border-color: #3B5BDB !important;
}
button[kind="primary"]:active,
button[kind="primaryFormSubmit"]:active {
    background-color: #364FC7 !important;
    border-color: #364FC7 !important;
}

/* Stop button */
.st-key-_stop_btn button {
    margin: 0.75rem !important;
    width: calc(100% - 1.5rem) !important;
    background-color: rgba(220, 53, 69, 0.15) !important;
    border-color: rgba(220, 53, 69, 0.5) !important;
    color: #f08090 !important;
}
.st-key-_stop_btn button:hover {
    background-color: rgba(220, 53, 69, 0.28) !important;
    border-color: rgba(220, 53, 69, 0.7) !important;
}

/* Floating settings button */
.st-key-_settings_fab {
    position: fixed !important;
    bottom: 1.5rem !important;
    right: 1.5rem !important;
    z-index: 9999 !important;
    height: 0 !important;
    overflow: visible !important;
}
.st-key-_settings_fab button {
    border-radius: 50% !important;
    width: 2.8rem !important;
    height: 2.8rem !important;
    padding: 0 !important;
    font-size: 1.2rem !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25) !important;
}

/* ─────────────────────────────────────────────
   DIALOG (UNCHANGED BUT CLEANED)
───────────────────────────────────────────── */

div[role="dialog"] {
    max-width: min(95vw, 1400px) !important;
    width: min(95vw, 1400px) !important;
}

[data-testid="stDialog"] {
    overflow: hidden !important;
}

[data-testid="stDialog"] > div:last-child {
    overflow-y: auto !important;
    max-height: 82vh !important;
}

[data-testid="stDialog"] div[role="tabpanel"] {
    overflow-y: auto !important;
    max-height: 70vh !important;
}

[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    gap: 0.25rem !important;
}

[data-testid="stDialog"] [data-testid="stVerticalBlockBorderWrapper"] > div {
    padding: 0.5rem 0.75rem !important;
}

[data-testid="stDialog"] label {
    font-size: 0.72rem !important;
    opacity: 0.6 !important;
}

[data-testid="stDialog"] hr {
    margin: 0.4rem 0 !important;
}

/* ─────────────────────────────────────────────
   SCROLLBAR CLEAN
───────────────────────────────────────────── */

* {
    scrollbar-width: thin;
    scrollbar-color: transparent transparent;
}

</style>
""", unsafe_allow_html=True)

components.html("""
<script>
(function(){
    var p=window.parent.document;
    function isDark(){var el=p.querySelector('[data-testid="stApp"]')||p.body;var rgb=getComputedStyle(el).backgroundColor;var m=rgb.match(/\d+/);return m?parseInt(m[0])<128:false;}
    function apply(){var b=p.querySelector('[data-testid="stHorizontalBlock"]');if(!b||b.children.length<2)return;b.children[0].style.setProperty('background',isDark()?'#1a1d2e':'#dde0e8','important');b.children[1].style.removeProperty('background');}
    apply();var t;new MutationObserver(function(){clearTimeout(t);t=setTimeout(apply,80);}).observe(p.documentElement,{childList:true,subtree:true,attributes:true});
})();
</script>
""", height=0)

# ── run state ────────────────────────────────────────────────────────────────

_rs        = _run_state()
running    = _rs["running"]
log_lines: list[str] = _rs["lines"]
returncode = _rs["returncode"]

# ── layout ────────────────────────────────────────────────────────────────────

col_left, col_right = st.columns([1, 1])

with col_left:

    # ───────────────────────── PROJECT ─────────────────────────
    with st.container():
        st.caption("Project")
        _path_row("", "project_path", is_dir=True)

    st.divider()

    # ───────────────────────── GROUP ─────────────────────────
    st.caption("Group")

    groups = [
        st.session_state.get(f"g{g['gid']}_name", g["name"]).strip()
        for g in st.session_state.get("groups", [])
    ]
    groups = [g for g in groups if g]

    c1, c2 = st.columns([5, 1])

    with c1:
        sel = st.selectbox(
            "Select group",
            options=["All"] + groups if groups else ["All"],
            key="export_group_sel",
            label_visibility="collapsed"
        )

    with c2:
        st.button("✎", on_click=_groups_dialog, use_container_width=True)

    selected_group = None if sel == "All" else sel

    st.divider()

    # ───────────────────────── RUN ─────────────────────────
    st.caption("Run")

    run_type = st.session_state.get("_run_type")

    # RUNNING STATE
    if running:
        
        st.button(
            "Stop",
            key="_stop_btn",
            use_container_width=True,
            type="secondary",
            on_click=_stop_pipeline
        )

        if run_type == "full":
            log_text = "\n".join(log_lines)
            phases_done = sum(f"Phase {n}" in log_text for n in [1, 2, 3, 4])
            current_phase = min(phases_done + 1, 4)

            st.progress(phases_done / 4)
            st.caption(f"{PHASE_NAMES.get(current_phase, '')}")
        else:
            st.progress(0.5)
            st.caption("Exporting DOCX…")


    # IDLE STATE (COMPACT SINGLE LINE)
    else:

        c1, c2 = st.columns([1, 1])

        with c1:
            st.button(
                "Run full",
                type="primary",
                use_container_width=True,
                on_click=lambda: _run_full(selected_group)
            )
            st.caption("Full pipeline → DOCX")

        with c2:
            st.button(
                "Export Only",
                type="secondary",
                use_container_width=True,
                on_click=lambda: _run_export(selected_group)
            )
            st.caption("Existing model → DOCX")


    # RESULT STATE
    if not running and returncode is not None:
        if returncode == 0:
            st.success("Done")
            st.session_state["_run_success"] = True
        else:
            st.error("Failed")

        st.session_state["_run_type"] = None

    # ───────────────────────── OUTPUT ─────────────────────────
    docx_files = sorted((ROOT / "output").rglob("*.docx")) if (ROOT / "output").exists() else []

    if st.session_state.get("_run_success") and docx_files:

        st.divider()
        st.caption("Outputs")

        for dp in docx_files:
            with open(dp, "rb") as fh:
                st.download_button(
                    f"⬇ {dp.name}",
                    data=fh,
                    file_name=dp.name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"dl_{dp}",
                    use_container_width=True
                )
    


# ════════════════════════════════════════════════════════════════════════════
# RIGHT — preview
# ════════════════════════════════════════════════════════════════════════════

with col_right:

    tab_mg, tab_output = st.tabs(["Modules Groups", "Pipeline Output"])

    def _js_click_tab(label: str):
        components.html(f"""<script>
        (function(){{
            var p=window.parent.document;
            function click(){{
                var tabs=p.querySelectorAll('[data-baseweb="tab"]');
                for(var t of tabs){{ if(t.textContent.trim()==={label!r}){{t.click();return true;}} }}
                return false;
            }}
            if(!click()) setTimeout(click, 200);
        }})();
        </script>""", height=0)

    if st.session_state.pop("_switch_to_log", False):
        _js_click_tab("Pipeline Output")

    if st.session_state.pop("_switch_to_preview", False):
        _js_click_tab("Modules Groups")

with tab_mg:
    if running and st.session_state.get("_run_type") == "full":
        st.info("Pipeline is running — content unavailable until complete.", icon="⏳")
    else:
        _units_all   = _load_json(ROOT / "model" / "units.json")
        _modules_all = _load_json(ROOT / "model" / "modules.json")
        _funcs_all   = _load_json(ROOT / "model" / "functions.json")

        groups = st.session_state.get("groups", [])

        for g in groups:
            gid   = g["gid"]
            gname = st.session_state.get(f"g{gid}_name", g["name"]).strip() or "(unnamed)"

            with st.expander(f"📁 {gname}", expanded=True):

                for m in g["modules"]:
                    mid   = m["mid"]
                    mname = st.session_state.get(f"m{mid}_name", m["mod"]).strip() or "(unnamed)"

                    with st.expander(f"📦 {mname}"):

                        unit_ids = _modules_all.get(mname, {}).get("units", [])

                        for uid in unit_ids:
                            udata = _units_all.get(uid, {})
                            uname = udata.get("name", uid)

                            with st.expander(f"📄 {uname}"):

                                fids = udata.get("functionIds", [])

                                for fid in fids:
                                    parts = fid.split("|")
                                    fname = parts[2] if len(parts) > 2 else fid

                                    if st.button(f"{fname}()", key=f"fn_{fid}", use_container_width=True):
                                        _function_dialog(fid, _units_all, _funcs_all)

with tab_output:
    cmd_str = _rs.get("cmd", "")
    if cmd_str:
        st.code(cmd_str, language="bash")
    if log_lines:
        st.code("\n".join(reversed(log_lines[-120:])), language="bash")
    else:
        st.markdown(
            """
            <div style="
                height: 60vh;
                display: flex;
                align-items: center;
                justify-content: center;
                opacity: 0.6;
                font-size: 0.9rem;
                text-align: center;
            ">
                No output yet — run the pipeline to see output here.
            </div>
            """,
            unsafe_allow_html=True
        )


# ── floating settings button ─────────────────────────────────────────────────

st.button("⚙", key="_settings_fab", disabled=True)

# ── polling + auto-save ───────────────────────────────────────────────────────

if running:
    time.sleep(0.8)
    st.rerun()

if st.session_state.get("_init_done"):
    _write_config_local()
