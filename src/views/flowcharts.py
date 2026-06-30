import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys

from .registry import register
from utils import KEY_SEP, log, mmdc_path, safe_filename, os_type, render_mermaid_cached


# PNG slicing thresholds: split a flowchart PNG across Word pages when it is too tall to
# embed at _SLICE_EMBED_WIDTH_IN without shrinking it illegibly.
_SLICE_EMBED_WIDTH_IN = 4.0
_SLICE_USABLE_HEIGHT_IN = 7.5
_SLICE_MAX_ASPECT        = _SLICE_USABLE_HEIGHT_IN / _SLICE_EMBED_WIDTH_IN # ~1.875
_SLICE_THRESHOLD_FACTOR  = 1.15
_SLICE_WIDE_LIMIT        = 1.50
_SLICE_WHITE_CUTOFF      = 250
_SLICE_WINDOW_PRIMARY    = 0.15
_SLICE_WINDOW_FALLBACK   = 0.20
_SLICE_MIN_TAIL_FRACTION = 0.20


def _baseline_flowchart_dir(plan, model_dir_abs, out_dir):
    """Locate the baseline version's flowchart dir mirroring this out_dir, or None."""
    base_ver_dir = plan.get("baselineVersionDir")
    if not base_ver_dir:
        return None

    project_root = os.path.dirname(model_dir_abs)
    rel = os.path.relpath(out_dir, os.path.join(project_root, "output"))
    cand = os.path.join(base_ver_dir, "output", rel)
    return cand if os.path.isdir(cand) else None


def _carry_forward_flowcharts(base_fc, out_dir):
    """Copy every baseline flowchart JSON + PNG into out_dir (engine then overwrites
    the changed files' JSONs; the merge restores unchanged functions). Returns count."""
    carried = 0

    for fn in os.listdir(base_fc):
        if fn == "_summary.json":
            continue

        if fn.endswith(".json") or fn.endswith(".png"):
            shutil.copyfile(
                os.path.join(base_fc, fn),
                os.path.join(out_dir, fn)
            )

            if fn.endswith(".json"):
                carried += 1

    log(
        f"incremental: carried forward {carried} baseline flowchart file(s) (+PNGs)",
        "flowcharts"
    )
    return carried


def _prune_orphan_flowcharts(out_dir, valid_stems):
    """Move/rename cleanup (M3.x): drop carried flowchart artifacts for source-file stems
    no longer present in the current model (a deleted or RENAMED file), so the version's
    output carries no stale units. JSON files are <stem>.json; PNGs <stem>_<func>.png.
    Skips pruning when `valid_stems` is empty (avoids nuking everything on a load glitch)."""

    valid = set(valid_stems)
    if not valid:
        return 0

    try:
        names = os.listdir(out_dir)
    except OSError:
        return 0

    orphan = [
        fn[:-5]
        for fn in names
        if fn.endswith(".json")
        and fn != "_summary.json"
        and fn[:-5] not in valid
    ]

    if not orphan:
        return 0

    removed = 0

    for fn in names:
        if fn == "_summary.json":
            continue

        is_orphan = (
            (fn.endswith(".json") and fn[:-5] in orphan)
            or (
                fn.endswith(".png")
                and any(fn.startswith(s + "_") for s in orphan)
            )
        )

        if is_orphan:
            try:
                os.unlink(os.path.join(out_dir, fn))
                removed += 1
            except OSError:
                pass

    log(
        f"incremental: pruned {removed} orphan flowchart artifact(s) for {len(orphan)} "
        f"removed/renamed unit(s): {sorted(orphan)}",
        "flowcharts"
    )

    return removed


def _source_unit_flowchart(version_dir, unit):
    """M3.7b: return (flowcharts_dir, {name: entry}) for unit's flowchart JSON anywhere
    under a version's output (handles scoped output/<scope>/flowcharts/), or (None, {})."""

    out_root = os.path.join(version_dir, "output")

    if not os.path.isdir(out_root):
        return None, {}

    for r, d, _f in os.walk(out_root):
        if os.path.basename(r) == "flowcharts":
            p = os.path.join(r, unit + ".json")

            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        arr = json.load(fh)

                    return r, {
                        e.get("name"): e
                        for e in arr
                        if isinstance(e, dict) and e.get("name")
                    }

                except (OSError, json.JSONDecodeError):
                    return r, {}

    return None, {}


def _apply_incremental_plan(functions_arg_path, model_dir_abs, out_dir):
    """Incremental flowchart reuse. If model/incremental_plan.json exists:

    * FUNCTION-LEVEL (M3.6, plan has `flowchartFids`): restrict the engine to the
      DIRECTLY changed/new functions only, carry forward ALL baseline flowchart
      JSONs+PNGs, and (after the engine runs) splice each fresh per-function flowchart
      into the baseline file JSON - keeping unchanged functions, replacing changed
      ones, dropping deleted ones. Only the changed functions' PNGs are re-rendered.

    * FILE-LEVEL (older plan, only `flowchartFiles`): restrict to whole changed files.

    Absent/unreadable plan -> full behaviour. Returns (functions_file, inc); `inc` is
    None (no plan) or a dict consumed by run() to merge + decide which PNGs to render.
    """

    plan_path = os.path.join(model_dir_abs, "incremental_plan.json")

    if not os.path.isfile(plan_path):
        return functions_arg_path, None

    try:
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = json.load(f)

        with open(functions_arg_path, "r", encoding="utf-8") as f:
            funcs = json.load(f)

    except (OSError, json.JSONDecodeError):
        return functions_arg_path, None

    base_fc = _baseline_flowchart_dir(plan, model_dir_abs, out_dir)

    def _stem(fid):
        fpath = ((funcs.get(fid) or {}).get("location") or {}).get("file")
        return os.path.splitext(os.path.basename(fpath))[0] if fpath else None

    out_path = os.path.join(model_dir_abs, "functions_incremental.json")

    fids = plan.get("flowchartFids")

    if fids is not None:
        # FUNCTION-LEVEL. Reuse needs the baseline JSONs to splice into; if they're
        # unexpectedly missing, fall back to a full (correct, if slower) regeneration.
        if not base_fc:
            log(
                "incremental: baseline flowcharts missing - full flowchart regen",
                "flowcharts"
            )
            return functions_arg_path, None

        _carry_forward_flowcharts(base_fc, out_dir)

        # In-scope source-file stems -> their CURRENT functions (qualifiedName). Used by
        # the merge to drop deleted entries and keep file order.
        scope_units = {}

        for fid, info in funcs.items():
            stem, qn = _stem(fid), info.get("qualifiedName")
            if stem and qn:
                scope_units.setdefault(stem, set()).add(qn)

        # Move/rename cleanup: drop carried artifacts for files no longer in the model.
        _prune_orphan_flowcharts(out_dir, set(scope_units))

        # Engine regenerates the directly changed/new functions in this scope.
        sel = [fid for fid in fids if fid in funcs]

        # M3.7b - cross-version flowchart reuse...
        xver_plan = plan.get("crossVersionFlowcharts") or {}
        xver_by_unit = {}

        for fid, src_dir in xver_plan.items():
            info = funcs.get(fid)
            stem = _stem(fid)
            qn = info.get("qualifiedName") if info else None

            if not info or not stem or not qn:
                continue

            src_fc_dir, src_entries = _source_unit_flowchart(src_dir, stem)
            entry = src_entries.get(qn)

            if entry is None:
                sel.append(fid)      # source has no flowchart -> regenerate
                continue

            xver_by_unit.setdefault(stem, {})[qn] = entry

            png = f"{stem}_{safe_filename(qn)}.png"
            srcpng = os.path.join(src_fc_dir, png) if src_fc_dir else ""

            if srcpng and os.path.isfile(srcpng):
                shutil.copyfile(srcpng, os.path.join(out_dir, png))

        restricted = {fid: funcs[fid] for fid in sel}
        fresh_pairs = {
            (_stem(fid), funcs[fid].get("qualifiedName"))
            for fid in sel
        }

        # Units whose JSON must be rebuilt...
        plan_files = plan.get("flowchartFiles") or []

        changed_units = {
            os.path.splitext(os.path.basename(f))[0]
            for f in plan_files
        } & set(scope_units)

        changed_units |= {p[0] for p in fresh_pairs if p[0]}
        changed_units |= set(xver_by_unit)

        current_by_unit = {
            u: scope_units.get(u, set())
            for u in changed_units
        }

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(restricted, f, indent=2)

        log(
            f"incremental: flowcharts (function-level) restricted to {len(restricted)} changed "
            f"function(s); {len(xver_by_unit)} unit(s) get cross-version splices; "
            f"{len(changed_units)} file JSON(s) to rebuild",
            "flowcharts"
        )

        return out_path, {
            "mode": "function",
            "base_fc": base_fc,
            "changed_units": changed_units,
            "current_by_unit": current_by_unit,
            "fresh_pairs": fresh_pairs,
            "xver_by_unit": xver_by_unit,
        }

    # FILE-LEVEL fallback (plan predates flowchartFids).
    if base_fc:
        _carry_forward_flowcharts(base_fc, out_dir)

        _prune_orphan_flowcharts(
            out_dir,
            [_stem(fid) for fid in funcs if _stem(fid)]
        )

    impacted = set(
        plan.get("flowchartFiles")
        or plan.get("impactedFiles")
        or []
    )

    impacted_units = [
        os.path.splitext(os.path.basename(f))[0]
        for f in impacted
    ]

    restricted = {
        fid: info
        for fid, info in funcs.items()
        if (info.get("location") or {}).get("file") in impacted
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(restricted, f, indent=2)

    log(
        f"incremental: flowcharts (file-level) restricted to {len(restricted)} function(s) "
        f"in {len(impacted)} impacted file(s)",
        "flowcharts"
    )

    return out_path, {
        "mode": "file",
        "impacted_units": impacted_units
    }

def _merge_incremental_flowcharts(inc, out_dir):
    """FUNCTION-LEVEL splice (M3.6 + M3.7b): rebuild each changed file's JSON from THREE
    sources, per current function (join key = entry 'name' == functions.json qualifiedName):
      * FRESH    - the engine's per-function output (directly changed/new functions);
      * X-VER    - a flowchart spliced from a prior version (M3.7b, a reused revert);
      * BASELINE - everything else (unchanged functions), in baseline file order.
    Deleted functions (not in the current set) are dropped; new ones appended."""
    base_fc = inc.get("base_fc")


    def _by_name(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)

            return {
                e.get("name"): e
                for e in arr
                if isinstance(e, dict) and e.get("name")
            }

        except (OSError, json.JSONDecodeError):
            return {}


    spliced = 0

    for unit in sorted(inc.get("changed_units") or []):
        out_json = os.path.join(out_dir, unit + ".json")

        fresh = _by_name(out_json)  # engine output: changed only

        baseline = (
            _by_name(os.path.join(base_fc, unit + ".json"))
            if base_fc
            else {}
        )

        xver = inc.get("xver_by_unit", {}).get(unit) or {}  # cross-version entries (M3.7b)

        current = inc.get("current_by_unit", {}).get(unit) or set()

        merged, emitted = [], set()

        # baseline order: replace changed, drop deleted
        for name, entry in baseline.items():
            if current and name not in current:
                continue

            merged.append(
                fresh.get(name)
                or xver.get(name)
                or entry
            )  # fresh > x-ver > baseline

            emitted.add(name)

        # functions new to the baseline
        for src in (fresh, xver):
            for name, entry in src.items():
                if name in emitted:
                    continue

                # a deleted fn still present in carried 'fresh'
                if current and name not in current:
                    continue

                merged.append(entry)
                emitted.add(name)

        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)

        spliced += 1

    if spliced:
        log(
            f"incremental: spliced fresh flowcharts into {spliced} baseline file JSON(s)",
            "flowcharts",
        )


def _cleanup_stale_slice_parts(png_path: str) -> None:
    """
    Remove any {stem}_part_*_of_*.png siblings so state is
    consistent before (re-)slicing.
    """

    out_dir = os.path.dirname(png_path)
    stem = os.path.splitext(os.path.basename(png_path))[0]

    pattern = re.compile(
        r"^" + re.escape(stem) + r"_part_\d+_of_\d+\.png$",
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
    """
    Given an array of white-row Y indices, pick N-1 cut points
    targeting evenly spaced boundaries.

    Falls back to the exact target Y if no white row is within
    +/-20% of H.

    Returns a sorted list of ints.
    """

    import numpy as np

    primary = int(H * _SLICE_WINDOW_PRIMARY)
    fallback = int(H * _SLICE_WINDOW_FALLBACK)

    slice_h = H / N
    cuts = []

    for k in range(1, N):
        target = int(k * slice_h)
        chosen = target

        if len(white_ys):
            mask = (
                (white_ys >= target - primary)
                & (white_ys <= target + primary)
            )

            cands = white_ys[mask]

            if not len(cands):
                mask = (
                    (white_ys >= target - fallback)
                    & (white_ys <= target + fallback)
                )

                cands = white_ys[mask]

            if len(cands):
                idx = int(
                    np.argmin(
                        np.abs(
                            cands.astype(np.int64) - target
                        )
                    )
                )

                chosen = int(cands[idx])

        cuts.append(chosen)

    return sorted(set(cuts))


def _maybe_slice_tall_png(png_path: str) -> int:
    """
    If png_path's aspect would overflow one Word page at 4"
    wide, split it horizontally at whitespace bands and write
    {stem}_part_K_of_N.png siblings.

    The original PNG is removed when slicing happens so the
    state is either "single original" OR "N parts" - never both.

    Slicing is best-effort: any error keeps the original intact
    and returns 1.

    Returns the number of parts produced
    (1 means no slice happened).
    """

    try:
        import numpy as np
        from PIL import Image

    except ImportError as exc:
        log(
            "slice: PIL/numpy unavailable, skipping slice (%s)" % exc,
            component="flowcharts",
        )
        return 1

    try:
        img = Image.open(png_path)
        img.load()

    except Exception as exc:
        log(
            "slice: cannot open %s: %s" % (png_path, exc),
            component="flowcharts",
        )
        return 1

    try:
        rgb = img.convert("RGB")

    except Exception as exc:
        log(
            "slice: convert RGB failed for %s: %s"
            % (png_path, exc),
            component="flowcharts",
        )

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

    # Always scrub stale parts first
    _cleanup_stale_slice_parts(png_path)

    name = os.path.basename(png_path)

    threshold = (
        _SLICE_MAX_ASPECT
        * _SLICE_THRESHOLD_FACTOR
    )

    # Width-bottleneck
    if W / H > _SLICE_WIDE_LIMIT:
        log(
            (
                "slice: %s W=%d H=%d aspect=%.2f "
                "W/H=%.2f -> skipped "
                "(wide layout, threshold W/H>%.2f)"
            )
            % (
                name,
                W,
                H,
                H / W,
                W / H,
                _SLICE_WIDE_LIMIT,
            ),
            component="flowcharts",
        )

        return 1

    aspect = H / W

    if aspect <= threshold:
        log(
            (
                "slice: %s W=%d H=%d aspect=%.2f "
                "-> not sliced (fits, threshold=%.2f)"
            )
            % (
                name,
                W,
                H,
                aspect,
                threshold,
            ),
            component="flowcharts",
        )

        return 1

    N = max(
        2,
        int(math.ceil(aspect / _SLICE_MAX_ASPECT)),
    )

    # Find rows that are entirely near-white
    arr = np.asarray(rgb, dtype=np.uint8)
    row_min = arr.min(axis=(1, 2))
    white_ys = np.nonzero(
        row_min > _SLICE_WHITE_CUTOFF
    )[0]

    cut_ys = _pick_cut_ys(white_ys, H, N)

    boundaries = [0] + cut_ys + [H]

    # Merge a too-small tail slice
    target_slice_h = H / N

    if len(boundaries) >= 3:
        tail_h = boundaries[-1] - boundaries[-2]

        if (
            tail_h
            < _SLICE_MIN_TAIL_FRACTION
            * target_slice_h
        ):
            boundaries = (
                boundaries[:-2]
                + [boundaries[-1]]
            )

    n_parts = len(boundaries) - 1

    if n_parts < 2:
        return 1

    stem, ext = os.path.splitext(png_path)

    written = []

    try:
        for i in range(n_parts):
            y0, y1 = boundaries[i], boundaries[i + 1]

            crop = rgb.crop((0, y0, W, y1))

            out_path = (
                f"{stem}_part_{i + 1}_of_{n_parts}{ext}"
            )

            crop.save(out_path)
            written.append(out_path)

    except Exception as exc:
        log(
            (
                "slice: write failed for %s: %s "
                "- keeping original"
            )
            % (png_path, exc),
            component="flowcharts",
        )

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

    log(
        (
            "slice: %s W=%d H=%d aspect=%.2f "
            "-> sliced into %d parts "
            "(threshold=%.2f)"
        )
        % (
            name,
            W,
            H,
            aspect,
            n_parts,
            threshold,
        ),
        component="flowcharts",
    )

    return n_parts

def _resolve_layer_dirs(config, group_name, layer_paths):
    """
    Return the include dirs for the layer that owns group_name.

    When group_name is set, only the dirs from its layer are returned so the
    flowchart engine does not see headers from unrelated layers. Falls back to
    all dirs across all layers when no group is selected or the group is not
    found in the config.
    """
    if group_name:
        layers_cfg = (config or {}).get("layers") or {}
        for layer_name, layer in layers_cfg.items():
            groups = layer.get("groups") or {}
            if group_name.lower() in [g.lower() for g in groups]:
                return layer_paths.get(layer_name) or []

    all_dirs: list = []
    seen: set = set()

    for dirs in layer_paths.values():
        for d in dirs:
            if d not in seen:
                seen.add(d)
                all_dirs.append(d)

    return all_dirs


def _resolve_script(project_root: str, script_path: str) -> str:
    if not script_path:
        return os.path.join(project_root, "fake_flowchart_generator.py")

    # Recover from unescaped backslashes in config.json: JSON parses "src\flowchart"
    # as src + FF (0x0C) + lowchart, because \f/\b/\n/\r/\t are JSON escape sequences.
    # Reverse that so Windows paths written with single backslashes still work.
    if any(c in script_path for c in "\b\f\n\r\t"):
        for ctrl, letter in (
            ("\b", "b"),
            ("\f", "f"),
            ("\n", "n"),
            ("\r", "r"),
            ("\t", "t"),
        ):
            script_path = script_path.replace(ctrl, "/" + letter)

        log(
            "scriptPath had unescaped backslashes in config.json; recovered to: %s"
            % script_path,
            component="flowcharts",
        )

    return (
        script_path
        if os.path.isabs(script_path)
        else os.path.join(project_root, script_path)
    )


@register("flowcharts")
def run(model, output_dir, model_dir, config):
    views_cfg = config.get("views", {})
    val = views_cfg.get("flowcharts")

    if val is None or val is False:
        # Not enabled
        return

    # Be robust to callers passing relative output_dir/model_dir.
    output_dir_abs = os.path.abspath(output_dir)
    model_dir_abs = os.path.abspath(model_dir)

    # When model_dir is a layer subdir (model/Layer1/), dirname gives model/
    # not the analyzer root. Walk up one extra level in that case.
    _parent = os.path.dirname(model_dir_abs)
    project_root = (
        os.path.dirname(_parent)
        if os.path.basename(_parent) == "model"
        else _parent
    )

    # Out dir fixed in code: output/flowcharts under the view output dir
    out_dir = os.path.join(output_dir_abs, "flowcharts")
    os.makedirs(out_dir, exist_ok=True)

    functions_path = os.path.join(model_dir_abs, "functions.json")
    metadata_path = os.path.join(model_dir_abs, "metadata.json")

    allowed_components = [
        m.lower()
        for m in ((config or {}).get("_analyzerAllowedComponents") or [])
    ]

    group_name = (config or {}).get("_analyzerSelectedGroup") or ""

    std = "c++14"  # fixed in code

    clang_cfg = config.get("clang") or {}
    clang_args = list(clang_cfg.get("clangArgs") or [])

    if not isinstance(clang_args, list):
        clang_args = [clang_args] if clang_args else []

    # Read base_path from metadata.json and layer-scoped include paths from
    # clang_include_paths.json (both written by run.py / Phase 1).
    if os.path.isfile(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            base_path = meta.get("basePath", "").strip()

            if base_path:
                base_i = f"-I{base_path}"
                if base_i not in clang_args:
                    clang_args.insert(0, base_i)

        except (json.JSONDecodeError, OSError):
            pass

    clang_paths_file = os.path.join(
        model_dir_abs,
        "clang_include_paths.json"
    )

    if os.path.isfile(clang_paths_file):
        try:
            with open(clang_paths_file, "r", encoding="utf-8") as f:
                layer_paths = json.load(f) or {}

            for p in _resolve_layer_dirs(
                config,
                group_name,
                layer_paths
            ):
                arg = f"-I{p}"

                if arg not in clang_args:
                    clang_args.append(arg)

        except (json.JSONDecodeError, OSError):
            pass

    clang_macros_file = os.path.join(
        model_dir_abs,
        "clang_macros.json"
    )

    if os.path.isfile(clang_macros_file):
        try:
            with open(clang_macros_file, "r", encoding="utf-8") as f:
                macro_args = json.load(f) or []

            for arg in macro_args:
                if arg and arg not in clang_args:
                    clang_args.append(arg)

        except (json.JSONDecodeError, OSError):
            pass

    clang_extra_inc_file = os.path.join(
        model_dir_abs,
        "clang_extra_include_paths.json"
    )

    if os.path.isfile(clang_extra_inc_file):
        try:
            with open(clang_extra_inc_file, "r", encoding="utf-8") as f:
                extra_inc_args = json.load(f) or []

            for arg in extra_inc_args:
                if arg and arg not in clang_args:
                    clang_args.append(arg)

        except (json.JSONDecodeError, OSError):
            pass

    script = _resolve_script(
        project_root,
        r"src\flowchart\flowchart_engine.py"
    )

    if not os.path.isfile(script):
        log(
            "generator not found: %s" % script,
            component="flowcharts",
            err=True,
        )
        return

    # If we are exporting a selected group/components,
    # pass only those functions to the generator.
    functions_arg_path = functions_path

    if allowed_components and os.path.isfile(functions_path):
        try:
            with open(functions_path, "r", encoding="utf-8") as f:
                all_funcs = json.load(f)

            if isinstance(all_funcs, dict):
                filtered = {
                    fid: info
                    for fid, info in all_funcs.items()
                    if isinstance(fid, str)
                    and KEY_SEP in fid
                    and fid.split(KEY_SEP, 1)[0].lower()
                    in allowed_components
                }

                orig_comps = sorted(
                    (config or {}).get("_analyzerAllowedComponents") or []
                )

                filename_key = (
                    group_name or "_".join(orig_comps)
                )

                group_functions_path = os.path.join(
                    model_dir_abs,
                    f"functions_{safe_filename(filename_key)}.json",
                )

                with open(
                    group_functions_path,
                    "w",
                    encoding="utf-8",
                ) as tf:
                    json.dump(filtered, tf, indent=2)

                functions_arg_path = group_functions_path

        except (OSError, json.JSONDecodeError):
            pass

    # Incremental (M2.4b/M3.1/M3.4/M3.6): restrict the engine to changed
    # functions + carry forward baseline JSONs/PNGs
    # (function-level splice happens after the engine).
    functions_arg_path, inc = _apply_incremental_plan(
        functions_arg_path,
        model_dir_abs,
        out_dir,
    )

    # knowledge_base.json (generated by model_deriver.py) - pass if it exists
    kb_path = os.path.join(
        model_dir_abs,
        "knowledge_base.json",
    )

    # LLM config for flowchart engine
    llm_cfg = config.get("llm") or {}

    llm_base_url = (
        llm_cfg.get("baseUrl")
        or "http://localhost:11434"
    ).rstrip("/")

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

    # M-D: when the analyzer disables LLM (--no-llm sets llm.descriptions=False),
    # tell the flowchart engine to skip the LLM too (fallback node labels)
    # for an LLM-free pipeline.
    if not llm_cfg.get("descriptions", True):
        cmd.append("--no-llm")

    # Many projects have hundreds of -I/-D clang args. Passing them all on the
    # command line blows the Windows cmd.exe 8192-char limit (WinError 206).
    # Write them to a response file and pass `@file` - flowchart_engine.py
    # enables argparse's fromfile_prefix_chars='@' to read args from it.
    non_empty_clang_args = [str(a) for a in clang_args if a]

    if non_empty_clang_args:
        args_file = os.path.join(model_dir_abs, ".flowcharts_clang_args.txt")

        with open(args_file, "w", encoding="utf-8") as f:
            for a in non_empty_clang_args:
                f.write(f"--clang-arg={a}\n")

        cmd.append(f"@{args_file}")

    log(
        "flowcharts cmd: " + " ".join(shlex.quote(a) for a in cmd),
        component="flowcharts",
    )

    try:
        if os_type == "Windows":
            r = subprocess.run(
                cmd,
                cwd=project_root,
                check=False,
                shell=True,
            )
        else:
            r = subprocess.run(
                cmd,
                cwd=project_root,
                check=False,
            )

    except subprocess.TimeoutExpired:
        log("generator timed out", component="flowcharts", err=True)
        return

    except OSError as e:
        log("generator failed: %s" % e, component="flowcharts", err=True)
        return

    if r.returncode != 0:
        log(
            "generator exited with code %s" % r.returncode,
            component="flowcharts",
            err=True,
        )
        return

    # Incremental function-level (M3.6): splice the freshly generated
    # per-function flowcharts into the carried baseline file JSONs before
    # rendering.
    if inc and inc.get("mode") == "function":
        _merge_incremental_flowcharts(inc, out_dir)

    # Always render flowcharts to PNG

    mmdc = mmdc_path(project_root)

    if not os.path.isfile(mmdc):
        try:
            if os_type == "Windows":
                subprocess.run(
                    [mmdc, "--help"],
                    capture_output=True,
                    timeout=5,
                    cwd=project_root,
                    shell=True,
                )
            else:
                subprocess.run(
                    [mmdc, "--help"],
                    capture_output=True,
                    timeout=5,
                    cwd=project_root,
                )

        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            log(
                "mmdc not found. Run: npm install @mermaid-js/mermaid-cli",
                component="flowcharts",
                err=True,
            )
            return

    puppeteer = os.path.join(
        project_root,
        "config",
        "puppeteer-config.json",
    )

    run_cmd_base = [mmdc]

    if os.path.isfile(puppeteer):
        run_cmd_base.extend(["-p", puppeteer])

    # Incremental PNG reuse: file-level carries whole non-impacted units;
    # function-level carries every function except the directly changed ones
    # (re-rendered below).
    inc_mode = inc.get("mode") if inc else None
    file_units = inc.get("impacted_units") if inc_mode == "file" else None
    fresh_pairs = inc.get("fresh_pairs") if inc_mode == "function" else None

    items = []

    for fname in sorted(os.listdir(out_dir)):
        if not fname.endswith(".json"):
            continue

        unit_name = fname[:-5]

        # File-level: skip re-rendering PNGs for non-impacted units
        # (carried forward).
        if file_units is not None and unit_name not in file_units:
            continue

        path = os.path.join(out_dir, fname)

        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)

            if not isinstance(arr, list):
                continue

            for item in arr:
                func_name = (item.get("name") or "").strip()
                flowchart = (item.get("flowchart") or "").strip()

                if not (func_name and flowchart):
                    continue

                # Function-level: re-render only the directly changed
                # functions' PNGs.
                if (
                    fresh_pairs is not None
                    and (unit_name, func_name) not in fresh_pairs
                ):
                    continue

                items.append((unit_name, func_name, flowchart))

        except (json.JSONDecodeError, OSError):
            pass

    from core.progress import ProgressReporter
    from core.logging_setup import get_logger

    total = len(items)
    failed = 0

    progress = ProgressReporter(
        "flowcharts:PNG",
        total=total,
        logger=get_logger("flowcharts"),
    )

    progress.start()

    for i, (unit_name, func_name, flowchart) in enumerate(items, 1):
        progress.step(label=f"{unit_name}/{func_name}")

        png_name = f"{unit_name}_{safe_filename(func_name)}.png"
        png_path = os.path.abspath(os.path.join(out_dir, png_name))

        try:
            # M-A: content-addressed cache -> an identical flowchart (e.g. carried across
            # a revert / shared between versions) skips mmdc entirely. scale=2 preserved;
            # the Windows/non-Windows subprocess handling + the temp .mmd are inside
            # utils._run_mmdc.
            if render_mermaid_cached(
                project_root, flowchart, png_path, scale=2, timeout=180
            ):
                if os.path.isfile(png_path):
                    # Split oversize flowcharts into per-page slices so Word
                    # doesn't clip them.
                    _maybe_slice_tall_png(png_path)

            else:
                failed += 1

                log(
                    "mmdc failed for %s/%s" % (unit_name, func_name),
                    component="flowcharts",
                    err=True,
                )

        except Exception as e:
            failed += 1

            log(
                "flowchart error for %s/%s: %s"
                % (unit_name, func_name, e),
                component="flowcharts",
                err=True,
            )

    progress.done(summary=("%d PNGs rendered%s" % (total, (" (%d failed)" % failed) if failed else "")) if total else None)
