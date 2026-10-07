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


def views_to_run(doc_type, config):
    """The views a doc type needs, in registry order -- the ones `run_views` runs.

    For swe3 (and all) this is the config-enabled set (unchanged behaviour);
    doc types with an explicit DOC_TYPE_VIEWS entry run exactly those views,
    bypassing config gating. Split out of `run_views` so the export guard's record
    can say which document each view was built for, by the same rule
    (`run_views._record_derivation`).
    """
    views_cfg = (config or {}).get("views", {})
    forced_views, use_config_defaults = _doc_type_view_selection(doc_type)
    selected = []
    for view_name in VIEW_REGISTRY:
        if view_name in forced_views:
            enabled = True
        elif not use_config_defaults:
            enabled = False
        else:
            # Both are mandatory document CONTENT, not optional extras -- and the
            # default has to hold for a workspace config written before this view
            # existed, which has no `views.unitHeaders` key at all.
            default = view_name in ("interfaceTables", "unitHeaders")
            val = views_cfg.get(view_name)
            if view_name not in views_cfg:
                enabled = default
            else:
                enabled = False if val is False else True
        if enabled:
            selected.append(view_name)
    return selected


def run_views(model, output_dir, model_dir, config, doc_type=DOC_TYPE_SWE3, only=None):
    """Run the views a doc type needs (`views_to_run`) -- of them, only those named in `only`
    when given: an update's Phase 3, which re-derives the views a rewrite changed and keeps the
    stored rest (FAST_WORD_FILE_UPDATES P5).

    model = {functions, globalVariables, units, components, dataDictionary}.

    Returns the names of the views that ran, in order -- what the export guard's
    derivation record says this phase rebuilt (`review.export_guard.record_derivation`).
    """
    ran = []
    for view_name in views_to_run(doc_type, config):
        if only is not None and view_name not in only:
            continue
        with timed(view_name):
            VIEW_REGISTRY[view_name](model, output_dir, model_dir, config)
        ran.append(view_name)
    return ran


# Import view components so they register themselves
from . import interface_tables  # noqa: F401
from . import unit_headers  # noqa: F401
from . import behaviour_diagram  # noqa: F401
from . import unit_diagrams  # noqa: F401
from . import flowcharts  # noqa: F401
from . import test_specs  # noqa: F401
from . import ut_export  # noqa: F401
