"""Flowcharts view.

Invokes `fake_flowchart_generator.py` to produce per-unit JSON files containing
simple function names and a Mermaid flowchart string. When renderPng is true,
renders each flowchart to PNG. The -I include path is derived from metadata.json
basePath when not set in config.
"""

import json
import os
import subprocess
import sys
import tempfile

from .registry import register
from utils import log, mmdc_path, safe_filename


def _resolve_script(project_root: str, script_path: str) -> str:
    if not script_path:
        return os.path.join(project_root, "fake_flowchart_generator.py")
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
    project_root = os.path.dirname(output_dir_abs)

    # Out dir fixed in code: output/flowcharts under the view output dir
    out_dir = os.path.join(output_dir_abs, "flowcharts")
    os.makedirs(out_dir, exist_ok=True)

    functions_path = os.path.join(model_dir_abs, "functions.json")
    metadata_path = os.path.join(model_dir_abs, "metadata.json")

    std = "c++17"  # fixed in code
    clang_args = fc_cfg.get("clangArgs")
    if clang_args is None:
        # Derive -I from metadata.json basePath
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

    cmd = [
        sys.executable,
        script,
        "--interface-json",
        functions_path,
        "--metadata-json",
        metadata_path,
        "--std",
        std,
        "--out-dir",
        out_dir,
    ]
    for a in clang_args:
        if a:
            # Pass as --clang-arg=... so leading '-' isn't parsed as a new option
            cmd.append(f"--clang-arg={str(a)}")

    try:
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

    total = len(items)
    failed = 0
    for i, (unit_name, func_name, flowchart) in enumerate(items, 1):
        print(f"  flowcharts: PNG {i}/{total} {unit_name}/{func_name}...", end="\r", flush=True)
        png_name = f"{unit_name}_{safe_filename(func_name)}.png"
        png_path = os.path.abspath(os.path.join(out_dir, png_name))
        mmd_path = os.path.join(out_dir, f".tmp_{unit_name}_{safe_filename(func_name)}.mmd")
        try:
            with open(mmd_path, "w", encoding="utf-8") as tf:
                tf.write(flowchart)
            run_cmd = run_cmd_base + ["-i", os.path.abspath(mmd_path), "-o", png_path]
            r = subprocess.run(run_cmd, cwd=project_root, capture_output=True, text=True, timeout=180, check=False)
            if r.returncode != 0 and failed == 0:
                log("mmdc failed for %s/%s: %s" % (unit_name, func_name, r.stderr or r.stdout or "exit " + str(r.returncode)), component="flowcharts", err=True)
                failed += 1
        except (subprocess.TimeoutExpired, OSError) as e:
            if failed == 0:
                log("mmdc error for %s/%s: %s" % (unit_name, func_name, e), component="flowcharts", err=True)
                failed += 1
        finally:
            try:
                os.unlink(mmd_path)
            except OSError:
                pass
    if total:
        log("%d PNGs rendered" % total, component="flowcharts")

