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

sys.path.insert(0, _ENGINE_DIR)
from utils import render_dot_cached, safe_filename  # noqa: E402


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


def _render(out_dir, scale, timeout):
    items = list(_iter_flowcharts(out_dir))
    if not items:
        print("No flowcharts found in", out_dir)
        return 0
    ok = failed = 0
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
    print(f"Done. {ok} PNG(s){f', {failed} failed' if failed else ''} -> {out_dir}")
    return 1 if failed else 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("functions_json", help="Path to functions.json")
    p.add_argument("--metadata", default=None,
                   help="metadata.json (default: sibling of functions.json)")
    p.add_argument("--out-dir", default=None,
                   help="Output dir for JSON + PNGs (default: <functions_dir>/flowcharts)")
    p.add_argument("--llm", action="store_true",
                   help="Use the LLM for node labels (default: deterministic --no-llm)")
    p.add_argument("--scale", type=int, default=2, help="Render scale (default: 2)")
    p.add_argument("--timeout", type=int, default=180,
                   help="Per-render timeout seconds (default: 180)")
    args = p.parse_args()

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
    return _render(out_dir, scale=args.scale, timeout=args.timeout)


if __name__ == "__main__":
    sys.exit(main())
