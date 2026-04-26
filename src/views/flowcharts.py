"""Flowcharts view.

Invokes flowchart_engine.py (src/flowchart/flowchart_engine.py) to produce
per-unit JSON files containing function names and Mermaid flowchart strings.
When renderPng is true, renders each flowchart to PNG.

The engine reads:
  - model/functions.json       (from parser.py)
  - model/metadata.json        (from parser.py)
  - model/knowledge_base.json  (from model_deriver.py, optional but recommended)

The -I include path is derived from metadata.json basePath when not set in config.
"""

import json
import math
import os
import re
import shlex
import subprocess
import sys
from .registry import register
from utils import KEY_SEP, log, mmdc_path, safe_filename, os_type


# ---------------------------------------------------------------------------
# Flowchart PNG slicer
#
# mmdc renders the full flowchart at its natural aspect ratio. When a function
# has many nodes the PNG becomes much taller than wide, Word embeds it at a
# fixed 4" width (see docx_exporter._add_flowchart_table), and the bottom of
# the image falls off the page. We split the PNG horizontally at whitespace
# bands between rank layers so each part fits on one page.
#
# Constants are keyed to the Word embed geometry:
#   _SLICE_EMBED_WIDTH_IN — Inches(4.0) in _add_flowchart_table
#   _SLICE_USABLE_HEIGHT_IN — conservative per-page height after margins,
#     description paragraph, labels, and table overhead above the image
# ---------------------------------------------------------------------------

_SLICE_EMBED_WIDTH_IN      = 4.0
_SLICE_USABLE_HEIGHT_IN    = 7.5
_SLICE_MAX_ASPECT          = _SLICE_USABLE_HEIGHT_IN / _SLICE_EMBED_WIDTH_IN  # ~1.875
_SLICE_THRESHOLD_FACTOR    = 1.15   # tolerate up to this × max before slicing
_SLICE_WIDE_LIMIT          = 1.50   # W/H over this → width is the bottleneck, skip
_SLICE_WHITE_CUTOFF        = 250    # channel value > this counts as white
_SLICE_WINDOW_PRIMARY      = 0.15   # ±15% of H for primary whitespace search
_SLICE_WINDOW_FALLBACK     = 0.20   # ±20% fallback
_SLICE_MIN_TAIL_FRACTION   = 0.20   # merge tail slice if smaller than 20% of a target slice


def _cleanup_stale_slice_parts(png_path: str) -> None:
    """Remove any {stem}__part_*_of_*.png siblings so state is consistent before (re-)slicing."""
    out_dir = os.path.dirname(png_path)
    stem = os.path.splitext(os.path.basename(png_path))[0]
    pattern = re.compile(
        r"^" + re.escape(stem) + r"__part_\d+_of_\d+\.png$",
        re.IGNORECASE,
    )
    try:
        for name in os.listdir(out_dir):
            if pattern.match(name):
                try:
                    os.unlink(os.path.join(out_dir, name))
                except OSError:
                    pass
    except OSError:
        pass


def _pick_cut_ys(white_ys, H: int, N: int):
    """Given an array of white-row Y indices, pick N-1 cut points targeting
    evenly spaced boundaries. Falls back to the exact target Y if no white row
    is within ±20% of H. Returns a sorted list of ints."""
    import numpy as np
    primary = int(H * _SLICE_WINDOW_PRIMARY)
    fallback = int(H * _SLICE_WINDOW_FALLBACK)
    slice_h = H / N
    cuts = []
    for k in range(1, N):
        target = int(k * slice_h)
        chosen = target
        if len(white_ys):
            mask = (white_ys >= target - primary) & (white_ys <= target + primary)
            cands = white_ys[mask]
            if not len(cands):
                mask = (white_ys >= target - fallback) & (white_ys <= target + fallback)
                cands = white_ys[mask]
            if len(cands):
                idx = int(np.argmin(np.abs(cands.astype(np.int64) - target)))
                chosen = int(cands[idx])
        cuts.append(chosen)
    return sorted(set(cuts))


def _maybe_slice_tall_png(png_path: str) -> int:
    """If `png_path`'s aspect would overflow one Word page at 4" wide, split it
    horizontally at whitespace bands and write {stem}__part_K_of_N.png siblings.

    The original PNG is removed when slicing happens so the state is either
    "single original" OR "N parts" — never both. Slicing is best-effort:
    any error keeps the original intact and returns 1.

    Returns the number of parts produced (1 means no slice happened).
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        log("slice: PIL/numpy unavailable, skipping slice (%s)" % exc, component="flowcharts")
        return 1

    try:
        img = Image.open(png_path)
        img.load()
    except Exception as exc:
        log("slice: cannot open %s: %s" % (png_path, exc), component="flowcharts")
        return 1
    try:
        rgb = img.convert("RGB")
    except Exception as exc:
        log("slice: convert RGB failed for %s: %s" % (png_path, exc), component="flowcharts")
        try:
            img.close()
        except Exception:
            pass
        return 1

    W, H = rgb.size
    try:
        img.close()
    except Exception:
        pass

    if W <= 0 or H <= 0:
        return 1

    # Always scrub stale parts first so a previous longer/shorter run doesn't
    # leave mismatched parts alongside the fresh original.
    _cleanup_stale_slice_parts(png_path)

    name = os.path.basename(png_path)
    threshold = _SLICE_MAX_ASPECT * _SLICE_THRESHOLD_FACTOR

    # Width-bottleneck: height-slicing can't help a wide-and-short image.
    if W / H > _SLICE_WIDE_LIMIT:
        log("slice: %s W=%d H=%d aspect=%.2f W/H=%.2f -> skipped (wide layout, threshold W/H>%.2f)"
            % (name, W, H, H / W, W / H, _SLICE_WIDE_LIMIT),
            component="flowcharts")
        return 1

    aspect = H / W
    if aspect <= threshold:
        log("slice: %s W=%d H=%d aspect=%.2f -> not sliced (fits, threshold=%.2f)"
            % (name, W, H, aspect, threshold),
            component="flowcharts")
        return 1  # fits on one page, possibly after minor Word scaling

    N = max(2, int(math.ceil(aspect / _SLICE_MAX_ASPECT)))

    # Find rows that are entirely near-white. min over width AND channels → (H,)
    arr = np.asarray(rgb, dtype=np.uint8)
    row_min = arr.min(axis=(1, 2))
    white_ys = np.nonzero(row_min > _SLICE_WHITE_CUTOFF)[0]

    cut_ys = _pick_cut_ys(white_ys, H, N)
    boundaries = [0] + cut_ys + [H]

    # Merge a too-small tail slice into its predecessor.
    target_slice_h = H / N
    if len(boundaries) >= 3:
        tail_h = boundaries[-1] - boundaries[-2]
        if tail_h < _SLICE_MIN_TAIL_FRACTION * target_slice_h:
            boundaries = boundaries[:-2] + [boundaries[-1]]

    n_parts = len(boundaries) - 1
    if n_parts < 2:
        return 1

    stem, ext = os.path.splitext(png_path)
    written = []
    try:
        for i in range(n_parts):
            y0, y1 = boundaries[i], boundaries[i + 1]
            crop = rgb.crop((0, y0, W, y1))
            out_path = f"{stem}__part_{i + 1}_of_{n_parts}{ext}"
            crop.save(out_path)
            written.append(out_path)
    except Exception as exc:
        log("slice: write failed for %s: %s — keeping original" % (png_path, exc),
            component="flowcharts")
        for p in written:
            try:
                os.unlink(p)
            except OSError:
                pass
        return 1

    try:
        rgb.close()
    except Exception:
        pass
    try:
        os.unlink(png_path)
    except OSError:
        pass

    log("slice: %s W=%d H=%d aspect=%.2f -> sliced into %d parts (threshold=%.2f)"
        % (name, W, H, aspect, n_parts, threshold),
        component="flowcharts")
    return n_parts


def _resolve_script(project_root: str, script_path: str) -> str:
    if not script_path:
        return os.path.join(project_root, "fake_flowchart_generator.py")
    # Recover from unescaped backslashes in config.json: JSON parses "src\flowchart"
    # as src + FF (0x0C) + lowchart, because \f/\b/\n/\r/\t are JSON escape sequences.
    # Reverse that so Windows paths written with single backslashes still work.
    if any(c in script_path for c in "\b\f\n\r\t"):
        for ctrl, letter in (("\b", "b"), ("\f", "f"), ("\n", "n"), ("\r", "r"), ("\t", "t")):
            script_path = script_path.replace(ctrl, "/" + letter)
        log("scriptPath had unescaped backslashes in config.json; recovered to: %s" % script_path,
            component="flowcharts")
    return script_path if os.path.isabs(script_path) else os.path.join(project_root, script_path)


@register("flowcharts")
def run(model, output_dir, model_dir, config):
    views_cfg = config.get("views", {})
    val = views_cfg.get("flowcharts")
    if val is None or val is False:
        # Not enabled
        return
    fc_cfg = val if isinstance(val, dict) else {}

    # Be robust to callers passing relative output_dir/model_dir.
    output_dir_abs = os.path.abspath(output_dir)
    model_dir_abs = os.path.abspath(model_dir)
    project_root = os.path.dirname(model_dir_abs)

    # Out dir fixed in code: output/flowcharts under the view output dir
    out_dir = os.path.join(output_dir_abs, "flowcharts")
    os.makedirs(out_dir, exist_ok=True)

    functions_path = os.path.join(model_dir_abs, "functions.json")
    metadata_path = os.path.join(model_dir_abs, "metadata.json")
    allowed_modules = {m.lower() for m in ((config or {}).get("_analyzerAllowedModules") or [])}

    std = "c++14"  # fixed in code
    clang_cfg = config.get("clang") or {}
    clang_args = clang_cfg.get("clangArgs")
    if not clang_args:
        # Fallback: derive -I from metadata.json basePath
        clang_args = []
        if os.path.isfile(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                base_path = meta.get("basePath", "").strip()
                if base_path:
                    clang_args = [f"-I{base_path}"]
            except (json.JSONDecodeError, OSError):
                pass
    if not isinstance(clang_args, list):
        clang_args = [clang_args] if clang_args else []

    script = _resolve_script(project_root, fc_cfg.get("scriptPath"))
    if not os.path.isfile(script):
        log("generator not found: %s" % script, component="flowcharts", err=True)
        return

    # If we are exporting a selected group, pass only that group's functions to the generator.
    functions_arg_path = functions_path
    group_name = (config or {}).get("_analyzerSelectedGroup") or ""
    if allowed_modules and group_name and os.path.isfile(functions_path):
        try:
            with open(functions_path, "r", encoding="utf-8") as f:
                all_funcs = json.load(f)
            if isinstance(all_funcs, dict):
                filtered = {
                    fid: info
                    for fid, info in all_funcs.items()
                    if isinstance(fid, str)
                    and KEY_SEP in fid
                    and fid.split(KEY_SEP, 1)[0].lower() in allowed_modules
                }
                group_functions_path = os.path.join(model_dir_abs, f"functions_{safe_filename(group_name)}.json")
                with open(group_functions_path, "w", encoding="utf-8") as tf:
                    json.dump(filtered, tf, indent=2)
                functions_arg_path = group_functions_path
        except (OSError, json.JSONDecodeError):
            pass

    # knowledge_base.json (generated by model_deriver.py) — pass if it exists
    kb_path = os.path.join(model_dir_abs, "knowledge_base.json")

    # LLM config for flowchart engine
    llm_cfg = config.get("llm") or {}
    llm_base_url = (llm_cfg.get("baseUrl") or "http://localhost:11434").rstrip("/")
    llm_url = f"{llm_base_url}/api/generate"
    llm_model = llm_cfg.get("defaultModel") or "qwen2.5-coder:14b"
    llm_num_ctx = str(int(llm_cfg.get("numCtx", 8192)))

    cmd = [
        sys.executable,
        script,
        "--interface-json",
        functions_arg_path,
        "--metaData-json",
        metadata_path,
        "--std",
        std,
        "--out-dir",
        out_dir,
        "--llm-url",
        llm_url,
        "--llm-model",
        llm_model,
        "--llm-num-ctx",
        llm_num_ctx,
    ]
    if os.path.isfile(kb_path):
        cmd.extend(["--knowledge-json", kb_path])
    # Many projects have hundreds of -I/-D clang args. Passing them all on the
    # command line blows the Windows cmd.exe 8192-char limit (WinError 206).
    # Write them to a response file and pass `@file` — flowchart_engine.py
    # enables argparse's fromfile_prefix_chars='@' to read args from it.
    non_empty_clang_args = [str(a) for a in clang_args if a]
    if non_empty_clang_args:
        args_file = os.path.join(model_dir_abs, ".flowcharts_clang_args.txt")
        with open(args_file, "w", encoding="utf-8") as f:
            for a in non_empty_clang_args:
                f.write(f"--clang-arg={a}\n")
        cmd.append(f"@{args_file}")

    log("flowcharts cmd: " + " ".join(shlex.quote(a) for a in cmd), component="flowcharts")
    try:
        if os_type == "Windows":
            r = subprocess.run(cmd, cwd=project_root, check=False, shell=True)
        else:
            r = subprocess.run(cmd, cwd=project_root, check=False)
    except subprocess.TimeoutExpired:
        log("generator timed out", component="flowcharts", err=True)
        return
    except OSError as e:
        log("generator failed: %s" % e, component="flowcharts", err=True)
        return

    if r.returncode != 0:
        log("generator exited with code %s" % r.returncode, component="flowcharts", err=True)
        return

    # Render flowcharts to PNG when renderPng is true
    if not fc_cfg.get("renderPng", False):
        return

    mmdc = mmdc_path(project_root)
    if not os.path.isfile(mmdc):
        try:
            if os_type == "Windows":
                subprocess.run([mmdc, "--help"], capture_output=True, timeout=5, cwd=project_root, shell=True)
            else:
                subprocess.run([mmdc, "--help"], capture_output=True, timeout=5, cwd=project_root)
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            log("mmdc not found. Run: npm install @mermaid-js/mermaid-cli", component="flowcharts", err=True)
            return

    puppeteer = os.path.join(project_root, "config", "puppeteer-config.json")
    run_cmd_base = [mmdc]
    if os.path.isfile(puppeteer):
        run_cmd_base.extend(["-p", puppeteer])

    items = []
    for fname in sorted(os.listdir(out_dir)):
        if not fname.endswith(".json"):
            continue
        unit_name = fname[:-5]
        path = os.path.join(out_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)
            if not isinstance(arr, list):
                continue
            for item in arr:
                func_name = (item.get("name") or "").strip()
                flowchart = (item.get("flowchart") or "").strip()
                if func_name and flowchart:
                    items.append((unit_name, func_name, flowchart))
        except (json.JSONDecodeError, OSError):
            pass

    from core.progress import ProgressReporter
    from core.logging_setup import get_logger
    total = len(items)
    failed = 0
    progress = ProgressReporter("flowcharts:PNG", total=total, logger=get_logger("flowcharts"))
    progress.start()
    for i, (unit_name, func_name, flowchart) in enumerate(items, 1):
        progress.step(label=f"{unit_name}/{func_name}")
        png_name = f"{unit_name}_{safe_filename(func_name)}.png"
        png_path = os.path.abspath(os.path.join(out_dir, png_name))
        mmd_path = os.path.join(out_dir, f".tmp_{unit_name}_{safe_filename(func_name)}.mmd")
        try:
            with open(mmd_path, "w", encoding="utf-8") as tf:
                tf.write(flowchart)
            run_cmd = run_cmd_base + ["-i", os.path.abspath(mmd_path), "-o", png_path]
            if os_type == "Windows":
                r = subprocess.run(run_cmd, cwd=project_root, capture_output=True, text=True, timeout=180, check=False, shell=True)
            else:
                r = subprocess.run(run_cmd, cwd=project_root, capture_output=True, text=True, timeout=180, check=False)
            if r.returncode != 0:
                failed += 1
                log("mmdc failed for %s/%s: %s" % (unit_name, func_name, (r.stderr or r.stdout or "exit " + str(r.returncode))[:200]), component="flowcharts", err=True)
            elif os.path.isfile(png_path):
                # Split oversize flowcharts into per-page slices so Word doesn't clip them.
                _maybe_slice_tall_png(png_path)
        except (subprocess.TimeoutExpired, OSError) as e:
            failed += 1
            log("mmdc error for %s/%s: %s" % (unit_name, func_name, e), component="flowcharts", err=True)
        except Exception as e:
            failed += 1
            log("flowchart error for %s/%s: %s" % (unit_name, func_name, e), component="flowcharts", err=True)
        finally:
            try:
                if os.path.isfile(mmd_path):
                    os.unlink(mmd_path)
            except OSError:
                pass
    progress.done(summary=("%d PNGs rendered%s" % (total, (" (%d failed)" % failed) if failed else "")) if total else None)

