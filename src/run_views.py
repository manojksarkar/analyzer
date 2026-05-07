"""Load model from disk and run views. Phase 3: Generate views."""
import os
import sys
import json

from core.paths import paths as _paths

_p = _paths()
SCRIPT_DIR = _p.src_dir
PROJECT_ROOT = _p.project_root


def _load_model():
    from core.model_io import (
        load_model, FUNCTIONS, GLOBALS, UNITS, COMPONENTS, DATA_DICTIONARY, ModelFileMissing,
    )
    try:
        return load_model(
            FUNCTIONS, GLOBALS, UNITS, COMPONENTS,
            optional=[DATA_DICTIONARY],
        )
    except ModelFileMissing as e:
        print(f"Error: {e}. Run Phase 2 (model_deriver) first.")
        raise SystemExit(1)


def main():
    args = sys.argv[1:]

    # --layer LayerN: read model from model/LayerN/
    if "--layer" in args:
        i = args.index("--layer")
        if i + 1 < len(args):
            from core.model_io import set_model_dir, layer_model_dir
            set_model_dir(layer_model_dir(args[i + 1]))

    output_dir = os.path.join(PROJECT_ROOT, "output")
    if "--output-dir" in args:
        i = args.index("--output-dir")
        if i + 1 < len(args):
            output_dir = args[i + 1]
    selected_group = None
    if "--selected-group" in args:
        i = args.index("--selected-group")
        if i + 1 < len(args):
            selected_group = args[i + 1]
    filter_mode_override = None
    if "--filter-mode" in args:
        i = args.index("--filter-mode")
        if i + 1 < len(args):
            filter_mode_override = args[i + 1]
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    from core.config import app_config
    from views import run_views

    from core.model_io import _effective_model_dir
    model = _load_model()
    config = app_config()
    model_dir = _effective_model_dir()
    # Apply filter mode override from command line
    if filter_mode_override:
        if "views" not in config:
            config["views"] = {}
        if "sequenceDiagrams" not in config["views"]:
            config["views"]["sequenceDiagrams"] = {}
        config["views"]["sequenceDiagrams"]["filterMode"] = filter_mode_override
        print(f"[run_views] Using filter mode: {filter_mode_override}")
    if selected_group:
        from core.config import get_flat_groups
        groups = get_flat_groups(config)
        resolved = selected_group
        if isinstance(groups, dict) and selected_group not in groups:
            sk = selected_group.casefold()
            for k in groups.keys():
                if isinstance(k, str) and k.casefold() == sk:
                    resolved = k
                    break
        if resolved != selected_group:
            print(f"[run_views] --selected-group resolved to {resolved!r} (case-insensitive match)")
        grp = (groups.get(resolved) if isinstance(groups, dict) else None)
        if isinstance(grp, dict):
            config = dict(config)
            config["_analyzerSelectedGroup"] = resolved
            config["_analyzerAllowedComponents"] = sorted(grp.keys())
    run_views(model, output_dir, model_dir, config)


if __name__ == "__main__":
    main()
