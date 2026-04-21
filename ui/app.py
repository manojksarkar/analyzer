"""
C++ Analyzer — DOCX Generator UI
Run with: streamlit run ui/app.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

# ── path picker helpers ───────────────────────────────────────────────────────

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


def _pick_file(key: str, filetypes: list | None = None):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    path = filedialog.askopenfilename(filetypes=filetypes or [("All files", "*.*")])
    root.destroy()
    if path:
        st.session_state[key] = path


def _path_row(label: str, key: str, is_dir: bool = False,
              filetypes: list | None = None, disabled: bool = False, help: str = ""):
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    with c1:
        st.text_input(label, key=key, disabled=disabled, help=help)
    with c2:
        st.button("Browse",
                  key=f"_browse_{key}",
                  disabled=disabled,
                  on_click=_pick_folder if is_dir else _pick_file,
                  args=(key,) if is_dir else (key, filetypes),
                  use_container_width=True)


# ── constants ─────────────────────────────────────────────────────────────────

ROOT         = Path(__file__).resolve().parent.parent
CONFIG_JSON  = ROOT / "config" / "config.json"
CONFIG_LOCAL = ROOT / "config" / "config.local.json"
LAST_RUN     = ROOT / "config" / "last_run.json"

PHASE_NAMES = {1: "Parse", 2: "Derive", 3: "Views", 4: "Export"}
PHASE_ORDER = ["Parse", "Derive", "Views", "Export"]

# ── persistent run store ──────────────────────────────────────────────────────

@st.cache_resource
def _get_runs() -> dict:
    return {}


def _run_state() -> dict:
    runs = _get_runs()
    sid = st.session_state.setdefault("_sid", str(uuid.uuid4()))
    if sid not in runs:
        runs[sid] = {"lines": [], "running": False, "returncode": None, "proc": None, "cmd": ""}
    return runs[sid]


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
    st.session_state.setdefault("project_path",   last.get("project_path") or (str(sample) if sample.exists() else ""))
    st.session_state.setdefault("flag_clean",      last.get("flag_clean",     False))
    st.session_state.setdefault("flag_use_model",  last.get("flag_use_model", False))
    st.session_state.setdefault("from_phase",      last.get("from_phase",     1))

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
    st.session_state.setdefault("llm_max_ctx_tokens", "" if max_ctx is None else str(max_ctx))
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
    gid = st.session_state["_next_gid"]
    mid = st.session_state["_next_mid"]
    pid = st.session_state["_next_pid"]
    st.session_state["groups"].append({
        "gid": gid, "name": "",
        "modules": [{"mid": mid, "mod": "", "paths": [{"pid": pid, "path": ""}]}],
    })
    st.session_state["_next_gid"] = gid + 1
    st.session_state["_next_mid"] = mid + 1
    st.session_state["_next_pid"] = pid + 1

def _remove_group(gid: int):
    st.session_state["groups"] = [g for g in st.session_state["groups"] if g["gid"] != gid]

def _add_module(gid: int):
    mid = st.session_state["_next_mid"]
    pid = st.session_state["_next_pid"]
    for g in st.session_state["groups"]:
        if g["gid"] == gid:
            g["modules"].append({"mid": mid, "mod": "", "paths": [{"pid": pid, "path": ""}]})
    st.session_state["_next_mid"] = mid + 1
    st.session_state["_next_pid"] = pid + 1

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
            paths = [
                st.session_state.get(f"p{p['pid']}_path", p["path"]).strip()
                for p in m["paths"]
            ]
            paths = [p for p in paths if p]
            if not paths:
                continue
            mods[mname] = paths[0] if len(paths) == 1 else paths
        if mods:
            result[gname] = mods
    return result


# ── config.local.json writer ──────────────────────────────────────────────────

def _write_config_local():
    cfg: dict[str, Any] = {}

    clang: dict[str, Any] = {}
    if v := st.session_state.get("llvm_lib", "").strip():
        clang["llvmLibPath"] = v
    if v := st.session_state.get("clang_include", "").strip():
        clang["clangIncludePath"] = v
    extra = [a for a in st.session_state.get("clang_args", "").split() if a]
    if extra:
        clang["clangArgs"] = extra
    if clang:
        cfg["clang"] = clang

    cfg["views"] = {
        "interfaceTables": True,
        "unitDiagrams":    {"renderPng": st.session_state["v_unit_png"]},
        "flowcharts": {
            "scriptPath": st.session_state["v_flow_script"],
            "renderPng":  st.session_state["v_flow_png"],
        },
        "behaviourDiagram":   {"renderPng": st.session_state["v_behav_png"]},
        "moduleStaticDiagram": {
            "enabled":     st.session_state["v_msd_enabled"],
            "renderPng":   st.session_state["v_msd_png"],
            "widthInches": st.session_state["v_msd_width"],
        },
    }

    cfg["export"] = {
        "docxPath":     st.session_state["export_docx_path"],
        "docxFontSize": st.session_state["export_font_size"],
    }

    mg = _groups_to_config()
    if mg:
        cfg["modulesGroups"] = mg

    provider = st.session_state.get("llm_provider", "ollama")
    llm_block: dict[str, Any] = {
        "descriptions":   st.session_state.get("llm_descriptions", False),
        "behaviourNames": st.session_state.get("llm_behav_names",  False),
        "summarize":      st.session_state.get("llm_summarize",    False),
        "provider":       provider,
        "defaultModel":   st.session_state.get("llm_model",   "llama"),
        "timeoutSeconds": st.session_state.get("llm_timeout", 120),
        "numCtx":         st.session_state.get("llm_ctx",     8192),
        "retries":        st.session_state.get("llm_retries", 1),
        "abbreviationsPath":  st.session_state.get("llm_abbrev_path",  "config/abbreviations.txt"),
        "fewShotExamplesDir": st.session_state.get("llm_few_shot_dir", "few_shot_examples"),
        "cacheVersion":       st.session_state.get("llm_cache_version", 1),
        "enrichment": {
            "twoPassDescriptions": st.session_state.get("llm_enr_two_pass",     False),
            "selfReview":          st.session_state.get("llm_enr_self_review",  False),
            "ensemble":            st.session_state.get("llm_enr_ensemble",     False),
            "cfgSimplification":   st.session_state.get("llm_enr_cfg_simplify", False),
            "variableEnrichment":  st.session_state.get("llm_enr_var_enrich",   True),
        },
    }
    # Always write baseUrl so a shallow-merging pipeline never loses it from config.json.
    # Fall back to the Ollama default if the user left the field blank.
    url = st.session_state.get("llm_url", "").strip() or "http://localhost:11434"
    llm_block["baseUrl"] = url
    if provider == "openai":
        llm_block["apiKey"] = st.session_state.get("llm_api_key", "")
    try:
        ch = json.loads(st.session_state.get("llm_custom_headers", "{}") or "{}")
    except json.JSONDecodeError:
        ch = {}
    if ch:
        llm_block["customHeaders"] = ch
    max_ctx = (st.session_state.get("llm_max_ctx_tokens") or "").strip()
    llm_block["maxContextTokens"] = int(max_ctx) if max_ctx.isdigit() else None
    cfg["llm"] = llm_block

    CONFIG_LOCAL.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _save_last_run()


def _save_last_run():
    """Persist project path + run flags alongside config so the full run state survives restarts."""
    run_state = {
        "project_path":   st.session_state.get("project_path", ""),
        "flag_clean":     st.session_state.get("flag_clean", False),
        "flag_use_model": st.session_state.get("flag_use_model", False),
        "from_phase":     st.session_state.get("from_phase", 1),
    }
    LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN.write_text(json.dumps(run_state, indent=2), encoding="utf-8")


def _load_last_run() -> dict:
    return _load_json(LAST_RUN)


# ── pipeline runner ───────────────────────────────────────────────────────────

_PHASE_RE = re.compile(r"=== Phase \d+: (.+?) ===")
_TS_RE    = re.compile(r"^\[[\d:.]+\] (.+)$")


def _current_phase(lines: list[str]) -> str:
    for line in reversed(lines):
        m = _PHASE_RE.search(line)
        if m:
            return m.group(1)
    return ""


def _last_activity(lines: list[str]) -> str:
    for line in reversed(lines):
        s = line.strip()
        if s and not s.startswith("===") and not s.startswith("---"):
            m = _TS_RE.match(s)
            return m.group(1) if m else s
    return ""


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
        state["lines"].append(f"ERROR: {exc}")
        state["returncode"] = -1
    finally:
        state["running"] = False


def _start_pipeline(cmd: list[str]):
    state = _run_state()
    state.update(lines=[], running=True, returncode=None, proc=None, cmd=" ".join(cmd))
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
    state["lines"].append("— stopped by user —")


# ── page setup ────────────────────────────────────────────────────────────────

st.set_page_config(page_title="C++ Analyzer", page_icon="📄", layout="wide")
_init()

st.markdown("""
<style>
/* ── Two-column layout ──────────────────────────────────────────────── */

/* Paint the split background directly on section.main — the most reliable
   selector. Inner containers are transparent so this shows through.
   col ratio [2,3] → left = 40 %, right = 60 %.                        */
section.main, [data-testid="stMain"] {
    overflow: hidden !important;
    /* Only shade left 40 %; right side keeps the default page background. */
    background: linear-gradient(to right, #dde0e8 40%, transparent 40%) !important;
    background: linear-gradient(
        to right,
        color-mix(in srgb, var(--secondary-background-color) 72%, #808080 28%) 40%,
        transparent 40%
    ) !important;
}

/* All containers transparent — let section.main gradient show */
.block-container, [data-testid="stMainBlockContainer"] {
    background: transparent !important;
    overflow: hidden !important;
    max-width: 100% !important;
    padding-top: 1rem !important;
    padding-bottom: 0 !important;
}

/* Two-column row */
[data-testid="stHorizontalBlock"] { align-items: stretch !important; }

[data-testid="stHorizontalBlock"] > div {
    background: transparent !important;
    height: calc(100vh - 4rem);
}

[data-testid="stHorizontalBlock"] > div:first-child {
    overflow-y: auto !important;
    border-right: 1px solid rgba(128,128,128,0.3) !important;
    padding: 1.5rem 2rem 1.5rem 2rem;
}

[data-testid="stHorizontalBlock"] > div:last-child {
    overflow-y: auto !important;
    padding-left: 2rem;
    padding-top: 1.5rem;
}

/* Reset nested column divs */
[data-testid="stHorizontalBlock"] div [data-testid="stHorizontalBlock"] > div {
    height: auto !important;
    overflow-y: visible !important;
    background: transparent !important;
    border-right: none !important;
    padding: unset !important;
}

/* ── Prevent Browse buttons from wrapping ───────────────────────────────── */
button[kind="secondary"] { white-space: nowrap !important; }

/* ── Phase chips ─────────────────────────────────────────────────────────── */
.phase-chip {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 999px;
    font-size: 0.8rem;
    font-weight: 600;
    margin: 2px 3px;
}
.chip-done    { background: #d1fae5; color: #065f46; }
.chip-active  { background: #dbeafe; color: #1e3a8a; border: 1.5px solid #93c5fd; }
.chip-pending { background: #f3f4f6; color: #9ca3af; }
.activity-line {
    font-size: 0.82rem;
    color: #6b7280;
    word-break: break-all;
    margin-top: 6px;
    line-height: 1.5;
}
</style>
""", unsafe_allow_html=True)

cfg = _merged_config()

# ── Two-column layout ─────────────────────────────────────────────────────────

col_run, col_cfg = st.columns([2, 3])

# ── Panel shading via JS ─────────────────────────────────────────────────────
# st.markdown strips <script> tags; components.html() runs in a same-origin
# iframe so window.parent.document reaches the Streamlit page DOM directly.
components.html("""
<script>
(function() {
    var p = window.parent.document;
    function isDark() {
        // Read the actual rendered background of the Streamlit app root —
        // reliable regardless of CSS variable availability or OS preference.
        var el = p.querySelector('[data-testid="stApp"]') || p.body;
        var rgb = getComputedStyle(el).backgroundColor; // "rgb(R, G, B)"
        var m = rgb.match(/\d+/);
        return m ? parseInt(m[0]) < 128 : false;
    }
    function apply() {
        var block = p.querySelector('[data-testid="stHorizontalBlock"]');
        if (!block || block.children.length < 2) return;
        var dark = isDark();
        block.children[0].style.setProperty('background', dark ? '#1e2130' : '#dde0e8', 'important');
        block.children[1].style.removeProperty('background');
    }
    apply();
    // Watch DOM node changes AND attribute changes (theme toggle only
    // updates CSS/attrs — no nodes added — so attributes:true is required).
    // Debounce avoids calling apply() hundreds of times per rerender.
    var t;
    new MutationObserver(function() {
        clearTimeout(t);
        t = setTimeout(apply, 80);
    }).observe(p.documentElement, {childList:true, subtree:true, attributes:true});
})();
</script>
""", height=0)


# ════════════════════════════════════════════════════════════════════════════════
# LEFT — primary: project + run + output
# ════════════════════════════════════════════════════════════════════════════════

with col_run:
    st.markdown("## C++ Analyzer")
    st.caption("Parse a C++ source tree and export a Software Detailed Design document.")

    st.markdown("")

    # Project path
    _path_row("Project folder", "project_path", is_dir=True,
              help="Root folder of the C++ source project")

    st.markdown("")

    # Options
    o1, o2 = st.columns(2)
    with o1:
        st.checkbox("--clean", key="flag_clean",
                    help="Delete output/ and model/ before running")
    with o2:
        st.checkbox("--use-model", key="flag_use_model",
                    help="Skip phases 1–2 and reuse an existing model/")

    o3, o4 = st.columns(2)
    with o3:
        st.selectbox("Start from phase", options=[1, 2, 3, 4], key="from_phase",
                     format_func=lambda n: f"Phase {n} — {PHASE_NAMES[n]}")
    with o4:
        current_group_names = [
            st.session_state.get(f"g{g['gid']}_name", g["name"]).strip()
            for g in st.session_state.get("groups", [])
        ]
        current_group_names = [n for n in current_group_names if n]
        selected_group: str | None = None
        if current_group_names:
            sel = st.selectbox("Export group",
                               options=["(all groups)"] + current_group_names)
            selected_group = None if sel == "(all groups)" else sel
        else:
            st.selectbox("Export group", options=["(all groups)"], disabled=True,
                         help="Define groups in Module Groups →")

    st.markdown("")

    # Run / Stop
    _rs        = _run_state()
    running    = _rs["running"]
    log_lines: list[str] = _rs["lines"]
    returncode = _rs["returncode"]

    if not running:
        if st.button("Generate DOCX", type="primary", use_container_width=True):
            proj = (st.session_state.get("project_path") or "").strip()
            if not proj:
                st.error("Project path is required.")
                st.stop()
            if not Path(proj).exists():
                st.error(f"Path does not exist:\n{proj}")
                st.stop()

            _write_config_local()   # also calls _save_last_run()

            cmd = [sys.executable, str(ROOT / "run.py")]
            if st.session_state.get("flag_clean"):
                cmd.append("--clean")
            if st.session_state.get("flag_use_model"):
                cmd.append("--use-model")
            phase = st.session_state.get("from_phase", 1)
            if phase > 1:
                cmd += ["--from-phase", str(phase)]
            if selected_group:
                cmd += ["--selected-group", selected_group]
            no_llm = not any(st.session_state.get(k)
                             for k in ("llm_descriptions", "llm_behav_names", "llm_summarize"))
            if no_llm:
                cmd.append("--no-llm-summarize")
            cmd.append(proj)

            _start_pipeline(cmd)
            st.rerun()
    else:
        st.button("Stop pipeline", type="secondary", on_click=_stop_pipeline,
                  use_container_width=True)

    # Phase progress
    if running:
        phase_label  = _current_phase(log_lines)
        active_found = False
        chips_html   = '<div style="margin: 14px 0 4px 0">'
        for step in PHASE_ORDER:
            if step == phase_label:
                chips_html += f'<span class="phase-chip chip-active">⟳ {step}</span>'
                active_found = True
            elif not active_found:
                chips_html += f'<span class="phase-chip chip-done">✓ {step}</span>'
            else:
                chips_html += f'<span class="phase-chip chip-pending">{step}</span>'
        chips_html += "</div>"
        st.markdown(chips_html, unsafe_allow_html=True)

        activity = _last_activity(log_lines)
        if activity:
            st.markdown(f'<p class="activity-line">{activity}</p>', unsafe_allow_html=True)

    # Status
    if returncode is not None and not running:
        if returncode == 0:
            st.success("Completed successfully!")
        elif log_lines and "— stopped by user —" in log_lines[-1]:
            st.warning("Stopped by user.")
        else:
            st.error(f"Failed (exit {returncode})")

    # Command
    if _rs.get("cmd"):
        with st.expander("Command", expanded=False):
            st.code(_rs["cmd"], language="bash")

    # Log
    if log_lines:
        with st.expander(f"Pipeline log  —  {len(log_lines)} lines", expanded=running):
            st.code("\n".join(reversed(log_lines[-120:])), language="bash")

    # Downloads
    if returncode == 0 and not running:
        docx_files = sorted((ROOT / "output").rglob("*.docx")) if (ROOT / "output").exists() else []
        if docx_files:
            st.markdown("### Download")
            dl_cols = st.columns(min(len(docx_files), 2))
            for i, dp in enumerate(docx_files):
                with dl_cols[i % 2]:
                    with open(dp, "rb") as fh:
                        st.download_button(
                            label=f"⬇  {dp.name}",
                            data=fh,
                            file_name=dp.name,
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            key=str(dp),
                            use_container_width=True,
                        )
        else:
            st.warning("Pipeline succeeded but no .docx files were found in output/.")

    if running:
        time.sleep(0.8)
        st.rerun()


# ════════════════════════════════════════════════════════════════════════════════
# RIGHT — secondary: settings
# ════════════════════════════════════════════════════════════════════════════════

with col_cfg:
    hdr, save_col, reset_col = st.columns([3, 1, 1])
    with hdr:
        st.markdown("## Settings")
    with save_col:
        st.markdown("")
        if st.button("Save", type="primary", use_container_width=True,
                     help="Save to config.local.json"):
            _write_config_local()
            st.success("Saved.")
    with reset_col:
        st.markdown("")
        if st.button("Reset", type="secondary", use_container_width=True,
                     help="Discard config.local.json and reload from config.json"):
            if CONFIG_LOCAL.exists():
                CONFIG_LOCAL.unlink()
            st.session_state.pop("_init_done", None)
            st.rerun()

    tab_groups, tab_clang, tab_views, tab_llm, tab_preview = st.tabs([
        "Module Groups", "Clang", "Views & Export", "LLM", "Config Preview",
    ])

    # ── Module Groups ─────────────────────────────────────────────────────────
    with tab_groups:
        st.caption("Each group generates one DOCX. Paths are relative to the project root.")

        add_col, _ = st.columns([1, 4])
        with add_col:
            st.button("＋ Add Group", on_click=_add_group, use_container_width=True)

        groups = st.session_state.get("groups", [])
        if not groups:
            st.info("No groups defined yet. Click **＋ Add Group** to get started.", icon="ℹ️")

        for group in groups:
            gid = group["gid"]
            with st.container(border=True):
                gc1, gc2 = st.columns([5, 1])
                with gc1:
                    st.text_input("Group name", key=f"g{gid}_name", value=group["name"],
                                  placeholder="Group name  (e.g. core)",
                                  label_visibility="collapsed")
                with gc2:
                    st.button("Remove group", key=f"del_g{gid}",
                              on_click=_remove_group, args=(gid,),
                              use_container_width=True)

                for mod in group["modules"]:
                    mid = mod["mid"]
                    with st.container(border=True):
                        mm1, mm2 = st.columns([4, 1])
                        with mm1:
                            st.text_input("Module name", key=f"m{mid}_name", value=mod["mod"],
                                          placeholder="Module name  (e.g. Core)",
                                          label_visibility="collapsed")
                        with mm2:
                            st.button("Remove", key=f"del_m{mid}",
                                      on_click=_remove_module, args=(gid, mid),
                                      use_container_width=True)

                        for path_entry in mod["paths"]:
                            pid = path_entry["pid"]
                            pc1, pc2, pc3 = st.columns([4, 0.85, 0.45])
                            with pc1:
                                st.text_input("Path", key=f"p{pid}_path", value=path_entry["path"],
                                              placeholder="relative/path/to/module",
                                              label_visibility="collapsed")
                            with pc2:
                                st.button("Browse", key=f"_browse_p{pid}_path",
                                          on_click=_pick_folder, args=(f"p{pid}_path",),
                                          use_container_width=True)
                            with pc3:
                                st.button("✕", key=f"del_p{pid}",
                                          on_click=_remove_path, args=(mid, pid),
                                          disabled=len(mod["paths"]) <= 1,
                                          use_container_width=True)

                        st.button("＋ Add path", key=f"add_p_{mid}",
                                  on_click=_add_path, args=(mid,))

                st.button("＋ Add module", key=f"add_m_{gid}",
                          on_click=_add_module, args=(gid,))

    # ── Clang ─────────────────────────────────────────────────────────────────
    with tab_clang:
        st.caption("Leave paths blank to inherit defaults from config.json.")
        _path_row("LLVM lib path  (libclang.dll / libclang.so)", "llvm_lib",
                  filetypes=[("Library files", "*.dll *.so *.dylib"), ("All files", "*.*")])
        _path_row("Clang include path", "clang_include", is_dir=True)
        st.text_input("Extra clang args  (space-separated)", key="clang_args",
                      placeholder="-DSOME_DEFINE -std=c++17")

    # ── Views & Export ────────────────────────────────────────────────────────
    with tab_views:
        vc1, vc2 = st.columns(2)

        with vc1:
            with st.container(border=True):
                st.markdown("**Unit Diagrams**")
                st.checkbox("Render PNG", key="v_unit_png")

            with st.container(border=True):
                st.markdown("**Flowcharts**")
                st.checkbox("Render PNG", key="v_flow_png")
                _path_row("Generator script", "v_flow_script",
                          filetypes=[("Python files", "*.py"), ("All files", "*.*")])

        with vc2:
            with st.container(border=True):
                st.markdown("**Behaviour Diagrams**")
                st.checkbox("Render PNG", key="v_behav_png")

            with st.container(border=True):
                st.markdown("**Module Static Diagram**")
                st.checkbox("Enabled", key="v_msd_enabled")
                msd_on = st.session_state.get("v_msd_enabled", True)
                st.checkbox("Render PNG", key="v_msd_png", disabled=not msd_on)
                st.number_input("Width (inches)", key="v_msd_width",
                                min_value=1.0, max_value=20.0, step=0.5, disabled=not msd_on)

        st.markdown("---")
        st.markdown("**Export**")
        ec1, ec2 = st.columns([3, 1])
        with ec1:
            st.text_input("DOCX output path template", key="export_docx_path",
                          help="Use {group} as a placeholder for the group name")
        with ec2:
            st.number_input("Font size (pt)", key="export_font_size", min_value=6, max_value=16)

    # ── LLM ───────────────────────────────────────────────────────────────────
    with tab_llm:
        with st.container(border=True):
            st.markdown("**Enable features**")
            lc1, lc2, lc3 = st.columns(3)
            with lc1:
                st.checkbox("Descriptions", key="llm_descriptions")
            with lc2:
                st.checkbox("Behaviour names", key="llm_behav_names")
            with lc3:
                st.checkbox("Call-graph summarize", key="llm_summarize")

        any_llm  = any(st.session_state.get(k)
                       for k in ("llm_descriptions", "llm_behav_names", "llm_summarize"))
        provider = st.selectbox("Provider", options=["ollama", "openai"],
                                key="llm_provider", disabled=not any_llm)
        is_openai = provider == "openai"

        with st.container(border=True):
            st.markdown("**Connection**")
            la1, la2, la3 = st.columns(3)
            with la1:
                st.text_input("Base URL", key="llm_url",
                              placeholder="http://localhost:11434",
                              disabled=not any_llm)
            with la2:
                st.text_input("API key", key="llm_api_key", type="password",
                              placeholder="sk-…",
                              disabled=not any_llm or not is_openai)
            with la3:
                st.text_input("Model", key="llm_model", disabled=not any_llm)

        with st.container(border=True):
            st.markdown("**Limits**")
            lb1, lb2, lb3, lb4 = st.columns(4)
            with lb1:
                st.number_input("Timeout (s)", key="llm_timeout",
                                min_value=10, disabled=not any_llm)
            with lb2:
                st.number_input("Retries", key="llm_retries",
                                min_value=0, max_value=10, disabled=not any_llm)
            with lb3:
                st.number_input("numCtx  (Ollama)", key="llm_ctx",
                                min_value=512, disabled=not any_llm or is_openai)
            with lb4:
                st.text_input("maxContextTokens", key="llm_max_ctx_tokens",
                              placeholder="blank = auto", disabled=not any_llm)

        with st.container(border=True):
            st.markdown("**Enrichment**")
            ea1, ea2, ea3, ea4, ea5 = st.columns(5)
            with ea1:
                st.checkbox("Two-pass",          key="llm_enr_two_pass",     disabled=not any_llm)
            with ea2:
                st.checkbox("Self-review",        key="llm_enr_self_review",  disabled=not any_llm)
            with ea3:
                st.checkbox("Ensemble",           key="llm_enr_ensemble",     disabled=not any_llm)
            with ea4:
                st.checkbox("CFG simplify",       key="llm_enr_cfg_simplify", disabled=not any_llm)
            with ea5:
                st.checkbox("Var enrichment",     key="llm_enr_var_enrich",   disabled=not any_llm)

        with st.container(border=True):
            st.markdown("**Misc**")
            _path_row("Abbreviations file", "llm_abbrev_path", disabled=not any_llm,
                      filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
            _path_row("Few-shot examples dir", "llm_few_shot_dir", is_dir=True, disabled=not any_llm)
            st.number_input("Cache version", key="llm_cache_version", min_value=1, disabled=not any_llm)

        if is_openai and any_llm:
            with st.container(border=True):
                st.markdown("**Custom headers**  (JSON object)")
                st.text_area("customHeaders", key="llm_custom_headers",
                             height=120, label_visibility="collapsed")

    # ── Config Preview ────────────────────────────────────────────────────────
    with tab_preview:
        st.caption("Merged view of config.json + config.local.json (read-only).")
        st.json(cfg)
