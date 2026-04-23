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
    st.session_state.setdefault("project_path",  last.get("project_path") or (str(sample) if sample.exists() else ""))
    st.session_state.setdefault("from_phase",     last.get("from_phase",    1))

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

@st.dialog("Function", width="extra-large")
def _function_dialog(fid: str, units_all, func_iface):

    entry = func_iface.get(fid)

    if not entry:
        st.info("No data")
        return

    fname = entry.get("name", fid)

    # ─────────────────────────────────────────────
    # HEADER
    # ─────────────────────────────────────────────
    st.markdown(f"### `{fname}()`")

    meta = []
    if entry.get("interfaceId"):
        meta.append(f"`{entry['interfaceId']}`")
    if entry.get("direction"):
        meta.append(entry["direction"])
    if entry.get("type"):
        meta.append(entry["type"])

    if meta:
        st.caption(" · ".join(meta))

    loc = entry.get("location", {})
    if loc:
        st.caption(f"{loc.get('file','?')}:{loc.get('line','?')}")

    st.divider()

    # ─────────────────────────────────────────────
    # MAIN SPLIT
    # ─────────────────────────────────────────────
    left, right = st.columns([2, 3])  # 👈 flowchart gets more space

    # =================================================
    # LEFT SIDE — DETAILS (compact)
    # =================================================
    with left:

        # Signature
        params = entry.get("parameters", [])
        if params:
            sig_parts = []
            for p in params:
                pname = p.get("name", "") if isinstance(p, dict) else str(p)
                ptype = p.get("type", "") if isinstance(p, dict) else ""
                sig_parts.append(f"{ptype} {pname}".strip())

            st.code(f"{fname}({', '.join(sig_parts)})")
        else:
            st.code(f"{fname}()")

        # Call graph
        callers = entry.get("callerUnits", [])
        callees = entry.get("calleesUnits", [])

        if callers:
            st.caption("Called by")
            st.code(", ".join(callers))

        if callees:
            st.caption("Calls")
            st.code(", ".join(callees))

        # Extra
        if entry.get("sourceDest"):
            st.caption("Source / Dest")
            st.code(entry["sourceDest"])

        if entry.get("reason"):
            st.caption("Reason")
            st.write(entry["reason"])

    # =================================================
    # RIGHT SIDE — FLOWCHART (hero)
    # =================================================
    with right:

        parts = fid.split("|")
        fname2 = parts[2] if len(parts) > 2 else ""

        unit_name = ""
        for u in units_all.values():
            if fid in u.get("functionIds", []):
                unit_name = u.get("name", "")
                break

        png_path = ROOT / "output" / "flowcharts" / f"{unit_name}_{fname2}.png"

        if png_path.exists():
            img_b64 = base64.b64encode(png_path.read_bytes()).decode()
            st.markdown(
                f'<div style="display:flex;align-items:center;justify-content:center;height:72vh;">'
                f'<img src="data:image/png;base64,{img_b64}" style="max-height:70vh;max-width:100%;object-fit:contain;">'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            fc_json = ROOT / "output" / "flowcharts" / f"{unit_name}.json"
            if fc_json.exists():
                fc_data = _load_json(fc_json)
                fc_entry = next(
                    (e for e in (fc_data if isinstance(fc_data, list) else [])
                     if e.get("name") == fname2),
                    None,
                )
                if fc_entry:
                    st.code(fc_entry["flowchart"], language="text")
                else:
                    st.caption("No flowchart")
            else:
                st.caption("No flowchart")

@st.dialog("Module Groups", width="large")
def _groups_dialog():
    groups = st.session_state.get("groups", [])

    h1, h2 = st.columns([5, 1], vertical_alignment="bottom")
    with h1:
        st.caption("One DOCX per group · paths relative to project root.")
    with h2:
        st.button("＋ Group", on_click=_add_group, use_container_width=True)

    if not groups:
        st.info("No groups yet — click **＋ Group** to get started.", icon="ℹ️")

    for group in groups:
        gid = group["gid"]
        st.markdown("---")

        # group name row
        ga, gb = st.columns([5, 1], vertical_alignment="bottom")
        with ga:
            st.text_input("Group", key=f"g{gid}_name", value=group["name"],
                          placeholder="group-name")
        with gb:
            st.button("🗑 Delete", key=f"del_g{gid}", on_click=_remove_group,
                      args=(gid,), use_container_width=True)

        for mod in group["modules"]:
            mid = mod["mid"]
            with st.container():
                # module name row
                ma, mb = st.columns([5, 1], vertical_alignment="bottom")
                with ma:
                    st.text_input("Module", key=f"m{mid}_name", value=mod["mod"],
                                  placeholder="module-name")
                with mb:
                    st.button("✕", key=f"del_m{mid}", on_click=_remove_module,
                              args=(gid, mid), use_container_width=True, help="Remove module")

                # paths
                for path_entry in mod["paths"]:
                    pid = path_entry["pid"]
                    pa, pb, pc = st.columns([5, 1, 0.5], vertical_alignment="bottom")
                    with pa:
                        st.text_input("Path", key=f"p{pid}_path", value=path_entry["path"],
                                      placeholder="relative/path/to/sources",
                                      label_visibility="collapsed")
                    with pb:
                        st.button("Browse", key=f"_browse_p{pid}_path",
                                  on_click=_pick_folder, args=(f"p{pid}_path",),
                                  use_container_width=True)
                    with pc:
                        st.button("✕", key=f"del_p{pid}", on_click=_remove_path,
                                  args=(mid, pid), use_container_width=True,
                                  disabled=len(mod["paths"]) <= 1)

                st.button("＋ path", key=f"add_p_{mid}", on_click=_add_path, args=(mid,))

        st.button("＋ module", key=f"add_m_{gid}", on_click=_add_module, args=(gid,))

    st.markdown("---")
    if st.button("Save", type="primary", use_container_width=True):
        _write_config_local()
        st.rerun()

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
   MAIN LAYOUT (2-PANE)
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


/* App title in the Streamlit toolbar (where Deploy lives) */
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
   SPLIT PANES (FIXED HEIGHT ISSUE)
───────────────────────────────────────────── */

[data-testid="stHorizontalBlock"] {
    align-items: stretch !important;
}

/* 🚨 FIX: remove forced full-height */
[data-testid="stHorizontalBlock"] > div {
    background: transparent !important;
    height: auto !important;
    min-height: unset !important;
}

/* Left panel */
[data-testid="stHorizontalBlock"] > div:first-child {
    overflow-y: auto !important;
    max-height: calc(100vh - 5rem);
    border-right: 1px solid rgba(128,128,128,0.25) !important;
    padding: 1.25rem 1.5rem 2rem 1.5rem !important;
}

/* Card spacing — gap between Project / Module Groups / Run cards */
[data-testid="stHorizontalBlock"] > div:first-child > [data-testid="stVerticalBlock"] {
    gap: 0.75rem !important;
}

/* Card internal padding */
[data-testid="stHorizontalBlock"] > div:first-child [data-testid="stVerticalBlockBorderWrapper"] > div {
    padding: 0.75rem 1rem !important;
}

/* Tighten elements inside left panel cards */
[data-testid="stHorizontalBlock"] > div:first-child [data-testid="stElementContainer"] {
    padding-top: 0.1rem !important;
    padding-bottom: 0.1rem !important;
}

/* Section caption labels */
[data-testid="stHorizontalBlock"] > div:first-child [data-testid="stCaptionContainer"] p {
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.07em !important;
    text-transform: uppercase !important;
    opacity: 0.5 !important;
    margin-bottom: 0.35rem !important;
    margin-top: 0 !important;
}

/* Right panel — prevent outer scroll */
[data-testid="stHorizontalBlock"] > div:last-child {
    overflow: hidden !important;
    max-height: calc(100vh - 5rem);
}

/* Tab content scrolls; tab bar stays fixed */
[data-testid="stHorizontalBlock"] > div:last-child [role="tabpanel"] {
    overflow-y: auto !important;
    overflow-x: hidden !important;
    max-height: calc(100vh - 11rem) !important;
}

/* Nested layouts reset */
[data-testid="stHorizontalBlock"] div [data-testid="stHorizontalBlock"] > div {
    height: auto !important;
    min-height: unset !important;
    overflow-y: visible !important;
    background: transparent !important;
    border-right: none !important;
    padding: unset !important;
}

/* ─────────────────────────────────────────────
   SMALL UI ELEMENTS
───────────────────────────────────────────── */


button[kind="secondary"] {
    white-space: nowrap !important;
}

/* Floating settings button — zero-height anchor so panels stay full width */
.st-key-_settings_fab {
    position: fixed !important;
    bottom: 1.5rem !important;
    right: 1.5rem !important;
    z-index: 9999 !important;
    height: 0 !important;
    overflow: visible !important;
    margin: 0 !important;
    padding: 0 !important;
    width: auto !important;
}
.st-key-_settings_fab button {
    border-radius: 50% !important;
    width: 2.8rem !important;
    height: 2.8rem !important;
    padding: 0 !important;
    font-size: 1.2rem !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25) !important;
    min-width: unset !important;
    position: relative !important;
}

/* ─────────────────────────────────────────────
   SETTINGS DIALOG (FIXED HEIGHT + GAPS)
───────────────────────────────────────────── */

[data-testid="stDialog"] {
    overflow: hidden !important;
}

/* Widen the actual dialog box */
div[role="dialog"] {
    max-width: min(95vw, 1400px) !important;
    width: min(95vw, 1400px) !important;
}
div[role="dialog"] > div {
    max-width: 100% !important;
    width: 100% !important;
}

/* Outer dialog scroll */
[data-testid="stDialog"] > div:last-child {
    overflow-y: auto !important;
    max-height: 82vh !important;
}

/* Tabs content */
[data-testid="stDialog"] div[role="tabpanel"] {
    overflow-y: auto !important;
    overflow-x: hidden !important;
    max-height: 70vh !important;
    padding-bottom: 0.4rem !important;
}

/* Tighten vertical rhythm inside dialogs */
[data-testid="stDialog"] [data-testid="stVerticalBlock"] {
    gap: 0.4rem !important;
}

/* Reduce element container padding */
[data-testid="stDialog"] [data-testid="stElementContainer"] {
    padding-top: 0.1rem !important;
    padding-bottom: 0.1rem !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
}

/* Compact labels */
[data-testid="stDialog"] label {
    margin-bottom: 0.1rem !important;
    padding-bottom: 0 !important;
    font-size: 0.72rem !important;
    opacity: 0.6 !important;
}

/* Compact inputs */
[data-testid="stDialog"] input {
    padding-top: 0.3rem !important;
    padding-bottom: 0.3rem !important;
}

/* Section headers ONLY (not widget labels) */
[data-testid="stDialog"] 
[data-testid="stMarkdown"] 
[data-testid="stMarkdownContainer"] > p {
    margin-top: 0.35rem !important;
    margin-bottom: 0.1rem !important;
}

/* Dividers */
[data-testid="stDialog"] hr {
    margin-top: 0.4rem !important;
    margin-bottom: 0.2rem !important;
}

/* Flowchart image — fit and center inside dialog */
[data-testid="stDialog"] img {
    max-height: 72vh !important;
    object-fit: contain !important;
    width: auto !important;
    max-width: 100% !important;
    display: block !important;
    margin: auto !important;
}


/* Remove widget spacing noise */
[data-testid="stDialog"] [data-testid="stRadio"],
[data-testid="stDialog"] [data-testid="stCheckbox"],
[data-testid="stDialog"] [data-testid="stTextInput"],
[data-testid="stDialog"] [data-testid="stNumberInput"] {
    margin: 0 !important;
    padding: 0 !important;
}

/* Captions (if used) */
[data-testid="stDialog"] [data-testid="stCaptionContainer"] {
    margin-top: 0.3rem !important;
    margin-bottom: 0 !important;
}

/* ─────────────────────────────────────────────
   LEFT PANEL CARD HIERARCHY
───────────────────────────────────────────── */

/* Sticky title block */
[data-testid="stHorizontalBlock"] > div:first-child > [data-testid="stVerticalBlock"] > div:first-child {
    position: sticky;
    top: 0;
    z-index: 10;
    background: inherit;
    padding-bottom: 0.25rem;
}

/* Section caption labels */
[data-testid="stHorizontalBlock"] [data-testid="stCaptionContainer"] p {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.55;
    margin-bottom: 0.4rem !important;
}

/* Tighten left panel input density */
[data-testid="stHorizontalBlock"] > div:first-child input {
    padding-top: 0.25rem !important;
    padding-bottom: 0.25rem !important;
}


/* ─────────────────────────────────────────────
   SCROLLBAR CLEANUP (OPTIONAL)
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

# ════════════════════════════════════════════════════════════════════════════
# LEFT — workflow
# ════════════════════════════════════════════════════════════════════════════

with col_left:

    # ── Card 1: Project ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.caption("PROJECT")
        _path_row("Project folder", "project_path", is_dir=True,
                  help="Root folder of the C++ source project")

    # ── Card 2: Run ──────────────────────────────────────────────────────────
    current_group_names = [st.session_state.get(f"g{g['gid']}_name", g["name"]).strip() for g in st.session_state.get("groups", [])]
    current_group_names = [n for n in current_group_names if n]
    selected_group: str | None = None

    with st.container(border=True):
        st.caption("RUN")
        s1, s2 = st.columns(2)
        with s1:
            st.selectbox("Start from phase", options=[1, 2, 3, 4], key="from_phase",
                         format_func=lambda n: f"Phase {n} — {PHASE_NAMES[n]}",
                         )
        with s2:
            if current_group_names:
                sel = st.selectbox("Export group", options=["(all groups)"] + current_group_names,
                                   key="export_group_sel",
                                   on_change=lambda: st.session_state.update(_switch_to_preview=True))
                selected_group = None if sel == "(all groups)" else sel
            else:
                st.selectbox("Export group", options=["(all groups)"], disabled=True,
                             help="Define groups in Module Groups above")
                st.session_state["export_group_sel"] = "(all groups)"

        if not running:
            if st.button("Generate DOCX", type="primary", use_container_width=True):
                proj = (st.session_state.get("project_path") or "").strip()
                if not proj:
                    st.error("Project path is required."); st.stop()
                if not Path(proj).exists():
                    st.error(f"Path does not exist:\n{proj}"); st.stop()

                _write_config_local()
                cmd = [sys.executable, str(ROOT / "run.py")]
                phase = st.session_state.get("from_phase", 1)
                if phase in (2, 3): cmd.append("--use-model")
                if phase > 1: cmd += ["--from-phase", str(phase)]
                if selected_group: cmd += ["--selected-group", selected_group]
                if not any(st.session_state.get(k) for k in ("llm_descriptions", "llm_behav_names", "llm_summarize")):
                    cmd.append("--no-llm-summarize")
                cmd.append(proj)
                _start_pipeline(cmd)
                st.session_state["_switch_to_log"] = True
                st.rerun()
        else:
            st.button("Stop", type="secondary", on_click=_stop_pipeline, use_container_width=True)

        # ── Downloads (shown after successful run) ────────────────────────────
        if not running and returncode == 0:
            docx_files = sorted((ROOT / "output").rglob("*.docx")) if (ROOT / "output").exists() else []
            if docx_files:
                st.success("Completed — download below.")
                dl_cols = st.columns(min(len(docx_files), 2))
                for i, dp in enumerate(docx_files):
                    with dl_cols[i % 2]:
                        with open(dp, "rb") as fh:
                            st.download_button(f"⬇ {dp.name}", data=fh, file_name=dp.name,
                                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                               key=f"dl_{dp}", use_container_width=True, type="primary")

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

    if running:
        st.info("Pipeline is running — content unavailable until complete.", icon="⏳")

    else:
        # ── load model data ───────────────────────────────
        _units_all   = _load_json(ROOT / "model" / "units.json")
        _modules_all = _load_json(ROOT / "model" / "modules.json")
        _iface_all   = _load_json(ROOT / "output" / "interface_tables.json")

        # map function → interface
        _func_iface = {}
        for _ik, _iv in _iface_all.items():
            if _ik == "unitNames" or not isinstance(_iv, dict):
                continue
            for _e in _iv.get("entries", []):
                if _fid := _e.get("functionId", ""):
                    _func_iface[_fid] = _e

        # Header
        hc1, hc2 = st.columns([6, 1])
        with hc1:
            st.caption("MODULE GROUPS")
        with hc2:
            if st.button("Edit", key="_mg_open", use_container_width=True):
                _groups_dialog()

        st.divider()

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

                                    if st.button(f"⚡ {fname}()", key=f"fn_{fid}", use_container_width=True):
                                        _function_dialog(fid, _units_all, _func_iface)


# ── floating settings button ─────────────────────────────────────────────────

st.button("⚙", key="_settings_fab", disabled=True)

# ── polling + auto-save ───────────────────────────────────────────────────────

if running:
    time.sleep(0.8)
    st.rerun()

if st.session_state.get("_init_done"):
    _write_config_local()
