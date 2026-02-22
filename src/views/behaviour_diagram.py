"""Behaviour diagram view.

Creates behaviour diagrams per external call by delegating to a generator object.
The generator returns one .mmd per external call (current_key_callee_key.mmd).
We render each to PNG and build docx rows with pngPath for the exporter.
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
from utils import mmdc_path, safe_filename, KEY_SEP
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

    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    fid_to_unit = {fid: uk for uk, u in units_data.items() for fid in u.get("functionIds", [])}
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
                  for uk, u in units_data.items()}

    functions_path = os.path.join(model_dir, "functions.json")
    modules_path = os.path.join(model_dir, "modules.json")
    units_path = os.path.join(model_dir, "units.json")
    gen = FakeBehaviourGenerator(functions_path, modules_path, units_path)

    render_png = beh_cfg.get("renderPng", True)
    mmdc = mmdc_path(root)
    puppeteer = beh_cfg.get("puppeteerConfigPath") or os.path.join(root, "config", "puppeteer-config.json")
    if not os.path.isabs(puppeteer):
        puppeteer = os.path.join(root, puppeteer)
    run_cmd_base = [mmdc]
    if os.path.isfile(puppeteer):
        run_cmd_base.extend(["-p", puppeteer])

    docx_rows = {}  # module -> [ {currentUnit, externalUnitFunction, pngPath} ]
    functions = list(model.get("functions", {}))
    total = len(functions)
    count = 0

    for i, fid in enumerate(functions, 1):
        print(f"  behaviourDiagram: {i}/{total} functions...", end="\r", flush=True)

        try:
            mmd_paths = gen.generate_for_function(fid, out_dir) or []
        except Exception as e:
            print(f"  behaviourDiagram: generator error for {fid}: {e}", file=sys.stderr)
            continue

        if not mmd_paths:
            continue

        unit_key = fid_to_unit.get(fid)
        if not unit_key:
            continue
        module_name = unit_key.split(KEY_SEP)[0] if KEY_SEP in unit_key else ""
        current_unit = unit_names.get(unit_key, unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key)
        calls_ids = functions_data.get(fid, {}).get("callsIds", []) or []
        external_callees = [c for c in calls_ids if c and "|" in c and c.split("|")[0] != module_name]

        for idx, mmd_path in enumerate(mmd_paths):
            if idx >= len(external_callees):
                break
            callee_fid = external_callees[idx]
            parts = (callee_fid or "").split(KEY_SEP)
            if len(parts) < 3:
                continue
            qualified = parts[2]
            external_func = qualified.split("::")[-1] if "::" in qualified else qualified
            external_unit_external_function = f"{parts[1]}_{external_func}"

            png_path = None
            if render_png and os.path.isfile(mmd_path):
                png_base = os.path.splitext(os.path.basename(mmd_path))[0]
                png = os.path.join(out_dir, f"{png_base}.png")
                run_cmd = run_cmd_base + ["-i", mmd_path, "-o", png]
                try:
                    r2 = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60, check=False)
                    if r2.returncode == 0 and os.path.isfile(png):
                        png_path = png
                    elif r2.returncode != 0 and idx == 0:
                        msg = (r2.stderr or r2.stdout or f"exit {r2.returncode}").strip()
                        print(f"  behaviourDiagram: mmdc failed: {msg}", file=sys.stderr)
                except FileNotFoundError:
                    if idx == 0:
                        print("  behaviourDiagram: mmdc not found. Run: npm install", file=sys.stderr)
                except subprocess.TimeoutExpired:
                    if idx == 0:
                        print("  behaviourDiagram: mmdc timed out", file=sys.stderr)

            docx_rows.setdefault(module_name, []).append({
                "currentUnit": current_unit,
                "externalUnitFunction": external_unit_external_function,
                "pngPath": png_path,
            })
            count += 1

    out_path = os.path.join(out_dir, "_behaviour_pngs.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"_docxRows": docx_rows}, f, indent=2)

    print()
    print(f"  output/behaviour_diagrams/ ({count} diagrams)")
