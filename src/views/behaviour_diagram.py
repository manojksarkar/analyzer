"""Behaviour diagram view. Calls external behaviour_diagram.py per function -> Mermaid."""
import os
import re
import subprocess
import sys

from .registry import register


def _safe_filename(key: str) -> str:
    """Convert function key to filesystem-safe name (| -> _)."""
    return re.sub(r'[<>:"/\\|?*]', "_", key)


@register("behaviourDiagram")
def run(model, output_dir, model_dir, config):
    """For each function, run: python behaviour_diagram.py <functionKey> --model <modelPath>. Write Mermaid to output/behaviour_diagrams/."""
    beh_cfg = config.get("views", {}).get("behaviourDiagram") or {}
    if not isinstance(beh_cfg, dict):
        beh_cfg = {}
    script_path = beh_cfg.get("scriptPath") or beh_cfg.get("script")
    if not script_path:
        print("  behaviourDiagram: skipped (config.behaviourDiagram.scriptPath not set)")
        return

    project_root = os.path.dirname(output_dir)  # output_dir is <project>/output
    abs_script = script_path if os.path.isabs(script_path) else os.path.join(project_root, script_path)
    if not os.path.isfile(abs_script):
        print(f"  behaviourDiagram: skipped (script not found: {abs_script})")
        return

    functions_data = model.get("functions", {})
    out_dir = os.path.join(output_dir, "behaviour_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for fid in functions_data:
        try:
            result = subprocess.run(
                [sys.executable, abs_script, fid, "--model", model_dir],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.path.dirname(abs_script),
            )
        except subprocess.TimeoutExpired:
            print(f"  behaviourDiagram: timeout for {fid}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"  behaviourDiagram: error for {fid}: {e}", file=sys.stderr)
            continue

        mermaid = result.stdout.strip() if result.stdout else ""
        if not mermaid and result.stderr:
            print(f"  behaviourDiagram: {fid}: {result.stderr.strip()}", file=sys.stderr)
        if mermaid:
            safe = _safe_filename(fid)
            mmd_path = os.path.join(out_dir, f"{safe}.mmd")
            png_path = os.path.join(out_dir, f"{safe}.png")
            with open(mmd_path, "w", encoding="utf-8") as f:
                f.write(mermaid)
            _render_mermaid_to_png(mmd_path, png_path, beh_cfg, project_root)
            count += 1

    print(f"  output/behaviour_diagrams/ ({count} diagrams)")


def _resolve_mmdc(project_root: str) -> str:
    """Resolve mmdc: node_modules/.bin/mmdc, else 'mmdc' from PATH."""
    ext = ".cmd" if sys.platform == "win32" else ""
    local = os.path.join(project_root, "node_modules", ".bin", "mmdc" + ext)
    if os.path.isfile(local):
        return local
    return "mmdc"


def _render_mermaid_to_png(mmd_path: str, png_path: str, config: dict, project_root: str):
    """Convert .mmd to .png via mmdc. Skips if skipPngRender is true."""
    if config.get("skipPngRender"):
        return
    mmdc = _resolve_mmdc(project_root)
    try:
        subprocess.run(
            [mmdc, "-i", mmd_path, "-o", png_path],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        print("  behaviourDiagram: mmdc not found. Run: npm install", file=sys.stderr)
