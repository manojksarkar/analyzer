#!/usr/bin/env python3
"""Prerequisite doctor for the C++ Codebase Analyzer.

Checks every external dependency the pipeline needs and, for each one, probes the
SAME places the pipeline resolves it, in the SAME order — **local (in-project)
first, then global (machine)** — reporting which location satisfied it (or that it
is missing in both). Exits non-zero if any REQUIRED check fails, so run.py / CI
can fail fast with an actionable message instead of a cryptic subprocess error.

    python tools/doctor.py            # human report, exit 1 on any REQUIRED fail
    python tools/doctor.py --quiet    # only print problems

What it verifies:
  - Python interpreter + required packages (libclang, requests, python-docx; tiktoken optional)
  - Node.js runtime
  - npm packages used by rendering: @viz-js/viz + puppeteer (flowcharts), @mermaid-js/mermaid-cli (mmdc)
  - Chromium that puppeteer will launch to rasterize SVG->PNG
  - libclang DLL (CFG parsing): LIBCLANG_PATH -> engine/config/config.json -> pip-bundled fallback
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IS_WIN = os.name == "nt"

OK, WARN, FAIL = "OK", "WARN", "FAIL"


class Check:
    # category drives run.py's view-gated preflight:
    #   core     — always needed (parse/derive/export)
    #   node     — the Node runtime (any diagram rendering)
    #   render   — the Chromium puppeteer launches (flowcharts + mermaid diagrams)
    #   flowchart— Graphviz-only deps (flowchart PNGs)
    #   mermaid  — mmdc (behaviour/unit diagrams)
    def __init__(self, name, status, detail="", fix="", required=True, category="core"):
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix
        self.required = required
        self.category = category


def _run(cmd, cwd=ROOT, timeout=20, env=None):
    """Run a command, return (rc, stdout, stderr); ('', '') on failure."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, shell=IS_WIN, env=env)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except (OSError, subprocess.SubprocessError):
        return 127, "", ""


def _pkg_version(pkg_json):
    try:
        with open(pkg_json, encoding="utf-8") as f:
            return json.load(f).get("version", "?")
    except (OSError, ValueError):
        return "?"


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

def check_python():
    v = sys.version_info
    ok = v >= (3, 9)
    return Check("python", OK if ok else FAIL,
                 f"{v.major}.{v.minor}.{v.micro} ({sys.executable})",
                 "" if ok else "Python >= 3.9 required")


def check_python_pkgs():
    checks = []
    # import_name, pip_name, required
    pkgs = [
        ("clang", "libclang", True),
        ("requests", "requests", True),
        ("docx", "python-docx", True),
        ("tiktoken", "tiktoken", False),
    ]
    for imp, pip, required in pkgs:
        found = importlib.util.find_spec(imp) is not None
        if found:
            checks.append(Check(f"py:{pip}", OK, f"import '{imp}' resolvable"))
        else:
            checks.append(Check(
                f"py:{pip}", FAIL if required else WARN,
                f"import '{imp}' not found",
                f"pip install {pip}" + ("" if required else "  (optional)"),
                required=required))
    return checks


# ---------------------------------------------------------------------------
# Node + npm packages (local -> global)
# ---------------------------------------------------------------------------

_NPM_GLOBAL_ROOT = None


def npm_global_root():
    global _NPM_GLOBAL_ROOT
    if _NPM_GLOBAL_ROOT is None:
        rc, out, _ = _run(["npm", "root", "-g"])
        root = out if rc == 0 and out else ""
        if not root and IS_WIN:  # fallback to the usual Windows prefix
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                root = os.path.join(appdata, "npm", "node_modules")
        _NPM_GLOBAL_ROOT = root
    return _NPM_GLOBAL_ROOT


def check_node():
    if shutil.which("node") is None:
        return Check("node", FAIL, "not on PATH",
                     "Install Node.js 18+ (https://nodejs.org)", category="node")
    rc, out, _ = _run(["node", "--version"])
    if rc != 0:
        return Check("node", FAIL, "found on PATH but failed to run", category="node")
    return Check("node", OK, f"{out} (global: PATH)", category="node")


def check_node_pkg(pkg, *, required=True, purpose="", category="core"):
    """Mirror Node resolution: local ./node_modules first, then npm global root."""
    local = os.path.join(ROOT, "node_modules", *pkg.split("/"), "package.json")
    if os.path.isfile(local):
        return Check(f"npm:{pkg}", OK,
                     f"v{_pkg_version(local)} (local: ./node_modules){purpose}",
                     category=category)
    groot = npm_global_root()
    if groot:
        gpkg = os.path.join(groot, *pkg.split("/"), "package.json")
        if os.path.isfile(gpkg):
            return Check(f"npm:{pkg}", OK,
                         f"v{_pkg_version(gpkg)} (global: {groot}){purpose}",
                         category=category)
    return Check(f"npm:{pkg}", FAIL if required else WARN,
                 "not found (checked local ./node_modules and npm global)",
                 f"npm install {pkg}", required=required, category=category)


def check_mmdc():
    """Mirror utils.mmdc_path: local node_modules/.bin -> %APPDATA%/npm -> PATH."""
    ext = ".cmd" if IS_WIN else ""
    local = os.path.join(ROOT, "node_modules", ".bin", "mmdc" + ext)
    if os.path.isfile(local):
        return Check("mmdc", OK, "local: ./node_modules/.bin", category="mermaid")
    if IS_WIN:
        appdata = os.environ.get("APPDATA", "")
        if appdata and os.path.isfile(os.path.join(appdata, "npm", "mmdc.cmd")):
            return Check("mmdc", OK, "global: %APPDATA%\\npm", category="mermaid")
    if shutil.which("mmdc"):
        return Check("mmdc", OK, "global: PATH", category="mermaid")
    return Check("mmdc", FAIL,
                 "not found (checked local ./node_modules/.bin and npm global)",
                 "npm install @mermaid-js/mermaid-cli", category="mermaid")


def _configured_browser_path():
    """The explicit browser render_dot.mjs would use, mirroring its resolution:
    env PUPPETEER_EXECUTABLE_PATH / CHROME_PATH, then puppeteer-config.json
    'executablePath'. Returns (path, source) or (None, None) when nothing is set."""
    env = os.environ.get("PUPPETEER_EXECUTABLE_PATH") or os.environ.get("CHROME_PATH")
    if env:
        return env, "env"
    cfg_path = os.path.join(ROOT, "engine", "config", "puppeteer-config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            exe = json.load(f).get("executablePath")
        if exe:
            return exe, "puppeteer-config.json"
    except (OSError, ValueError):
        pass
    return None, None


def check_chromium():
    """Resolve the browser the renderer will launch to rasterize SVG->PNG, the
    SAME way render_dot.mjs does: an explicit executablePath (env or
    puppeteer-config.json) wins, else puppeteer's bundled Chromium."""
    # 1. Explicit path (offline servers point this at a standalone Chrome).
    exe, source = _configured_browser_path()
    if exe:
        if os.path.isfile(exe):
            return Check("chromium", OK, f"{exe} ({source}: executablePath)",
                         category="render")
        # render_dot.mjs falls back to bundled when the path is missing, so this
        # is only fatal if the bundled browser is also absent (checked below).
        cfg_missing = f"configured executablePath missing: {exe} ({source})"
    else:
        cfg_missing = ""

    # 2. Bundled Chromium via puppeteer. Strip the explicit-path env vars so
    # puppeteer.executablePath() reports its TRUE bundled browser, not the (bad)
    # configured path — render_dot.mjs falls back to bundled in exactly this case.
    if shutil.which("node") is None:
        return Check("chromium", FAIL, "node unavailable - cannot resolve puppeteer",
                     "Install Node.js, then npm install puppeteer", category="render")
    bundled_env = {k: v for k, v in os.environ.items()
                   if k not in ("PUPPETEER_EXECUTABLE_PATH", "CHROME_PATH")}
    rc, out, err = _run(
        ["node", "-e",
         "try{process.stdout.write(require('puppeteer').executablePath())}"
         "catch(e){process.stdout.write('ERR:'+e.message)}"],
        env=bundled_env)
    if rc != 0 or not out or out.startswith("ERR:"):
        detail = "puppeteer not resolvable" + (f" ({out[4:]})" if out.startswith("ERR:") else "")
        if cfg_missing:
            detail = cfg_missing + "; and " + detail
        return Check("chromium", FAIL, detail,
                     "Fix executablePath in engine/config/puppeteer-config.json, "
                     "or npm install puppeteer (downloads Chromium)", category="render")
    if os.path.isfile(out):
        detail = out + " (bundled)"
        if cfg_missing:
            # Works, but the configured path is broken — warn so it's fixed before
            # deploying to a server that lacks the bundled browser.
            return Check("chromium", WARN, f"{cfg_missing}; using bundled: {out}",
                         "Fix executablePath in engine/config/puppeteer-config.json",
                         required=False, category="render")
        return Check("chromium", OK, detail, category="render")
    return Check("chromium", FAIL, f"puppeteer points at missing browser: {out}",
                 "npx puppeteer browsers install chrome", category="render")


# ---------------------------------------------------------------------------
# libclang (env -> config.json -> pip-bundled) — mirrors _configure_libclang
# ---------------------------------------------------------------------------

def check_libclang():
    env = os.environ.get("LIBCLANG_PATH", "")
    if env and os.path.isfile(env):
        return Check("libclang", OK, f"{env} (env: LIBCLANG_PATH)")

    cfg_path = os.path.join(ROOT, "engine", "config", "config.json")
    cfg_lib = ""
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, encoding="utf-8") as f:
                cfg = json.load(f)
            cfg_lib = (cfg.get("clang") or {}).get("llvmLibPath") or cfg.get("llvmLibPath") or ""
        except (OSError, ValueError):
            cfg_lib = ""
    if cfg_lib and os.path.isfile(cfg_lib):
        return Check("libclang", OK, f"{cfg_lib} (config: engine/config/config.json)")

    # pip `libclang` bundles a native library that clang.cindex can discover.
    if importlib.util.find_spec("clang.cindex") is not None:
        detail = "pip 'libclang' bundled lib (default discovery)"
        if cfg_lib:
            detail += f"; NOTE config path missing: {cfg_lib}"
        return Check("libclang", WARN, detail,
                     "Set a valid engine/config/config.json clang.llvmLibPath or "
                     "$LIBCLANG_PATH to pin the DLL explicitly", required=False)

    return Check("libclang", FAIL,
                 "not resolvable via $LIBCLANG_PATH, config.json, or pip 'libclang'",
                 "pip install libclang  (or install LLVM and set config.json clang.llvmLibPath)")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def collect_checks():
    """Run every check once and return the list (used by the report and preflight)."""
    checks = [check_python()]
    checks += check_python_pkgs()
    checks.append(check_node())
    checks.append(check_node_pkg("@viz-js/viz", purpose="  [flowcharts]",
                                 category="flowchart"))
    checks.append(check_node_pkg("puppeteer", purpose="  [flowcharts+behaviour]",
                                 category="render"))
    checks.append(check_chromium())
    checks.append(check_mmdc())
    checks.append(check_libclang())
    return checks


def preflight(*, need_flowchart, need_mermaid):
    """Return the REQUIRED checks that FAIL and matter for this run's enabled views.

    Called by run.py before a long run. `core` deps always block; render/node/mermaid
    deps block only when a view that uses them is enabled, so a parse-only run isn't
    stopped by a missing browser."""
    render = need_flowchart or need_mermaid
    blocking = []
    for c in collect_checks():
        if c.status != FAIL:
            continue
        cat = c.category
        needed = (
            cat == "core"
            or (cat in ("node", "render") and render)
            or (cat == "flowchart" and need_flowchart)
            or (cat == "mermaid" and need_mermaid)
        )
        if needed:
            blocking.append(c)
    return blocking


def main():
    ap = argparse.ArgumentParser(description="Analyzer prerequisite doctor")
    ap.add_argument("--quiet", action="store_true", help="only print WARN/FAIL rows")
    args = ap.parse_args()

    checks = collect_checks()

    sym = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}
    width = max(len(c.name) for c in checks)

    print(f"\nAnalyzer prerequisite check - {ROOT}\n" + "-" * 60)
    n_fail = n_warn = 0
    for c in checks:
        if c.status == FAIL:
            n_fail += 1
        elif c.status == WARN:
            n_warn += 1
        if args.quiet and c.status == OK:
            continue
        print(f"[{sym[c.status]}] {c.name.ljust(width)}  {c.detail}")
        if c.fix and c.status != OK:
            print(f"        -> {c.fix}")
    print("-" * 60)
    print(f"{len(checks)} checks | {n_fail} fail | {n_warn} warn")

    if n_fail:
        print("\nMissing REQUIRED prerequisites — the pipeline will not run cleanly.")
        return 1
    if n_warn:
        print("\nAll required prerequisites present (some optional items missing).")
    else:
        print("\nAll prerequisites present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
