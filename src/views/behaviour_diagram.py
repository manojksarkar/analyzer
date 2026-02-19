"""Behaviour diagram view.

Creates behaviour diagrams per function by delegating to a generator object
(`FakeBehaviourGenerator` in this test setup). The generator:

- is constructed once with paths to `functions.json`, `modules.json`, `units.json`
- is then called per-function with the function key and an output directory
- may create 0..N Mermaid `.mmd` files and returns their paths

For compatibility with the DOCX exporter we still render **one PNG per
function**, using the first returned `.mmd` file (if any) and naming the PNG
`safe_filename(fid).png` as before.
"""

import json
import os
import subprocess
import sys

# fake_behaviour_diagram_generator lives in project root
_proj = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _proj not in sys.path:
    sys.path.insert(0, _proj)

from .registry import register
from utils import mmdc_path, safe_filename
from fake_behaviour_diagram_generator import FakeBehaviourGenerator


@register("behaviourDiagram")
def run(model, output_dir, model_dir, config):
    views_cfg = config.get("views", {})
    beh_val = views_cfg.get("behaviourDiagram")
    if beh_val is None or beh_val is False:
        print("  behaviourDiagram: skipped (views.behaviourDiagram not enabled)")
        return
    beh_cfg = beh_val if isinstance(beh_val, dict) else {}

    root = os.path.dirname(output_dir)
    out_dir = os.path.join(output_dir, "behaviour_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    # Construct generator once with model paths (functions, modules, units).
    functions_path = os.path.join(model_dir, "functions.json")
    modules_path = os.path.join(model_dir, "modules.json")
    units_path = os.path.join(model_dir, "units.json")
    gen = FakeBehaviourGenerator(functions_path, modules_path, units_path)

    functions = list(model.get("functions", {}))
    total = len(functions)
    count = 0
    with_diagram = []
    behaviour_pngs = {}  # fid -> list of PNG paths for DOCX

    for i, fid in enumerate(functions, 1):
        print(f"  behaviourDiagram: {i}/{total} functions...", end="\r", flush=True)

        try:
            mmd_paths = gen.generate_for_function(fid, out_dir) or []
        except Exception as e:
            print(f"  behaviourDiagram: generator error for {fid}: {e}", file=sys.stderr)
            continue

        if not mmd_paths:
            continue

        safe = safe_filename(fid)
        png_paths = []

        if not beh_cfg.get("renderPng", True):
            with_diagram.append(fid)
            # No PNGs; exporter will not find _behaviour_pngs entries, can fall back to single path
            count += 1
            continue

        mmdc = mmdc_path(root)
        puppeteer = beh_cfg.get("puppeteerConfigPath") or os.path.join(root, "config", "puppeteer-config.json")
        if not os.path.isabs(puppeteer):
            puppeteer = os.path.join(root, puppeteer)
        run_cmd_base = [mmdc]
        if os.path.isfile(puppeteer):
            run_cmd_base.extend(["-p", puppeteer])

        for idx, mmd_path in enumerate(mmd_paths):
            if not os.path.isfile(mmd_path):
                continue
            png_name = f"{safe}.png" if idx == 0 else f"{safe}_{idx}.png"
            png = os.path.join(out_dir, png_name)
            run_cmd = run_cmd_base + ["-i", mmd_path, "-o", png]
            try:
                r2 = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60, check=False)
                if r2.returncode == 0 and os.path.isfile(png):
                    png_paths.append(png)
                elif r2.returncode != 0 and idx == 0:
                    msg = (r2.stderr or r2.stdout or f"exit {r2.returncode}").strip()
                    print(f"  behaviourDiagram: mmdc failed: {msg}", file=sys.stderr)
            except FileNotFoundError:
                if idx == 0:
                    print("  behaviourDiagram: mmdc not found. Run: npm install", file=sys.stderr)
                break
            except subprocess.TimeoutExpired:
                if idx == 0:
                    print("  behaviourDiagram: mmdc timed out", file=sys.stderr)
                break

        if png_paths:
            with_diagram.append(fid)
            behaviour_pngs[fid] = png_paths
        count += 1

    status_path = os.path.join(out_dir, "_with_diagram.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(with_diagram, f, indent=2)
    # Map fid -> list of PNG paths (DOCX exporter uses this to show all diagrams per function)
    pngs_path = os.path.join(out_dir, "_behaviour_pngs.json")
    with open(pngs_path, "w", encoding="utf-8") as f:
        json.dump(behaviour_pngs, f, indent=2)

    print()  # newline after progress
    print(f"  output/behaviour_diagrams/ ({count} functions processed)")
