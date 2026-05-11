"""Load model from disk and run SAD views. Phase 3 (SAD): Generate architecture views."""
import os
import sys

from core.paths import paths as _paths

_p = _paths()
SCRIPT_DIR = _p.src_dir
PROJECT_ROOT = _p.project_root
MODEL_DIR = _p.model_dir


def _load_model():
    from core.model_io import (
        load_merged_model, FUNCTIONS, GLOBALS, UNITS, COMPONENTS, DATA_DICTIONARY, ModelFileMissing,
    )
    try:
        return load_merged_model(
            FUNCTIONS, GLOBALS, UNITS, COMPONENTS,
            optional=[DATA_DICTIONARY],
        )
    except ModelFileMissing as e:
        print(f"Error: {e}. Run Phase 1+2 per layer first.")
        raise SystemExit(1)


def main():
    output_dir = os.path.join(PROJECT_ROOT, "output", "sad")
    args = sys.argv[1:]
    if "--output-dir" in args:
        i = args.index("--output-dir")
        if i + 1 < len(args):
            output_dir = args[i + 1]
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(PROJECT_ROOT, output_dir)
    os.makedirs(output_dir, exist_ok=True)

    from core.config import app_config
    from sad_views import run_sad_views

    model = _load_model()
    config = app_config()
    run_sad_views(model, output_dir, MODEL_DIR, config)


if __name__ == "__main__":
    main()
