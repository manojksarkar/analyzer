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
from utils import mmdc_path, safe_filename, KEY_SEP
from fake_behaviour_diagram_generator import FakeBehaviourGenerator


def _build_docx_rows(model, with_diagram):
    """Build per-module rows for DOCX Dynamic Behaviour: one row per external call,
    or one row per function with diagram but no external calls (fallback: current_unit - current_unit_function).
    Returns { module_name: [ {currentUnit, externalUnitFunction, callerFid}, ... ] }.
    """
    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    fid_to_unit = {}
    for uk, u in units_data.items():
        for fid in u.get("functionIds", []):
            fid_to_unit[fid] = uk
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
                  for uk, u in units_data.items()}
    by_module = {}
    for fid in with_diagram:
        unit_key = fid_to_unit.get(fid)
        if not unit_key:
            continue
        module_name = unit_key.split(KEY_SEP)[0] if KEY_SEP in unit_key else ""
        current_unit = unit_names.get(unit_key, unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key)
        fid_parts = (fid or "").split(KEY_SEP)
        func_qualified = fid_parts[2] if len(fid_parts) >= 3 else ""
        func_short = func_qualified.split("::")[-1] if "::" in func_qualified else func_qualified
        calls_ids = functions_data.get(fid, {}).get("callsIds", []) or []
        has_external = False
        for callee_fid in calls_ids:
            parts = (callee_fid or "").split(KEY_SEP)
            if len(parts) < 3:
                continue
            callee_module = parts[0]
            if callee_module == module_name:
                continue
            has_external = True
            external_unit = parts[1]
            qualified = parts[2]
            external_func = qualified.split("::")[-1] if "::" in qualified else qualified
            external_unit_external_function = f"{external_unit}_{external_func}"
            by_module.setdefault(module_name, []).append({
                "currentUnit": current_unit,
                "externalUnitFunction": external_unit_external_function,
                "callerFid": fid,
            })
        if not has_external:
            by_module.setdefault(module_name, []).append({
                "currentUnit": current_unit,
                "externalUnitFunction": f"{current_unit}_{func_short}",
                "callerFid": fid,
            })
    return by_module


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
    # Map fid -> list of PNG paths + per-module docx rows (DOCX exporter uses both)
    docx_rows = _build_docx_rows(model, with_diagram)
    pngs_export = {**behaviour_pngs, "_docxRows": docx_rows}
    pngs_path = os.path.join(out_dir, "_behaviour_pngs.json")
    with open(pngs_path, "w", encoding="utf-8") as f:
        json.dump(pngs_export, f, indent=2)

    print()  # newline after progress
    print(f"  output/behaviour_diagrams/ ({count} functions processed)")
