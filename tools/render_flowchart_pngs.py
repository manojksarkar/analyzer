"""
render_flowchart_pngs.py — flowchart pictures (SVG + PNG) without a pipeline run.

Three ways in:

  * FUNCTIONS_JSON — runs flowchart_engine.py on a functions.json (producing per-unit JSON,
    each with a Graphviz DOT `flowchart` field), then draws every flowchart.
  * --skip-engine --out-dir DIR — draws what one finished run's flowcharts dir already holds.
  * --project ID / --all — draws what EVERY version of a web-app project already holds
    (workspaces/<ID>/versions/*/output/**/flowcharts). The backfill for runs made before
    runs drew SVGs: nothing is parsed, generated or exported, only the pictures are drawn.

Pictures, with the project's own renderers and file names, so they match a pipeline run:
  * SVG, <unit>_<safe_func_name>.svg — the web reader's (views.flowcharts.write_flowchart_svgs;
    one Node process for all of them, about a millisecond per chart). Always drawn; a chart
    whose SVG is already current is left alone.
  * PNG, <unit>_<safe_func_name>.png — the Word document's (render_dot.mjs via
    render_dot_cached; a headless browser per chart, ~12 s each, cached by content). Drawn by
    the first two modes, and by --project/--all only with --png.

Requires Node.js (viz-js; the PNGs also puppeteer). The engine step also needs libclang
configured (LIBCLANG_PATH or engine/config/config.json).

Usage:
    python tools/render_flowchart_pngs.py FUNCTIONS_JSON \
        [--metadata METADATA_JSON] [--out-dir DIR] [--llm] [--scale N]
    python tools/render_flowchart_pngs.py --skip-engine --out-dir DIR [--only PATTERN]
    python tools/render_flowchart_pngs.py --project ID [--project ID2] [--png]
    python tools/render_flowchart_pngs.py --all [--png]

    FUNCTIONS_JSON   path to functions.json (analyzer output)
    --metadata       metadata.json (default: metadata.json beside FUNCTIONS_JSON)
    --out-dir        where JSON + pictures go (default: <functions_dir>/flowcharts)
    --llm            use the LLM for node labels (default: --no-llm, deterministic)

A document shows the new pictures on its next load; the API reads them from disk.
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
from views.flowcharts import write_flowchart_svgs  # noqa: E402


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


def _svgs(out_dir):
    """Draw out_dir's SVGs and say what happened. Returns the counts."""
    c = write_flowchart_svgs(_REPO_ROOT, out_dir)
    extra = "".join(f", {c[k]} {label}" for k, label in
                    (("too_large", "too large"), ("failed", "failed"), ("removed", "removed"))
                    if c[k])
    print(f"SVG: {c['drawn']} drawn, {c['current']} already current{extra} -> {out_dir}")
    return c


def _project_flowchart_dirs(project_dir):
    """Every flowcharts dir in a project's version outputs: versions/<v>/output (and the
    older commit-addressed <commit>/output, which api doc_render still reads)."""
    roots = sorted(glob.glob(os.path.join(project_dir, "versions", "*", "output")))
    roots += sorted(p for p in glob.glob(os.path.join(project_dir, "*", "output"))
                    if os.path.basename(os.path.dirname(p)) != "versions")
    found = []
    for root in roots:
        for here, subdirs, _files in os.walk(root):
            if os.path.basename(here) == "flowcharts":
                found.append(here)
                subdirs[:] = []
    return found


def _backfill(project_ids, every, png, scale, timeout, only):
    """--project / --all: draw the pictures every version of the projects already has."""
    workspaces = os.path.join(_REPO_ROOT, "workspaces")
    if every:
        project_ids = sorted(
            d for d in os.listdir(workspaces)
            if os.path.isdir(os.path.join(workspaces, d, "versions"))) \
            if os.path.isdir(workspaces) else []
    if not project_ids:
        print(f"No projects to draw (nothing under {workspaces}).", file=sys.stderr)
        return 1

    dirs = drawn = failed = too_large = 0
    png_failed = False
    for pid in project_ids:
        project_dir = os.path.join(workspaces, pid)
        if not os.path.isdir(project_dir):
            print(f"{pid}: no such project (no {project_dir})", file=sys.stderr)
            png_failed = True
            continue
        fc_dirs = _project_flowchart_dirs(project_dir)
        if not fc_dirs:
            print(f"{pid}: no flowcharts in any version")
            continue
        for fc_dir in fc_dirs:
            print(f"{pid}: {os.path.relpath(fc_dir, project_dir)}")
            c = _svgs(fc_dir)
            dirs += 1
            drawn += c["drawn"]
            failed += c["failed"]
            too_large += c["too_large"]
            if png and _render(fc_dir, scale=scale, timeout=timeout, only=only) != 0:
                png_failed = True
    print(f"Done. {len(project_ids)} project(s), {dirs} flowchart dir(s): {drawn} SVG(s) drawn"
          + (f", {too_large} too large to draw" if too_large else "")
          + (f", {failed} failed" if failed else "") + ".")
    return 1 if (failed or png_failed) else 0


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
    p.add_argument("--project", action="append", default=[], metavar="ID",
                   help="Draw what every version of this web-app project already has "
                        "(workspaces/ID): SVGs, and PNGs with --png. Repeatable.")
    p.add_argument("--all", action="store_true",
                   help="Like --project, for every project under workspaces/")
    p.add_argument("--png", action="store_true",
                   help="With --project/--all: also draw the PNGs (Word's; ~12 s per new chart)")
    args = p.parse_args()

    if args.project or args.all:
        return _backfill(args.project, args.all, png=args.png, scale=args.scale,
                         timeout=args.timeout, only=args.only)

    # --skip-engine renders what is already there, so it needs only --out-dir. This is
    # the one-function path: re-rendering a single PNG of a finished run must not cost
    # a rebuild of every flowchart in the project.
    if args.skip_engine:
        if not args.out_dir:
            p.error("--skip-engine needs --out-dir (the flowcharts dir of the run)")
        out_dir = os.path.abspath(args.out_dir)
        if not os.path.isdir(out_dir):
            p.error(f"no such directory: {out_dir}")
        svg = _svgs(out_dir)
        rc = _render(out_dir, scale=args.scale, timeout=args.timeout, only=args.only)
        return 1 if (rc or svg["failed"]) else 0

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
    svg = _svgs(out_dir)
    rc = _render(out_dir, scale=args.scale, timeout=args.timeout, only=args.only)
    return 1 if (rc or svg["failed"]) else 0


if __name__ == "__main__":
    sys.exit(main())
