"""ADD view builders: model -> output. Each view reads the full model (no group filtering)."""
from utils import timed

from .registry import ADD_VIEW_REGISTRY


def run_add_views(model, output_dir, model_dir, config):
    """Run all enabled ADD views. model = {functions, globalVariables, units, modules, dataDictionary}."""
    add_cfg = (config or {}).get("architectureDoc", {}).get("views", {})
    for view_name, run_fn in ADD_VIEW_REGISTRY.items():
        val = add_cfg.get(view_name)
        enabled = val is not False
        if enabled:
            with timed(view_name):
                run_fn(model, output_dir, model_dir, config)


from . import layer_static_diagram  # noqa: F401
