"""Load model from disk and run views. Phase 3: Generate views."""
import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")


def _load_model():
    required = ["functions", "globalVariables", "units", "modules"]
    model = {}
    for key in required:
        path = os.path.join(MODEL_DIR, f"{key}.json")
        if not os.path.isfile(path):
            print(f"Error: {path} not found. Run Phase 2 (model_deriver) first.")
            raise SystemExit(1)
        with open(path, "r", encoding="utf-8") as f:
            model[key] = json.load(f)
    dd_path = os.path.join(MODEL_DIR, "dataDictionary.json")
    if os.path.isfile(dd_path):
        with open(dd_path, "r", encoding="utf-8") as f:
            model["dataDictionary"] = json.load(f)
    else:
        model["dataDictionary"] = {}
    return model


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

    from utils import load_config
    from views import run_views

    model = _load_model()
    config = load_config(PROJECT_ROOT)
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
            config["_analyzerAllowedModules"] = sorted(grp.keys())
    run_views(model, output_dir, MODEL_DIR, config)


if __name__ == "__main__":
    main()
