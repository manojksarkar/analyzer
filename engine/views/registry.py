"""View + exporter registries and the per-doc-type view sets.

Doc type is a *dimension*, not a phase: Phases 1-3 (parse -> derive -> views)
stay doc-type-agnostic; only Phase 4 (export) diverges. Three registries make
that work:

  VIEW_REGISTRY      view name -> run(model, output_dir, model_dir, config)
  EXPORTER_REGISTRY  doc type  -> the Phase-4 exporter script (basename)
  DOC_TYPE_VIEWS     doc type  -> the Phase-3 views it needs, or None meaning
                                  "every config-enabled view" (SWE.3's existing
                                  behaviour, preserved so a no-flag run is
                                  byte-for-byte unchanged)
"""
VIEW_REGISTRY = {}


def register(name):
    def decorator(fn):
        VIEW_REGISTRY[name] = fn
        return fn
    return decorator


# Concrete doc types the pipeline can emit. "all" is a meta value handled by the
# planner (expands to every concrete type); it is never a key in the maps below.
DOC_TYPE_SWE3 = "swe3"
DOC_TYPE_SWE4 = "swe4"
DOC_TYPES = (DOC_TYPE_SWE3, DOC_TYPE_SWE4)
DOC_TYPE_ALL = "all"
DOC_TYPE_CHOICES = (DOC_TYPE_SWE3, DOC_TYPE_SWE4, DOC_TYPE_ALL)

# doc type -> Phase-4 exporter script (basename, resolved against engine/ by the
# PhaseRunner).
EXPORTER_REGISTRY = {
    DOC_TYPE_SWE3: "docx_exporter.py",
    DOC_TYPE_SWE4: "swe4_exporter.py",
}

# doc type -> the Phase-3 view names it consumes. None means "every
# config-enabled view" -- SWE.3's historical behaviour, kept intact so a default
# run reproduces the SWE.3 document exactly. SWE.4 transcribes each function's
# control flow into Test Steps, so it needs the flowchart engine's CFG output
# alongside its own view; `flowcharts` registers first, so it also runs first.
DOC_TYPE_VIEWS = {
    DOC_TYPE_SWE3: None,
    DOC_TYPE_SWE4: ("flowcharts", "testSpecs"),
}


def concrete_doc_types(doc_type):
    """Expand a doc-type selector into the concrete doc types to emit.

    "all" -> every entry in DOC_TYPES; anything else -> just itself.
    """
    return list(DOC_TYPES) if doc_type == DOC_TYPE_ALL else [doc_type]
