"""Load model from disk and run views. Phase 3: Generate views."""
import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
MODEL_DIR = os.path.join(PROJECT_ROOT, "model")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _load_model():
    """Load model from model/ directory."""
    required = ["functions.json", "globalVariables.json", "units.json", "modules.json"]
    for name in required:
        path = os.path.join(MODEL_DIR, name)
        if not os.path.exists(path):
            print(f"Error: {path} not found. Run Phase 2 (model_deriver) first.")
            raise SystemExit(1)

    model = {}
    with open(os.path.join(MODEL_DIR, "functions.json"), "r", encoding="utf-8") as f:
        model["functions"] = json.load(f)
    with open(os.path.join(MODEL_DIR, "globalVariables.json"), "r", encoding="utf-8") as f:
        model["globalVariables"] = json.load(f)
    with open(os.path.join(MODEL_DIR, "units.json"), "r", encoding="utf-8") as f:
        model["units"] = json.load(f)
    with open(os.path.join(MODEL_DIR, "modules.json"), "r", encoding="utf-8") as f:
        model["modules"] = json.load(f)

    dd_path = os.path.join(MODEL_DIR, "dataDictionary.json")
    model["dataDictionary"] = {}
    if os.path.exists(dd_path):
        with open(dd_path, "r", encoding="utf-8") as f:
            model["dataDictionary"] = json.load(f)

    return model


def main():
    from utils import load_config
    from views import run_views

    model = _load_model()
    config = load_config(PROJECT_ROOT)
    run_views(model, OUTPUT_DIR, MODEL_DIR, config)


if __name__ == "__main__":
    main()
