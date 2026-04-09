"""Load model from disk and run views. Phase 3: Generate views."""
import os
import sys
import json

from core.paths import paths as _paths

_p = _paths()
SCRIPT_DIR = _p.src_dir
PROJECT_ROOT = _p.project_root
MODEL_DIR = _p.model_dir


def _load_model():
    from core.model_io import (
        load_model, FUNCTIONS, GLOBALS, UNITS, MODULES, DATA_DICTIONARY, ModelFileMissing,
    )
    try:
        return load_model(
            FUNCTIONS, GLOBALS, UNITS, MODULES,
            optional=[DATA_DICTIONARY],
        )
    except ModelFileMissing as e:
        print(f"Error: {e}. Run Phase 2 (model_deriver) first.")
        raise SystemExit(1)


def main():
    # Optional CLI override:
    #   python src/run_views.py --output-dir output/group1
    #   python src/run_views.py --selected-group tests
    output_dir = os.path.join(PROJECT_ROOT, "output")
    args = sys.argv[1:]
    if "--output-dir" in args:
        i = args.index("--output-dir")
        if i + 1 < len(args):
            output_dir = args[i + 1]
    selected_group = None
    if "--selected-group" in args:
        i = args.index("--selected-group")
        if i + 1 < len(args):
            selected_group = args[i + 1]
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    from core.config import app_config
    from views import run_views

    model = _load_model()
    config = app_config()
    if selected_group:
        groups = (config.get("modulesGroups") or {})
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
            config["_analyzerAllowedModules"] = sorted(grp.keys())
    run_views(model, output_dir, MODEL_DIR, config)


if __name__ == "__main__":
    main()
