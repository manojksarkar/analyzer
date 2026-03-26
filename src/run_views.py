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
    from utils import load_config
    from views import run_views

    # Optional CLI override:
    #   python src/run_views.py --output-dir output/group1
    output_dir = os.path.join(PROJECT_ROOT, "output")
    args = sys.argv[1:]
    if "--output-dir" in args:
        i = args.index("--output-dir")
        if i + 1 < len(args):
            output_dir = args[i + 1]
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    model = _load_model()
    config = load_config(PROJECT_ROOT)
    run_views(model, output_dir, MODEL_DIR, config)


if __name__ == "__main__":
    main()
