"""Flowcharts view.

Invokes flowchart_engine.py (src/flowchart/flowchart_engine.py) to produce
per-unit JSON files containing function names and Mermaid flowchart strings.
When renderPng is true, renders each flowchart to PNG.

The engine reads:
  - model/functions.json       (from parser.py)
  - model/metadata.json        (from parser.py)
  - model/knowledge_base.json  (from model_deriver.py, optional but recommended)

The -I include path is derived from metadata.json basePath when not set in config.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from .registry import register
from utils import KEY_SEP, log, mmdc_path, safe_filename, os_type


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
            shutil.copyfile(os.path.join(base_fc, fn), os.path.join(out_dir, fn))
            if fn.endswith(".json"):
                carried += 1
    log(f"incremental: carried forward {carried} baseline flowchart file(s) (+PNGs)", "flowcharts")
    return carried


def _prune_orphan_flowcharts(out_dir, valid_stems):
    """Move/rename cleanup (M3.x): drop carried flowchart artifacts for source-file stems
    no longer present in the current model (a deleted or RENAMED file), so the version's
    output carries no stale units. JSON files are `<stem>.json`; PNGs `<stem>_<func>.png`.
    Skips pruning when `valid_stems` is empty (avoids nuking everything on a load glitch)."""
    valid = set(valid_stems)
    if not valid:
        return 0
    try:
        names = os.listdir(out_dir)
    except OSError:
        return 0
    orphan = {fn[:-5] for fn in names
              if fn.endswith(".json") and fn != "_summary.json" and fn[:-5] not in valid}
    if not orphan:
        return 0
    removed = 0
    for fn in names:
        if fn == "_summary.json":
            continue
        is_orphan = ((fn.endswith(".json") and fn[:-5] in orphan)
                     or (fn.endswith(".png") and any(fn.startswith(s + "_") for s in orphan)))
        if is_orphan:
            try:
                os.unlink(os.path.join(out_dir, fn))
                removed += 1
            except OSError:
                pass
    log(f"incremental: pruned {removed} orphan flowchart artifact(s) for {len(orphan)} "
        f"removed/renamed unit(s): {sorted(orphan)}", "flowcharts")
    return removed


def _apply_incremental_plan(functions_arg_path, model_dir_abs, out_dir):
    """Incremental flowchart reuse. If model/incremental_plan.json exists:

      * FUNCTION-LEVEL (M3.6, plan has `flowchartFids`): restrict the engine to the
        DIRECTLY changed/new functions only, carry forward ALL baseline flowchart
        JSONs+PNGs, and (after the engine runs) splice each fresh per-function flowchart
        into the baseline file JSON — keeping unchanged functions, replacing changed
        ones, dropping deleted ones. Only the changed functions' PNGs are re-rendered.
      * FILE-LEVEL (older plan, only `flowchartFiles`): restrict to whole changed files.

    Absent/unreadable plan -> full behaviour. Returns (functions_file, inc): `inc` is
    None (no plan) or a dict consumed by run() to merge + decide which PNGs to render."""
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
            log("incremental: baseline flowcharts missing - full flowchart regen", "flowcharts")
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

        # Engine regenerates ONLY the directly changed/new functions in this scope.
        sel = [fid for fid in fids if fid in funcs]
        restricted = {fid: funcs[fid] for fid in sel}
        fresh_pairs = {(_stem(fid), funcs[fid].get("qualifiedName")) for fid in sel}

        # Units whose JSON must be rebuilt = files of changed/new/deleted functions
        # (flowchartFiles) that exist in this scope. A deletion-only file has no fresh
        # entry but still needs its deleted function spliced OUT.
        plan_files = plan.get("flowchartFiles") or []
        changed_units = {os.path.splitext(os.path.basename(f))[0] for f in plan_files} & set(scope_units)
        # also cover changed/new fids whose file somehow isn't in flowchartFiles
        changed_units |= {p[0] for p in fresh_pairs if p[0]}
        current_by_unit = {u: scope_units.get(u, set()) for u in changed_units}

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(restricted, f, indent=2)
        log(f"incremental: flowcharts (function-level) restricted to {len(restricted)} "
            f"changed function(s); {len(changed_units)} file JSON(s) to rebuild", "flowcharts")
        return out_path, {"mode": "function", "base_fc": base_fc,
                          "changed_units": changed_units, "current_by_unit": current_by_unit,
                          "fresh_pairs": fresh_pairs}

    # FILE-LEVEL fallback (plan predates flowchartFids).
    if base_fc:
        _carry_forward_flowcharts(base_fc, out_dir)
        _prune_orphan_flowcharts(  # move/rename cleanup
            out_dir, {_stem(fid) for fid in funcs if _stem(fid)})
    impacted = set(plan.get("flowchartFiles") or plan.get("impactedFiles") or [])
    impacted_units = {os.path.splitext(os.path.basename(f))[0] for f in impacted}
    restricted = {fid: info for fid, info in funcs.items()
                  if (info.get("location") or {}).get("file") in impacted}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(restricted, f, indent=2)
    log(f"incremental: flowcharts (file-level) restricted to {len(restricted)} function(s) "
        f"in {len(impacted)} impacted file(s)", "flowcharts")
    return out_path, {"mode": "file", "impacted_units": impacted_units}


def _merge_incremental_flowcharts(inc, out_dir):
    """FUNCTION-LEVEL splice (M3.6): the engine wrote fresh JSONs containing ONLY the
    changed functions of each changed file. Rebuild each changed file's JSON from the
    baseline (all functions) with the changed entries replaced, deleted entries dropped
    and new entries appended. Join key = entry 'name' (== functions.json qualifiedName)."""
    base_fc = inc.get("base_fc")

    def _by_name(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                arr = json.load(f)
            return {e.get("name"): e for e in arr if isinstance(e, dict) and e.get("name")}
        except (OSError, json.JSONDecodeError):
            return {}

    spliced = 0
    for unit in sorted(inc.get("changed_units") or []):
        out_json = os.path.join(out_dir, unit + ".json")
        fresh = _by_name(out_json)                                   # engine output: changed only
        baseline = _by_name(os.path.join(base_fc, unit + ".json")) if base_fc else {}
        current = inc.get("current_by_unit", {}).get(unit) or set()

        merged, emitted = [], set()
        for name, entry in baseline.items():       # baseline order: replace changed, drop deleted
            if current and name not in current:
                continue
            merged.append(fresh.get(name, entry))
            emitted.add(name)
        for name, entry in fresh.items():          # new functions not in the baseline
            if name in emitted:
                continue
            if current and name not in current:    # a deleted fn still present in carried 'fresh'
                continue
            merged.append(entry)
            emitted.add(name)

        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        spliced += 1
    if spliced:
        log(f"incremental: spliced fresh flowcharts into {spliced} baseline file JSON(s)", "flowcharts")


def _resolve_layer_dirs(config, group_name, layer_paths):
    """Return the include dirs for the layer that owns group_name.

    When group_name is set, only the dirs from its layer are returned so the
    flowchart engine does not see headers from unrelated layers.  Falls back to
    all dirs across all layers when no group is selected or the group is not
    found in the config.
    """
    if group_name:
        layers_cfg = (config or {}).get("layers") or {}
        for layer_name, layer in layers_cfg.items():
            groups = layer.get("groups") or {}
            if group_name.lower() in {g.lower() for g in groups}:
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
        for ctrl, letter in (("\b", "b"), ("\f", "f"), ("\n", "n"), ("\r", "r"), ("\t", "t")):
            script_path = script_path.replace(ctrl, "/" + letter)
        log("scriptPath had unescaped backslashes in config.json; recovered to: %s" % script_path,
            component="flowcharts")
    return script_path if os.path.isabs(script_path) else os.path.join(project_root, script_path)


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
    # When model_dir is a layer subdir (model/Layer1/), dirname gives model/ not the
    # analyzer root.  Walk up one extra level in that case.
    _parent = os.path.dirname(model_dir_abs)
    project_root = os.path.dirname(_parent) if os.path.basename(_parent) == "model" else _parent

    # Out dir fixed in code: output/flowcharts under the view output dir
    out_dir = os.path.join(output_dir_abs, "flowcharts")
    os.makedirs(out_dir, exist_ok=True)

    functions_path = os.path.join(model_dir_abs, "functions.json")
    metadata_path = os.path.join(model_dir_abs, "metadata.json")
    allowed_components = {m.lower() for m in ((config or {}).get("_analyzerAllowedComponents") or [])}
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

    clang_paths_file = os.path.join(model_dir_abs, "clang_include_paths.json")
    if os.path.isfile(clang_paths_file):
        try:
            with open(clang_paths_file, "r", encoding="utf-8") as f:
                layer_paths = json.load(f) or {}
            for p in _resolve_layer_dirs(config, group_name, layer_paths):
                arg = f"-I{p}"
                if arg not in clang_args:
                    clang_args.append(arg)
        except (json.JSONDecodeError, OSError):
            pass

    clang_macros_file = os.path.join(model_dir_abs, "clang_macros.json")
    if os.path.isfile(clang_macros_file):
        try:
            with open(clang_macros_file, "r", encoding="utf-8") as f:
                macro_args = json.load(f) or []
            for arg in macro_args:
                if arg and arg not in clang_args:
                    clang_args.append(arg)
        except (json.JSONDecodeError, OSError):
            pass

    clang_extra_inc_file = os.path.join(model_dir_abs, "clang_extra_include_paths.json")
    if os.path.isfile(clang_extra_inc_file):
        try:
            with open(clang_extra_inc_file, "r", encoding="utf-8") as f:
                extra_inc_args = json.load(f) or []
            for arg in extra_inc_args:
                if arg and arg not in clang_args:
                    clang_args.append(arg)
        except (json.JSONDecodeError, OSError):
            pass

    script = _resolve_script(project_root, "fake_flowchart_generator.py")
    if not os.path.isfile(script):
        log("generator not found: %s" % script, component="flowcharts", err=True)
        return

    # If we are exporting a selected group/components, pass only those functions to the generator.
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
                    and fid.split(KEY_SEP, 1)[0].lower() in allowed_components
                }
                orig_comps = sorted((config or {}).get("_analyzerAllowedComponents") or [])
                filename_key = group_name or "_".join(orig_comps)
                group_functions_path = os.path.join(model_dir_abs, f"functions_{safe_filename(filename_key)}.json")
                with open(group_functions_path, "w", encoding="utf-8") as tf:
                    json.dump(filtered, tf, indent=2)
                functions_arg_path = group_functions_path
        except (OSError, json.JSONDecodeError):
            pass

    # Incremental (M2.4b/M3.1/M3.4/M3.6): restrict the engine to changed functions +
    # carry forward baseline JSONs/PNGs (function-level splice happens after the engine).
    functions_arg_path, inc = _apply_incremental_plan(functions_arg_path, model_dir_abs, out_dir)

    # knowledge_base.json (generated by model_deriver.py) — pass if it exists
    kb_path = os.path.join(model_dir_abs, "knowledge_base.json")

    # LLM config for flowchart engine
    llm_cfg = config.get("llm") or {}
    llm_base_url = (llm_cfg.get("baseUrl") or "http://localhost:11434").rstrip("/")
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
    # Many projects have hundreds of -I/-D clang args. Passing them all on the
    # command line blows the Windows cmd.exe 8192-char limit (WinError 206).
    # Write them to a response file and pass `@file` — flowchart_engine.py
    # enables argparse's fromfile_prefix_chars='@' to read args from it.
    non_empty_clang_args = [str(a) for a in clang_args if a]
    if non_empty_clang_args:
        args_file = os.path.join(model_dir_abs, ".flowcharts_clang_args.txt")
        with open(args_file, "w", encoding="utf-8") as f:
            for a in non_empty_clang_args:
                f.write(f"--clang-arg={a}\n")
        cmd.append(f"@{args_file}")

    log("flowcharts cmd: " + " ".join(shlex.quote(a) for a in cmd), component="flowcharts")
    try:
        if os_type == "Windows":
            r = subprocess.run(cmd, cwd=project_root, check=False, shell=True)
        else:
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

    # Incremental function-level (M3.6): splice the freshly generated per-function
    # flowcharts into the carried baseline file JSONs before rendering.
    if inc and inc.get("mode") == "function":
        _merge_incremental_flowcharts(inc, out_dir)

    # Always render flowcharts to PNG

    mmdc = mmdc_path(project_root)
    if not os.path.isfile(mmdc):
        try:
            if os_type == "Windows":
                subprocess.run([mmdc, "--help"], capture_output=True, timeout=5, cwd=project_root, shell=True)
            else:
                subprocess.run([mmdc, "--help"], capture_output=True, timeout=5, cwd=project_root)
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            log("mmdc not found. Run: npm install @mermaid-js/mermaid-cli", component="flowcharts", err=True)
            return

    puppeteer = os.path.join(project_root, "config", "puppeteer-config.json")
    run_cmd_base = [mmdc]
    if os.path.isfile(puppeteer):
        run_cmd_base.extend(["-p", puppeteer])

    # Incremental PNG reuse: file-level carries whole non-impacted units; function-level
    # carries every function except the directly changed ones (re-rendered below).
    inc_mode = inc.get("mode") if inc else None
    file_units = inc.get("impacted_units") if inc_mode == "file" else None
    fresh_pairs = inc.get("fresh_pairs") if inc_mode == "function" else None

    items = []
    for fname in sorted(os.listdir(out_dir)):
        if not fname.endswith(".json"):
            continue
        unit_name = fname[:-5]
        # File-level: skip re-rendering PNGs for non-impacted units (carried forward).
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
                # Function-level: re-render only the directly changed functions' PNGs.
                if fresh_pairs is not None and (unit_name, func_name) not in fresh_pairs:
                    continue
                items.append((unit_name, func_name, flowchart))
        except (json.JSONDecodeError, OSError):
            pass

    from core.progress import ProgressReporter
    from core.logging_setup import get_logger
    total = len(items)
    failed = 0
    progress = ProgressReporter("flowcharts:PNG", total=total, logger=get_logger("flowcharts"))
    progress.start()
    for i, (unit_name, func_name, flowchart) in enumerate(items, 1):
        progress.step(label=f"{unit_name}/{func_name}")
        png_name = f"{unit_name}_{safe_filename(func_name)}.png"
        png_path = os.path.abspath(os.path.join(out_dir, png_name))
        mmd_path = os.path.join(out_dir, f".tmp_{unit_name}_{safe_filename(func_name)}.mmd")
        try:
            with open(mmd_path, "w", encoding="utf-8") as tf:
                tf.write(flowchart)
            run_cmd = run_cmd_base + ["-i", os.path.abspath(mmd_path), "-o", png_path]
            if os_type == "Windows":
                r = subprocess.run(run_cmd, cwd=project_root, capture_output=True, text=True, timeout=180, check=False, shell=True)
            else:
                r = subprocess.run(run_cmd, cwd=project_root, capture_output=True, text=True, timeout=180, check=False)
            if r.returncode != 0:
                failed += 1
                log("mmdc failed for %s/%s: %s" % (unit_name, func_name, (r.stderr or r.stdout or "exit " + str(r.returncode))[:200]), component="flowcharts", err=True)
        except (subprocess.TimeoutExpired, OSError) as e:
            failed += 1
            log("mmdc error for %s/%s: %s" % (unit_name, func_name, e), component="flowcharts", err=True)
        except Exception as e:
            failed += 1
            log("flowchart error for %s/%s: %s" % (unit_name, func_name, e), component="flowcharts", err=True)
        finally:
            try:
                if os.path.isfile(mmd_path):
                    os.unlink(mmd_path)
            except OSError:
                pass
    progress.done(summary=("%d PNGs rendered%s" % (total, (" (%d failed)" % failed) if failed else "")) if total else None)

