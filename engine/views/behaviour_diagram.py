"""Behaviour diagram view.

Creates behaviour diagrams when current unit gets called by external units.
The generator returns one .mmd per external caller (current_key__caller_key.mmd).
We render each to PNG and build docx rows with pngPath for the exporter.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Ensure engine is in path for behaviour_diagram imports
_src = Path(__file__).parent.parent
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from .registry import register

from behaviour_diagram import SequenceDiagramGenerator
from utils import log, mmdc_path, scoped_name, KEY_SEP, os_type


def _project_root() -> str:
    """The CODE root, for resolving tools and assets.

    Deliberately NOT derived from model_dir. These views need `node_modules/.bin/mmdc`,
    `engine/config/render_dot.mjs` and the shared `.mmdc_cache`, all of which live at the
    code root — while model_dir is DATA whose location moves (per-version dirs, an isolated
    test root). The old `dirname(model_dir)` coupled the two, which is why flowcharts.py
    needed a "walk up one extra level" special case, and why relocating model/ would have
    silently pointed the renderer at a directory with no render script in it: the render
    simply returns False and the flowchart never appears.
    """
    from core.paths import paths
    return paths().project_root



@register("behaviourDiagram")
def run(model, output_dir, model_dir, config):
    views_cfg = config.get("views", {})
    beh_val = views_cfg.get("behaviourDiagram")
    if beh_val is None or beh_val is False:
        log("skipped (views.behaviourDiagram not enabled)", component="behaviourDiagram")
        return

    project_root = _project_root()
    out_dir = os.path.join(output_dir, "behaviour_diagrams")
    os.makedirs(out_dir, exist_ok=True)

    units_data = model.get("units", {})
    functions_data = model.get("functions", {})
    allowed_components = {m.lower() for m in (config.get("_analyzerAllowedComponents") or [])}
    fid_to_unit = {fid: uk for uk, u in units_data.items() for fid in u.get("functionIds", [])}
    unit_names = {uk: u.get("name", uk.split(KEY_SEP)[-1] if KEY_SEP in uk else uk)
                  for uk, u in units_data.items()}

    # Pass the ALREADY-LOADED model, not paths (doc 10, step 5). run_views loads functions /
    # units / components through model_io before calling any view, so re-reading them from disk
    # was both redundant I/O and a bypass of the one gateway — in database mode those files do
    # not exist at all. SequenceDiagramGenerator accepts either.
    gen = SequenceDiagramGenerator(model.get("components") or {},
                                   model.get("units") or {},
                                   model.get("functions") or {}, config)

    render_png = True
    mmdc = mmdc_path(project_root)
    puppeteer = os.path.join(project_root, "engine", "config", "puppeteer-config.json")
    if not os.path.isabs(puppeteer):
        puppeteer = os.path.join(project_root, puppeteer)
    run_cmd_base = [mmdc, "--scale", "2"]
    if os.path.isfile(puppeteer):
        run_cmd_base.extend(["-p", puppeteer])

    docx_rows = {}  # component -> unit -> [ {externalUnitFunction, pngPath} ]
    rowed_mmd = set()          # .mmd files this run recorded a row for
    # Only generate diagrams for functions within the selected group (if any),
    # but keep full-model context so external callers (outside the group) are captured.
    if allowed_components:
        functions = [
            fid for fid, uk in fid_to_unit.items()
            if KEY_SEP in uk
            and uk.split(KEY_SEP, 1)[0].lower() in allowed_components
            and (functions_data.get(fid, {}).get("visibility") or "").lower() != "private"
        ]
    else:
        functions = [
            fid for fid in model.get("functions", {})
            if (functions_data.get(fid, {}).get("visibility") or "").lower() != "private"
        ]
    # --selected-unit narrows the RENDER, not the model walk.
    #
    # Deciding whether a function needs a behaviour diagram is free -- the selector
    # returns nothing for almost every function, measured at ~0.01s across 2817 of them.
    # The cost is mmdc, several seconds per PNG. So every function is still evaluated and
    # every row still recorded; only the image rendering is skipped for units the caller
    # did not name, reusing whatever PNG is already on disk.
    #
    # Narrowing the function list instead was wrong in a way that is easy to miss: the
    # rows for every other unit simply vanished, this manifest is the ONLY thing the
    # exporter reads to place a behaviour subsection, and the images stayed on disk -- so
    # the document came out with an empty "Dynamic Behaviour" heading beside a directory
    # that looked complete. It also could not repair itself: no --unit run could ever
    # restore rows a previous --unit run had dropped, only a full run could.
    #
    # This way the manifest is complete by construction, `--unit` still skips the
    # expensive work, and a narrowed run heals a manifest that was previously emptied.
    allowed_units = [u.lower() for u in (config.get("_analyzerSelectedUnits") or [])]
    from core.progress import ProgressReporter
    from core.logging_setup import get_logger
    total = len(functions)
    count = 0

    progress = ProgressReporter("behaviourDiagram", total=total, logger=get_logger("behaviourDiagram"))
    progress.start()
    for i, fid in enumerate(functions, 1):
        progress.step()

        try:
            result = gen.generate_all_diagrams(fid, out_dir)
            mmd_paths = result[0] if result else []
            behaviour_descriptions = result[1] if result else []
        except Exception as e:
            log("generator error for %s: %s" % (fid, e), component="behaviourDiagram", err=True)
            continue

        if not mmd_paths:
            continue

        unit_key = fid_to_unit.get(fid)
        if not unit_key:
            continue
        component_name = unit_key.split(KEY_SEP)[0] if KEY_SEP in unit_key else ""
        current_unit = unit_names.get(unit_key, unit_key.split(KEY_SEP)[-1] if KEY_SEP in unit_key else unit_key)
        called_by_ids = functions_data.get(fid, {}).get("calledByIds", []) or []
        # External = a DIFFERENT COMPONENT, which is exactly how the generator decided
        # which diagrams to write (selector.get_external_callers_with_component compares
        # caller_component != current_component). The two must agree, because the loop
        # below pairs mmd_paths[idx] with external_callers[idx].
        #
        # This used to say "outside the selected components" whenever a scope was set,
        # and the two definitions disagree the moment ONE DOCUMENT SPANS SEVERAL
        # COMPONENTS -- `--scope "component:Alpha,Beta"`, or any group-level document.
        # A caller in a sibling component was external to the generator (so it wrote the
        # .mmd) but internal to the view, so external_callers came out empty, the loop
        # broke at idx 0, and no row was recorded. The symptom is a directory full of
        # .mmd/.png files beside a _behaviour_pngs.json holding {"_docxRows": {}}, and a
        # document with an empty Dynamic Behaviour section.
        external_callers = [c for c in called_by_ids
                            if c and "|" in c and c.split("|")[0] != component_name]

        for idx, mmd_path in enumerate(mmd_paths):
            if idx >= len(external_callers):
                break
            caller_fid = external_callers[idx]
            parts = (caller_fid or "").split(KEY_SEP)
            if len(parts) < 3:
                continue
            qualified = parts[2]
            external_func = qualified.split("::")[-1] if "::" in qualified else qualified
            external_unit_external_function = f"{parts[1]} - {external_func}"
            fid_parts = (fid or "").split(KEY_SEP)
            func_qualified = fid_parts[2] if len(fid_parts) >= 3 else ""
            current_function_name = func_qualified.split("::")[-1] if "::" in func_qualified else func_qualified

            png_path = None
            if render_png and os.path.isfile(mmd_path):
                png_base = os.path.splitext(os.path.basename(mmd_path))[0]
                png = os.path.join(out_dir, f"{png_base}.png")
                # This is where --selected-unit saves the time: mmdc costs seconds per
                # diagram. Skip it ONLY when there is an existing PNG to reuse -- the point
                # is to avoid RE-rendering what is already on disk, not to ship a document
                # with an empty picture slot. On a first run nothing exists to reuse, so
                # everything renders and the document is complete; on the next --unit run
                # the named unit re-renders and the rest are reused, which is the case the
                # flag exists for.
                _unit = (fid_to_unit.get(fid) or "")
                _short = _unit.split(KEY_SEP, 1)[1].lower() if KEY_SEP in _unit else ""
                _reuse = (allowed_units and _short not in allowed_units
                          and os.path.isfile(png))
                if _reuse:
                    png_path = png
                else:
                    run_cmd = run_cmd_base + ["-i", mmd_path, "-o", png, "-s", "2"]
                    try:
                        if os_type == "Windows":
                            r2 = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60, check=False, shell=True)
                        else:
                            r2 = subprocess.run(run_cmd, capture_output=True, text=True, timeout=60, check=False)
                        if r2.returncode == 0 and os.path.isfile(png):
                            png_path = png
                        elif r2.returncode != 0 and idx == 0:
                            msg = (r2.stderr or r2.stdout or f"exit {r2.returncode}").strip()
                            log("mmdc failed: %s" % msg, component="behaviourDiagram", err=True)
                    except FileNotFoundError:
                        if idx == 0:
                            log("mmdc not found. Run: npm install", component="behaviourDiagram", err=True)
                    except subprocess.TimeoutExpired:
                        if idx == 0:
                            log("mmdc timed out", component="behaviourDiagram", err=True)

            rowed_mmd.add(os.path.basename(mmd_path))
            docx_rows.setdefault(component_name, {}).setdefault(current_unit, []).append({
                "currentFunctionName": current_function_name,
                # fid identifies the function exactly; the exporter used to re-find it by
                # short name within the unit, which picks the wrong one when a unit has two
                # same-named methods (AddOperation::apply / MultiplyOperation::apply).
                "currentFunctionId": fid,
                "currentFunctionDisplay": scoped_name(
                    func_qualified, (functions_data.get(fid) or {}).get("className", "")
                ),
                "externalUnitFunction": external_unit_external_function,
                "pngPath": png_path,
                "behaviorDescription": behaviour_descriptions[idx] if idx < len(behaviour_descriptions) else [],
            })
            count += 1

    out_path = os.path.join(out_dir, "_behaviour_pngs.json")
    # A straight write, because docx_rows is now COMPLETE for this component: every
    # function was evaluated, whether or not --unit named its owner. The merge this used
    # to need existed only to stop a narrowed run deleting the other units' rows, and a
    # narrowed run no longer produces a partial set. Rebuilding the whole manifest each
    # time is also what removes a stale row whose diagram has since gone.
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"_docxRows": docx_rows}, f, indent=2)

    # A .mmd with no ROW is invisible damage: the exporter places a behaviour subsection
    # only from this manifest, so the document gets an empty "Dynamic Behaviour" heading
    # while the directory looks healthy. Keyed on the .mmd files this run actually
    # recorded, NOT on whether a PNG exists -- a row whose image was skipped by --unit is
    # still a row, and reporting it as an orphan sent exactly the wrong message.
    orphans = []
    if os.path.isdir(out_dir):
        for f in sorted(os.listdir(out_dir)):
            if f.endswith(".mmd") and f not in rowed_mmd:
                orphans.append(f)
    if orphans:
        log("%d behaviour diagram file(s) here have no entry in _behaviour_pngs.json, so "
            "they will NOT appear in the document:" % len(orphans),
            component="behaviourDiagram", err=True)
        for f in orphans[:5]:
            log("    %s" % f, component="behaviourDiagram", err=True)
        if len(orphans) > 5:
            log("    ... and %d more" % (len(orphans) - 5), component="behaviourDiagram", err=True)
        log("  They are left over from an earlier run and no function in this model "
            "produces them any more.", component="behaviourDiagram", err=True)

    progress.done(summary="output/behaviour_diagrams/ (%d diagrams)" % count)
