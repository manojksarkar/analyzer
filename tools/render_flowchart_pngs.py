"""
render_flowchart_pngs.py — functions.json -> flowchart PNGs, in one step.

Runs flowchart_engine.py on a functions.json (producing per-unit JSON, each with
a Graphviz DOT `flowchart` field), then renders every flowchart to PNG using the
project's own renderer (engine/config/render_dot.mjs via render_dot_cached) and
filename convention — so the PNGs match pipeline/DOCX output exactly.

Requires Node.js (renderer is viz-js -> SVG -> puppeteer PNG). The engine step
also needs libclang configured (LIBCLANG_PATH or engine/config/config.json).

Usage:
    python tools/render_flowchart_pngs.py FUNCTIONS_JSON \
        [--metadata METADATA_JSON] [--out-dir DIR] [--llm] [--scale N]

    FUNCTIONS_JSON   path to functions.json (analyzer output)
    --metadata       metadata.json (default: metadata.json beside FUNCTIONS_JSON)
    --out-dir        where JSON + PNGs go (default: <functions_dir>/flowcharts)
    --llm            use the LLM for node labels (default: --no-llm, deterministic)

PNGs are written into OUT_DIR as <unit>_<safe_func_name>.png.
"""

import argparse
import glob
import json
import os
import subprocess
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINE_DIR = os.path.join(_REPO_ROOT, "engine")
_FLOWCHART_ENGINE = os.path.join(_ENGINE_DIR, "flowchart", "flowchart_engine.py")
_RENDER_MJS = os.path.join(_ENGINE_DIR, "config", "render_dot.mjs")
_IS_WINDOWS = os.name == "nt"

sys.path.insert(0, _ENGINE_DIR)
from utils import render_dot_cached, safe_filename  # noqa: E402


def _debug_render(dot, scale):
    """Run render_dot.mjs directly on `dot` and return (rc, stdout, stderr).
    Used to surface the REAL Node error when render_dot_cached returns False."""
    import tempfile
    fd, dot_path = tempfile.mkstemp(suffix=".dot", dir=_REPO_ROOT)
    png_path = dot_path[:-4] + ".png"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dot or "")
        r = subprocess.run(["node", _RENDER_MJS, dot_path, png_path, str(scale)],
                           capture_output=True, text=True, timeout=60,
                           cwd=_REPO_ROOT, shell=_IS_WINDOWS)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", f"{type(exc).__name__}: {exc}"
    finally:
        for p in (dot_path, png_path):
            try:
                os.remove(p)
            except OSError:
                pass


def _run_engine(functions_json, metadata_json, out_dir, use_llm):
    """Invoke flowchart_engine.py -> writes per-unit JSON into out_dir."""
    cmd = [
        sys.executable, _FLOWCHART_ENGINE,
        "--interface-json", functions_json,
        "--metaData-json", metadata_json,
        "--out-dir", out_dir,
    ]
    if not use_llm:
        cmd.append("--no-llm")
    print("Running flowchart_engine ...", file=sys.stderr)
    # cwd=repo root so config/libclang discovery walks from the analyzer root.
    proc = subprocess.run(cmd, cwd=_REPO_ROOT)
    if proc.returncode != 0:
        raise SystemExit(f"flowchart_engine failed (exit {proc.returncode})")


def _iter_flowcharts(out_dir):
    """Yield (unit_name, func_name, dot) for every generated function."""
    for path in sorted(glob.glob(os.path.join(out_dir, "*.json"))):
        if os.path.basename(path) == "_summary.json":
            continue
        unit_name = os.path.basename(path)[:-5]
        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  skip {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(arr, list):
            continue
        for item in arr:
            name = (item.get("name") or "").strip()
            dot = (item.get("flowchart") or "").strip()
            if name and dot:
                yield unit_name, name, dot


def _matches(unit_name, func_name, pattern):
    """Does "<unit>/<func>" match PATTERN - as a glob, or as a plain substring?

    Both, because both are what people type: `MyUnit/MyFunc` is a substring and
    `*Handler*` is a glob, and guessing wrong just prints "no flowcharts matched".
    """
    if not pattern:
        return True
    key = f"{unit_name}/{func_name}"
    import fnmatch
    return (pattern.lower() in key.lower()
            or fnmatch.fnmatch(key.lower(), pattern.lower())
            or fnmatch.fnmatch(func_name.lower(), pattern.lower()))


def _render(out_dir, scale, timeout, only=None):
    items = [it for it in _iter_flowcharts(out_dir) if _matches(it[0], it[1], only)]
    if only and not items:
        # Name what IS there: the commonest cause is the unit prefix, which is the
        # file stem in out_dir and not always what the function is called.
        have = sorted({f"{u}/{f}" for u, f, _ in _iter_flowcharts(out_dir)})
        print(f"no flowchart matched {only!r} in {out_dir}", file=sys.stderr)
        if have:
            print(f"  {len(have)} available, e.g.:", file=sys.stderr)
            for k in have[:15]:
                print(f"    {k}", file=sys.stderr)
        return 1
    if not items:
        print("No flowcharts found in", out_dir,
              "(engine produced no DOT — check the flowchart_engine log above for parse errors)")
        return 0
    ok = failed = 0
    shown_error = False
    for i, (unit_name, func_name, dot) in enumerate(items, 1):
        png_name = f"{unit_name}_{safe_filename(func_name)}.png"
        png_path = os.path.abspath(os.path.join(out_dir, png_name))
        print(f"[{i}/{len(items)}] {unit_name}/{func_name}", file=sys.stderr)
        if render_dot_cached(_REPO_ROOT, dot, png_path, scale=scale,
                             timeout=timeout) and os.path.isfile(png_path):
            ok += 1
        else:
            failed += 1
            print(f"  render failed: {unit_name}/{func_name}", file=sys.stderr)
            # Surface the REAL Node error the first time (once — same cause repeats).
            if not shown_error:
                shown_error = True
                rc, out, err = _debug_render(dot, scale)
                print(f"  ── node exit {rc} ──", file=sys.stderr)
                for line in (err or out or "(no output)").splitlines():
                    print(f"  | {line}", file=sys.stderr)
                print("  ────────────────────", file=sys.stderr)
                print("  For a full prerequisite check run: python tools/doctor.py",
                      file=sys.stderr)
    print(f"Done. {ok} PNG(s){f', {failed} failed' if failed else ''} -> {out_dir}")
    return 1 if failed else 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("functions_json", nargs="?", default=None,
                   help="Path to functions.json (not needed with --skip-engine)")
    p.add_argument("--metadata", default=None,
                   help="metadata.json (default: sibling of functions.json)")
    p.add_argument("--out-dir", default=None,
                   help="Output dir for JSON + PNGs (default: <functions_dir>/flowcharts)")
    p.add_argument("--llm", action="store_true",
                   help="Use the LLM for node labels (default: deterministic --no-llm)")
    p.add_argument("--scale", type=int, default=2, help="Render scale (default: 2)")
    p.add_argument("--timeout", type=int, default=180,
                   help="Per-render timeout seconds (default: 180)")
    p.add_argument("--skip-engine", action="store_true",
                   help="Render from the per-unit JSON already in --out-dir")
    p.add_argument("--only", default=None,
                   help='Render only "<unit>/<function>" matching this (substring or glob)')
    args = p.parse_args()

    # --skip-engine renders what is already there, so it needs only --out-dir. This is
    # the one-function path: re-rendering a single PNG of a finished run must not cost
    # a rebuild of every flowchart in the project.
    if args.skip_engine:
        if not args.out_dir:
            p.error("--skip-engine needs --out-dir (the flowcharts dir of the run)")
        out_dir = os.path.abspath(args.out_dir)
        if not os.path.isdir(out_dir):
            p.error(f"no such directory: {out_dir}")
        return _render(out_dir, scale=args.scale, timeout=args.timeout, only=args.only)

    if not args.functions_json:
        p.error("FUNCTIONS_JSON is required (or pass --skip-engine --out-dir DIR)")

    functions_json = os.path.abspath(args.functions_json)
    if not os.path.isfile(functions_json):
        p.error(f"functions.json not found: {functions_json}")
    src_dir = os.path.dirname(functions_json)

    metadata_json = os.path.abspath(args.metadata) if args.metadata \
        else os.path.join(src_dir, "metadata.json")
    if not os.path.isfile(metadata_json):
        p.error(f"metadata.json not found: {metadata_json} (pass --metadata)")

    out_dir = os.path.abspath(args.out_dir) if args.out_dir \
        else os.path.join(src_dir, "flowcharts")
    os.makedirs(out_dir, exist_ok=True)

    _run_engine(functions_json, metadata_json, out_dir, use_llm=args.llm)
    return _render(out_dir, scale=args.scale, timeout=args.timeout, only=args.only)


if __name__ == "__main__":
    sys.exit(main())
