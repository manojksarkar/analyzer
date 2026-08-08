"""Unit diagram view: one Mermaid flowchart per unit (boxes for units, edges = interfaceIds)."""
import json
import os
import re
import shutil
import subprocess
import sys

from .registry import register
from utils import KEY_SEP, log, mmdc_path, safe_filename, os_type, render_mermaid_cached


def _affected_units(impact_fids, functions_data, fid_to_unit):
    """M3.10: the set of unit_keys whose diagram may have changed = units of the impacted
    functions PLUS their 1-hop cross-unit neighbours (callees + callers). A unit diagram
    shows the edges incident to the unit, so any change to a function in the unit OR to a
    function it calls / is called by can alter it. Over-approximates (D7: never stale)."""
    affected_fids = set(impact_fids)
    for fid in impact_fids:
        f = functions_data.get(fid) or {}
        affected_fids.update(f.get("callsIds") or [])
        affected_fids.update(f.get("calledByIds") or [])
    return {fid_to_unit[fid] for fid in affected_fids if fid in fid_to_unit}


def _apply_incremental_unit_plan(model_dir, out_dir, functions_data, fid_to_unit, cpp_units):
    """Incremental unit-diagram reuse (M3.10). If model/incremental_plan.json exists, carry
    forward the baseline version's unit diagrams (.mmd + .png), drop orphans (renamed/
    deleted units), and return the SET of unit_keys to regenerate. None -> no plan (caller
    does a full wipe + regenerate)."""
    plan_path = os.path.join(os.path.abspath(model_dir), "incremental_plan.json")
    if not os.path.isfile(plan_path):
        return None
    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    # 1. carry forward the baseline version's unit diagrams (engine cleaned output/).
    base_ver_dir = plan.get("baselineVersionDir")
    if base_ver_dir:
        project_root = os.path.dirname(os.path.abspath(model_dir))
        rel = os.path.relpath(out_dir, os.path.join(project_root, "output"))
        base_ud = os.path.join(base_ver_dir, "output", rel)
        if os.path.isdir(base_ud):
            carried = 0
            for fn in os.listdir(base_ud):
                if fn.endswith(".mmd") or fn.endswith(".png"):
                    shutil.copyfile(os.path.join(base_ud, fn), os.path.join(out_dir, fn))
                    carried += 1
            log(f"incremental: carried forward {carried} baseline unit-diagram file(s)", "unitDiagrams")

    # 2. move/rename cleanup: drop carried diagrams for units no longer in the model.
    valid = {safe_filename(uk) for uk in cpp_units}
    if valid:
        for fn in os.listdir(out_dir):
            if (fn.endswith(".mmd") or fn.endswith(".png")) and fn.rsplit(".", 1)[0] not in valid:
                try:
                    os.unlink(os.path.join(out_dir, fn))
                except OSError:
                    pass

    # 3. regenerate only the affected units.
    affected = _affected_units(set(plan.get("impactFids") or []), functions_data, fid_to_unit)
    log(f"incremental: unit diagrams restricted to {len(affected & set(cpp_units))} affected "
        f"unit(s) of {len(cpp_units)}", "unitDiagrams")
    return affected


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
    return (unit_key or "").replace(KEY_SEP, "_").replace(" ", "-") or "u"


def _escape_label(text):
    """Escape text for Mermaid (avoid breaking diagram)."""
    t = text or ""
    t = t.replace('"', "'").replace("\n", " ").replace("|", "\u00a6")
    return t


# One arrow carries every interface id for a unit pair (REQ-UD-05), so a busy edge stacks
# 10+ ids in a single label. Joined with a bare <br/> they render as contiguous rows of text
# with no leading \u2014 the reported "no space between the lines/labels".
#
# Spacing lives in the GRAPH TEXT, not in layout hints: mermaid 10.9.5 silently IGNORES the
# ELK spacing options. Rendering Sample-Core_Core with elk.spacing.edgeEdge / edgeLabel /
# edgeNode / nodeNode + layered.spacing.* produced a byte-identical 1374x700 PNG, so no ELK
# block is emitted \u2014 it would be dead config that reads as if it works.
#
# Three text levers, measured on that diagram (edges of 1 / 10 / 7 ids):
#   blank line between rows   1374x700 -> 1374x1270, rows legible but the column is very tall
#   + two ids per row         -> 1568x618, compact
#   + a "to <partner>" header -> 1568x760, and the block finally says which arrow it belongs to
# Without the header the label blocks of two adjacent edges ABUT, and a reader cannot tell
# where one ends \u2014 the ids sit in a column of their own, not on their arrow.
#
# Rejected: one arrow per id (fixes association outright but needs a REQ-UD-05 spec change,
# and a unit with 30 interfaces to one partner fans into 30 arrows) and capping ids per
# label (the diagram must stay complete).
_LABEL_SEP = "<br/> <br/>"
_IDS_PER_ROW = 2


def _label_header(dest_name):
    """'to <partner>' \u2014 sanitised. Parentheses and pipes break the Mermaid edge-label parse."""
    t = re.sub(r"(?:<br/>|\s)+", " ", dest_name or "").strip()
    t = re.sub(r"[()|\[\]]", "", t)
    return f"to {t}" if t else ""


def _edge_label(ifaces, dest_name=""):
    """Interface ids for one edge: an optional destination header, then rows of ids.

    The header is only added for a multi-id edge \u2014 a single id needs no disambiguation and
    the header would just be clutter.
    """
    ids = sorted(ifaces)
    if not ids:
        return ""
    if len(ids) == 1:
        return _escape_label(ids[0])
    rows = [", ".join(ids[i:i + _IDS_PER_ROW]) for i in range(0, len(ids), _IDS_PER_ROW)]
    header = _label_header(dest_name)
    if header:
        rows.insert(0, header)
    return _escape_label(_LABEL_SEP.join(rows))


def _build_unit_diagram(
    unit_key,
    unit_info,
    units_data,
    functions_data,
    fid_to_unit,
    unit_names,
    *,
    allowed_components: set | None = None,
):
    """Build Mermaid flowchart for one unit: one box per unit, edges labeled with interfaceIds.
    If allowed_components is provided, "internal" means: units whose module is in allowed_components."""
    if not (unit_info.get("fileName") or "").endswith(".cpp"):
        return None

    this_id = _unit_part_id(unit_key)
    this_component = unit_key.split(KEY_SEP)[0] if KEY_SEP in unit_key else ""

    edges = {}

    def _dir_of(fn):
        return "out" if (fn.get("direction") or "In").strip().lower() == "out" else "in"

    def _add_edge(owner_unit, other_unit, iface, direction):
        # 3.6: orient each edge by the interface OWNER's In/Out so the SAME edge renders
        # identically in both units' diagrams. Out => owner->other (arrow away from owner),
        # In => other->owner (arrow towards owner). The caller's own direction is irrelevant.
        if not owner_unit or not other_unit or owner_unit == other_unit or not iface:
            return
        o, x = _unit_part_id(owner_unit), _unit_part_id(other_unit)
        key = (o, x) if direction == "out" else (x, o)
        edges.setdefault(key, set()).add(iface)

    for fid in unit_info.get("functionIds", []):
        if fid not in functions_data:
            continue
        f = functions_data[fid]
        # 3.15: only this unit's OWNED (caller) edges are drawn. Each caller edge is oriented by
        # f's own direction. Callee edges (functions this unit uses) are intentionally dropped —
        # they render in the partner (provider) unit's own diagram, so every relationship still
        # appears exactly once across the model, from the provider's perspective.
        for caller_fid in f.get("calledByIds", []) or []:
            _add_edge(unit_key, fid_to_unit.get(caller_fid), f.get("interfaceId", ""), _dir_of(f))
        # A function published by a file-scope table has no caller function, so its
        # relationship to the registering unit would otherwise never be drawn. In-body
        # address-takes are already ordinary call edges above.
        for registrar_unit in f.get("addressTakenByUnits", []) or []:
            _add_edge(unit_key, registrar_unit, f.get("interfaceId", ""), _dir_of(f))

    caller_ids = {fr for (fr, to) in edges if to == this_id}
    callee_ids = {to for (fr, to) in edges if fr == this_id}
    internal_set = set()
    for uk in units_data:
        pid = _unit_part_id(uk)
        uk_component = uk.split(KEY_SEP)[0] if KEY_SEP in uk else ""
        if allowed_components:
            if uk_component.lower() in allowed_components:
                internal_set.add(pid)
        else:
            if uk_component == this_component:
                internal_set.add(pid)
    # A partner that has arrows in BOTH directions (mutual) is drawn on BOTH sides: once as a
    # caller (inbound arrow + inbound interface ids) and once as a callee (outbound arrow +
    # outbound interface ids). Same rule for internal (module box, top vs bottom) and external
    # (left vs right) partners. The two boxes need distinct node ids or Mermaid collapses them
    # into one, so the callee-side box gets a suffix. Interface ids split naturally by direction
    # because each side only carries the edges pointing its way.
    mutual = caller_ids & callee_ids

    def _callee_node_id(pid):
        return f"{pid}__out" if pid in mutual else pid

    internal_callers = sorted(caller_ids & internal_set)
    external_callers = sorted(caller_ids - internal_set)
    internal_callees = sorted(callee_ids & internal_set)
    external_callees = sorted(callee_ids - internal_set)

    # Blank <br/> lines padding the main node's label make it taller, which spreads its edge
    # PORTS apart. Kept keyed to edge COUNT on purpose: re-keying it to label height was
    # tried and rejected — for Sample-Core_Core (edges of 1/10/7 ids) padding of 10 and 18
    # lines both rendered byte-identically to no padding at all, because once labels are tall
    # the label column, not the node, sets the height. Only an absurd 36 lines moved it, and
    # that renders the unit as a grotesque tall bar. Row spacing is handled by _LABEL_SEP.
    n_edges = len(edges)
    n_extra_lines = min(max(2, n_edges), 12)
    pad = "   "

    def _display_name(pid):
        """Human name for a node id — for the edge-label header. Strips the callee-side
        `__out` suffix and never returns the main unit's <br/>-padded box text."""
        base_pid = pid[:-len("__out")] if pid.endswith("__out") else pid
        for uk in units_data:
            if _unit_part_id(uk) == base_pid:
                if base_pid == this_id:
                    return unit_names.get(uk, uk)
                return uk.replace(KEY_SEP, "/").replace("-", " ")
        return ""

    def _node_line(node_id, base_pid=None):
        base_pid = base_pid if base_pid is not None else node_id
        for uk in units_data:
            if _unit_part_id(uk) == base_pid:
                raw = unit_names.get(uk, uk) if base_pid == this_id else uk.replace(KEY_SEP, "/").replace("-", " ")
                box_label = (raw or "?").replace("]", "'").replace("[", "'")
                if base_pid == this_id:
                    extra = "<br/>".join([f"{pad} " for _ in range(n_extra_lines)])
                    box_label = f"{pad}{box_label}{pad}<br/>{extra}"
                return f'  {node_id}["{box_label}"]'
        return ""

    lines = [
        """---
config:
  flowchart:
    defaultRenderer: elk
---""",
        "flowchart LR",
        "  classDef internal fill:#87CEEB,stroke:#333,stroke-width:1px",
        "  classDef mainUnit fill:#87CEEB,stroke:#4682B4,stroke-width:3px",
        "",
    ]

    # External callers (left)
    for pid in external_callers:
        lines.append("  " + _node_line(pid).strip())

    # Internal module (yellow box)
    mod_label = (this_component or "Internal").replace("-", " ").replace('"', "'").replace("]", "'").replace("[", "'")
    lines.append(f'  subgraph internal_mod["{mod_label}"]')
    lines.append("    direction TB")
    lines.append("    style internal_mod fill:#ffffcc,stroke:#d4d400,stroke-width:2px")
    lines.append("")
    for pid in internal_callers:
        lines.append("    " + _node_line(pid).strip())
    lines.append("    " + _node_line(this_id).strip())
    for pid in internal_callees:
        lines.append("    " + _node_line(_callee_node_id(pid), pid).strip())
    lines.append("")

    # Internal edges (partner inside the module). Outbound arrows land on the callee-side box.
    for (fr, to), ifaces in sorted(edges.items()):
        partner = fr if to == this_id else to
        if partner not in internal_set:
            continue
        src, dst = (fr, to) if to == this_id else (fr, _callee_node_id(to))
        label = _edge_label(ifaces, _display_name(dst))
        lines.append(f"    {src} -->|{label}| {dst}")
    lines.append("")
    lines.append(f"    class {this_id} mainUnit")
    others = internal_callers + [_callee_node_id(p) for p in internal_callees]
    if others:
        lines.append("    class " + ",".join(others) + " internal")
    lines.append("  end")
    lines.append("")

    # External callees (right)
    for pid in external_callees:
        lines.append("  " + _node_line(_callee_node_id(pid), pid).strip())
    lines.append("")

    # External connections (partner outside the module). Outbound arrows land on the callee box.
    for (fr, to), ifaces in sorted(edges.items()):
        partner = fr if to == this_id else to
        if partner in internal_set:
            continue
        src, dst = (fr, to) if to == this_id else (fr, _callee_node_id(to))
        label = _edge_label(ifaces, _display_name(dst))
        lines.append(f"  {src} -->|{label}| {dst}")

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
    allowed_components = {m.lower() for m in (config.get("_analyzerAllowedComponents") or [])}

    fid_to_unit = _fid_to_unit(units_data)
    unit_names = {
        uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
        for uk, u in units_data.items()
    }

    out_dir = os.path.join(output_dir, "unit_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    render_png = True
    # Project root must not be derived from output_dir: with --all-groups output is output/<group>/.
    project_root = os.path.dirname(os.path.abspath(model_dir))
    mmdc = mmdc_path(project_root)
    puppeteer = os.path.join(project_root, "engine", "config", "puppeteer-config.json")
    if not os.path.isabs(puppeteer):
        puppeteer = os.path.join(project_root, puppeteer)
    run_cmd_base = [mmdc]
    if os.path.isfile(puppeteer):
        run_cmd_base.extend(["-p", puppeteer])

    cpp_units = [uk for uk, u in units_data.items() if (u.get("fileName") or "").endswith(".cpp")]
    if allowed_components:
        cpp_units = [uk for uk in cpp_units if KEY_SEP in uk and uk.split(KEY_SEP, 1)[0].lower() in allowed_components]

    # Incremental (M3.10): carry forward baseline diagrams + render only AFFECTED units.
    # No plan -> full: wipe and regenerate every unit (original behaviour).
    affected = _apply_incremental_unit_plan(model_dir, out_dir, functions_data, fid_to_unit, cpp_units)
    if affected is None:
        for f in os.listdir(out_dir):
            try:
                os.unlink(os.path.join(out_dir, f))
            except OSError:
                pass
        units_to_render = sorted(cpp_units)
    else:
        units_to_render = sorted(uk for uk in cpp_units if uk in affected)

    from core.progress import ProgressReporter
    from core.logging_setup import get_logger
    total = len(units_to_render)
    progress = ProgressReporter("unitDiagrams", total=total, logger=get_logger("unitDiagrams"))
    progress.start()
    for i, unit_key in enumerate(units_to_render, 1):
        progress.step(label=unit_key)
        unit_info = units_data[unit_key]
        mermaid = _build_unit_diagram(
            unit_key,
            unit_info,
            units_data,
            functions_data,
            fid_to_unit,
            unit_names,
            allowed_components=allowed_components or None,
        )
        if not mermaid:
            continue
        safe = safe_filename(unit_key)
        mmd_path = os.path.join(out_dir, f"{safe}.mmd")
        with open(mmd_path, "w", encoding="utf-8") as f:
            f.write(mermaid)
        if render_png:
            png_path = os.path.join(out_dir, f"{safe}.png")
            # M-A: content-addressed cache -> unchanged unit diagrams skip mmdc.
            render_mermaid_cached(project_root, mermaid, png_path, scale=2, timeout=60)
    _suffix = " regenerated (rest carried)" if affected is not None else ""
    progress.done(summary=f"output/unit_diagrams/ ({total} units{_suffix})")
