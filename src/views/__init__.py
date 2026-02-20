"""View builders: model -> output. Each view reads the model and produces its output."""
from .registry import VIEW_REGISTRY


def run_views(model, output_dir, model_dir, config):
    """Run all enabled views. model = {functions, globalVariables, units, modules, dataDictionary}."""
    views_cfg = config.get("views", {})
    for view_name, run_fn in VIEW_REGISTRY.items():
        default = view_name == "interfaceTables"
        val = views_cfg.get(view_name)
        if view_name not in views_cfg:
            enabled = default
        else:
            enabled = False if val is False else True
        if enabled:
            run_fn(model, output_dir, model_dir, config)


# Import view modules so they register themselves
from . import interface_tables  # noqa: F401
from . import behaviour_diagram  # noqa: F401
from . import unit_diagrams  # noqa: F401
from . import flowcharts  # noqa: F401