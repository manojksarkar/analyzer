"""View builders: model -> output. Each view reads the model and produces its output."""
from utils import timed

from .registry import (
    VIEW_REGISTRY, DOC_TYPE_VIEWS, DOC_TYPE_SWE3, DOC_TYPE_ALL, DOC_TYPES,
)


def _doc_type_view_selection(doc_type):
    """Split a doc type into (forced_views, use_config_defaults).

    - forced_views: views that must run regardless of config gating (a doc
      type's explicit requirement, e.g. SWE.4 -> testSpecs).
    - use_config_defaults: whether to *also* run the config-enabled views
      (SWE.3's historical set). True for swe3/all, False for a doc type whose
      DOC_TYPE_VIEWS entry names an explicit set.
    """
    if doc_type == DOC_TYPE_ALL:
        forced = set()
        for dt in DOC_TYPES:
            v = DOC_TYPE_VIEWS.get(dt)
            if v:
                forced.update(v)
        return forced, True
    required = DOC_TYPE_VIEWS.get(doc_type)
    if required is None:
        return set(), True
    return set(required), False


def run_views(model, output_dir, model_dir, config, doc_type=DOC_TYPE_SWE3):
    """Run the views a doc type needs.

    model = {functions, globalVariables, units, components, dataDictionary}.
    For swe3 (and all) this is the config-enabled set (unchanged behaviour);
    doc types with an explicit DOC_TYPE_VIEWS entry run exactly those views,
    bypassing config gating.
    """
    views_cfg = (config or {}).get("views", {})
    forced_views, use_config_defaults = _doc_type_view_selection(doc_type)
    for view_name, run_fn in VIEW_REGISTRY.items():
        if view_name in forced_views:
            enabled = True
        elif not use_config_defaults:
            enabled = False
        else:
            default = view_name == "interfaceTables"
            val = views_cfg.get(view_name)
            if view_name not in views_cfg:
                enabled = default
            else:
                enabled = False if val is False else True
        if enabled:
            with timed(view_name):
                run_fn(model, output_dir, model_dir, config)


# Import view components so they register themselves
from . import interface_tables  # noqa: F401
from . import behaviour_diagram  # noqa: F401
from . import unit_diagrams  # noqa: F401
from . import flowcharts  # noqa: F401
from . import test_specs  # noqa: F401
