"""Behaviour diagram view. Runs script per function, writes .mmd/.png."""
import json
import os
import subprocess
import sys

from .registry import register
from utils import safe_filename




def _mmdc_path(project_root: str) -> str:
    ext = ".cmd" if sys.platform == "win32" else ""
    local = os.path.join(project_root, "node_modules", ".bin", "mmdc" + ext)
    return local if os.path.isfile(local) else "mmdc"


@register("behaviourDiagram")
def run(model, output_dir, model_dir, config):
    beh = config.get("views", {}).get("behaviourDiagram") or {}
    if not isinstance(beh, dict):
        beh = {}
    cmd_tpl = beh.get("scriptCmd")
    if not cmd_tpl or not isinstance(cmd_tpl, list) or "{fid}" not in str(cmd_tpl):
        print("  behaviourDiagram: skipped (views.behaviourDiagram.scriptCmd with {fid} required)")
        return

    root = os.path.dirname(output_dir)
    out_dir = os.path.join(output_dir, "behaviour_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    functions = list(model.get("functions", {}))
    total = len(functions)
    count = 0
    with_diagram = []  # fids where CLI returned non-empty and PNG created
    for i, fid in enumerate(functions, 1):
        print(f"  behaviourDiagram: {i}/{total} functions...", end="\r", flush=True)
        args = [fid if str(x) == "{fid}" else str(x) for x in cmd_tpl]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60, cwd=root)
        except subprocess.TimeoutExpired:
            print(f"  behaviourDiagram: timeout for {fid}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"  behaviourDiagram: error for {fid}: {e}", file=sys.stderr)
            continue

        mermaid = (r.stdout or "").strip()
        if not mermaid and r.stderr:
            print(f"  behaviourDiagram: {fid}: {r.stderr.strip()}", file=sys.stderr)
        if not mermaid:
            continue

        safe = safe_filename(fid)
        mmd = os.path.join(out_dir, f"{safe}.mmd")
        png = os.path.join(out_dir, f"{safe}.png")
        with open(mmd, "w", encoding="utf-8") as f:
            f.write(mermaid)

        if beh.get("skipPngRender"):
            count += 1
            continue

        mmdc = _mmdc_path(root)
        puppeteer = beh.get("puppeteerConfigPath") or os.path.join(root, "config", "puppeteer-config.json")
        if not os.path.isabs(puppeteer):
            puppeteer = os.path.join(root, puppeteer)
        run_cmd = [mmdc]
        if os.path.isfile(puppeteer):
            run_cmd.extend(["-p", puppeteer])
        run_cmd.extend(["-i", mmd, "-o", png])
        try:
            r2 = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60, check=False)
            if r2.returncode != 0:
                msg = (r2.stderr or r2.stdout or f"exit {r2.returncode}").strip()
                print(f"  behaviourDiagram: mmdc failed: {msg}", file=sys.stderr)
            else:
                with_diagram.append(fid)
        except FileNotFoundError:
            print(f"  behaviourDiagram: mmdc not found. Run: npm install", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print("  behaviourDiagram: mmdc timed out", file=sys.stderr)
        count += 1

    # List of fids where CLI returned non-empty (docx_exporter uses this)
    status_path = os.path.join(out_dir, "_with_diagram.json")
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(with_diagram, f, indent=2)

    print()  # newline after progress
    print(f"  output/behaviour_diagrams/ ({count} diagrams)")
