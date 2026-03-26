"""View builders: model -> output. Each view reads the model and produces its output."""
from utils import timed

from .registry import VIEW_REGISTRY


def _selected_group_modules(config: dict) -> set:
    """Return allowed module names for selectedGroup; empty set means 'no filtering'."""
    groups = (config or {}).get("modulesGroups") or {}
    sel = (config or {}).get("selectedGroup") or (config or {}).get("modulesGroup")
    if not sel:
        return set()
    grp = groups.get(sel)
    if not isinstance(grp, dict):
        return set()
    return set(grp.keys())


def run_views(model, output_dir, model_dir, config):
    """Run all enabled views. model = {functions, globalVariables, units, modules, dataDictionary}."""
    allowed = _selected_group_modules(config or {})
    if allowed:
        # Expose allowed modules to view implementations.
        # Views should only OUTPUT the selected group's units/modules, but they must keep
        # full-model context to correctly label external cross-group interactions.
        config = dict(config or {})
        config["_analyzerAllowedModules"] = sorted(allowed)

    views_cfg = config.get("views", {})
    for view_name, run_fn in VIEW_REGISTRY.items():
        default = view_name == "interfaceTables"
        val = views_cfg.get(view_name)
        if view_name not in views_cfg:
            enabled = default
        else:
            enabled = False if val is False else True
        if enabled:
            with timed(view_name):
                run_fn(model, output_dir, model_dir, config)


# Import view modules so they register themselves
from . import interface_tables  # noqa: F401
from . import behaviour_diagram  # noqa: F401
from . import unit_diagrams  # noqa: F401
from . import flowcharts  # noqa: F401