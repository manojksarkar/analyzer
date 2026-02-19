"""Unit diagram view: one Mermaid flowchart per unit (boxes for units, edges = interfaceIds)."""
import os
import subprocess
import sys

from .registry import register
from utils import KEY_SEP, safe_filename


def _mmdc_path(project_root: str) -> str:
    ext = ".cmd" if sys.platform == "win32" else ""
    local = os.path.join(project_root, "node_modules", ".bin", "mmdc" + ext)
    return local if os.path.isfile(local) else "mmdc"


def _fid_to_unit(units_data):
    """functionId -> unit_key (first unit that contains this function)."""
    out = {}
    for unit_key, unit_info in units_data.items():
        for fid in unit_info.get("functionIds", []):
            if fid not in out:
                out[fid] = unit_key
    return out


def _unit_part_id(unit_key):
    """Mermaid node id (safe, no | or special chars)."""
    return (unit_key or "").replace(KEY_SEP, "_").replace(" ", "_") or "u"


def _escape_label(text):
    """Escape text for Mermaid (avoid breaking diagram)."""
    t = text or ""
    t = t.replace('"', "'").replace("\n", " ").replace("|", "\u00a6")
    return t


def _build_unit_diagram(unit_key, unit_info, units_data, functions_data, fid_to_unit, unit_names):
    """Build Mermaid flowchart for one unit: one box per unit, edges labeled with interfaceIds."""
    if not (unit_info.get("fileName") or "").endswith(".cpp"):
        return None

    this_id = _unit_part_id(unit_key)
    this_module = unit_key.split(KEY_SEP)[0] if KEY_SEP in unit_key else ""

    edges = {}
    for fid in unit_info.get("functionIds", []):
        if fid not in functions_data:
            continue
        f = functions_data[fid]
        for callee_fid in f.get("callsIds", []) or []:
            callee_unit = fid_to_unit.get(callee_fid)
            if not callee_unit or callee_unit == unit_key:
                continue
            callee_f = functions_data.get(callee_fid, {})
            iface = callee_f.get("interfaceId", "")
            if iface:
                key = (this_id, _unit_part_id(callee_unit))
                edges.setdefault(key, set()).add(iface)

    for fid in unit_info.get("functionIds", []):
        if fid not in functions_data:
            continue
        f = functions_data[fid]
        iface = f.get("interfaceId", "")
        if not iface:
            continue
        for caller_fid in f.get("calledByIds", []) or []:
            caller_unit = fid_to_unit.get(caller_fid)
            if not caller_unit or caller_unit == unit_key:
                continue
            key = (_unit_part_id(caller_unit), this_id)
            edges.setdefault(key, set()).add(iface)

    caller_ids = {fr for (fr, to) in edges if to == this_id}
    callee_ids = {to for (fr, to) in edges if fr == this_id}
    same_mod = set()
    for uk in units_data:
        pid = _unit_part_id(uk)
        uk_module = uk.split(KEY_SEP)[0] if KEY_SEP in uk else ""
        if uk_module == this_module:
            same_mod.add(pid)
    internal_callers = sorted(caller_ids & same_mod)
    external_callers = sorted(caller_ids - same_mod)
    internal_callees = sorted((callee_ids - caller_ids) & same_mod)
    external_callees = sorted((callee_ids - caller_ids) - same_mod)

    n_edges = len(edges)
    n_extra_lines = min(max(2, n_edges), 12)
    pad = "   "

    def _node_line(pid):
        for uk in units_data:
            if _unit_part_id(uk) == pid:
                raw = unit_names.get(uk, uk) if pid == this_id else uk.replace(KEY_SEP, "/")
                box_label = (raw or "?").replace("]", "'").replace("[", "'")
                if pid == this_id:
                    extra = "<br/>".join([f"{pad} " for _ in range(n_extra_lines)])
                    box_label = f"{pad}{box_label}{pad}<br/>{extra}"
                return f'  {pid}["{box_label}"]'
        return ""

    lines = ["flowchart LR"]
    lines.append("  classDef internal fill:#87CEEB,stroke:#333,stroke-width:1px")
    lines.append("  classDef mainUnit fill:#87CEEB,stroke:#4682B4,stroke-width:3px")
    lines.append("")

    # External callers (left) - invisible subgraph for layout
    if external_callers:
        lines.append("  subgraph ext_left[ ]")
        lines.append("    direction TB")
        lines.append("    style ext_left fill:none,stroke:none")
        for pid in external_callers:
            lines.append("    " + _node_line(pid).strip())
        lines.append("  end")
        lines.append("")

    # Internal module (yellow box) - callers (top) -> this -> callees (bottom)
    mod_label = (this_module or "Internal").replace("]", "'").replace("[", "'")
    lines.append(f'  subgraph internal_mod[{mod_label}]')
    lines.append("    direction TB")
    lines.append("    style internal_mod fill:#ffffcc,stroke:#d4d400,stroke-width:2px")
    lines.append("")
    for pid in internal_callers:
        lines.append("    " + _node_line(pid).strip())
    lines.append("    " + _node_line(this_id).strip())
    for pid in internal_callees:
        lines.append("    " + _node_line(pid).strip())
    lines.append("")

    # Internal edges (inside yellow box)
    for (fr, to), ifaces in sorted(edges.items()):
        if fr in same_mod and to in same_mod:
            label = "<br/>".join(sorted(ifaces))
            label = _escape_label(label)
            lines.append(f'    {fr} -- "{label}" --> {to}')
    lines.append("")
    # Apply classes to internal nodes
    lines.append(f"    class {this_id} mainUnit")
    others = internal_callers + internal_callees
    if others:
        lines.append("    class " + ",".join(others) + " internal")
    lines.append("  end")
    lines.append("")

    # External callees (right) - invisible subgraph for layout
    if external_callees:
        lines.append("  subgraph ext_right[ ]")
        lines.append("    direction TB")
        lines.append("    style ext_right fill:none,stroke:none")
        for pid in external_callees:
            lines.append("    " + _node_line(pid).strip())
        lines.append("  end")
        lines.append("")

    # External connections - direct edges
    for (fr, to), ifaces in sorted(edges.items()):
        label = "<br/>".join(sorted(ifaces))
        label = _escape_label(label)
        is_ext_in = fr in external_callers and to in same_mod
        is_ext_out = fr in same_mod and to in external_callees
        if is_ext_in or is_ext_out:
            lines.append(f'  {fr} -- "{label}" --> {to}')

    return "\n".join(lines) if len(lines) > 1 else None


@register("unitDiagrams")
def run(model, output_dir, model_dir, config):
    views_cfg = config.get("views", {})
    enabled = views_cfg.get("unitDiagrams", False)
    if not enabled:
        return

    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    if not units_data or not functions_data:
        return

    fid_to_unit = _fid_to_unit(units_data)
    unit_names = {
        uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
        for uk, u in units_data.items()
    }

    out_dir = os.path.join(output_dir, "unit_diagrams")
    if os.path.isdir(out_dir):
        for f in os.listdir(out_dir):
            try:
                os.unlink(os.path.join(out_dir, f))
            except OSError:
                pass
    os.makedirs(out_dir, exist_ok=True)

    ud_cfg = views_cfg.get("unitDiagrams") if isinstance(views_cfg.get("unitDiagrams"), dict) else {}
    render_png = ud_cfg.get("renderPng", True)
    root = os.path.dirname(output_dir)
    mmdc = _mmdc_path(root)
    puppeteer = ud_cfg.get("puppeteerConfigPath") or os.path.join(root, "config", "puppeteer-config.json")
    if not os.path.isabs(puppeteer):
        puppeteer = os.path.join(root, puppeteer)
    run_cmd_base = [mmdc]
    if os.path.isfile(puppeteer):
        run_cmd_base.extend(["-p", puppeteer])

    cpp_units = [uk for uk, u in units_data.items() if (u.get("fileName") or "").endswith(".cpp")]
    total = len(cpp_units)
    for i, unit_key in enumerate(sorted(cpp_units), 1):
        print(f"  unitDiagrams: {i}/{total} units...", end="\r", flush=True)
        unit_info = units_data[unit_key]
        mermaid = _build_unit_diagram(
            unit_key, unit_info, units_data, functions_data, fid_to_unit, unit_names
        )
        if not mermaid:
            continue
        safe = safe_filename(unit_key)
        mmd_path = os.path.join(out_dir, f"{safe}.mmd")
        with open(mmd_path, "w", encoding="utf-8") as f:
            f.write(mermaid)
        if render_png:
            png_path = os.path.join(out_dir, f"{safe}.png")
            run_cmd = run_cmd_base + ["-i", mmd_path, "-o", png_path]
            try:
                subprocess.run(run_cmd, capture_output=True, text=True, timeout=60, check=False)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
    if total:
        print()
    print(f"  output/unit_diagrams/ ({total} units)")
