"""Re-deriving a component's SWE.4 specs when a correction is saved (`REQ-CS-04`, `REQ-AP-02`).

A SWE.4 spec carries two kinds of corrected text: its function's `description`, copied as it is,
and every node label of the flowchart it transcribes into Test Steps -- "Check whether <label>",
"Return <label>", and in a Dynamic Behaviour spec another unit's steps spliced in place. The UT
export is built from the specs, so a return label is the expected return of a case. Nothing else
in a save touches `test_specs.json` or `ut_export.json`, so without this their rows keep the old
wording until the next Phase-3 run.

The save re-derives them from what is stored, through the views' own code:

    for each stored output directory whose SWE.4 specs cover the component:
        the settings they were built with       the directory's `_derivations.json` record
        the model                               the save's, holding the corrected text
        the flowchart graphs                    the stored flowchart rows, with every label
                                                correction applied the way Phase 3 applies them
        test_specs.build(...)                   the component only, merged into the stored file
        ut_export.build(...)                    the whole file, built from the merged specs
        write the rows                          in the save's transaction (REQ-AP-02)

No parse, no LLM, no C++ source and no output tree, so it runs on an API host. A version with no
SWE.4 output -- every version the web app generates -- costs one query of row paths.

## Only where the settings are known

The SWE.4 views depend on the run's config: which spec kinds, the layers that scope the mock rule,
the Dynamic Behaviour filter mode, the UT export's review block. A version generated from the CLI
keeps no config of its own, so Phase 3 stores what these views used beside their entry in the
record (`run_views._record_derivation`). A directory covering the component without it is output
from before the record existed: nothing is re-derived, nothing is reported, and the export guard
keeps calling the SWE.4 export stale until Phase 3 runs -- which is then the truth.

## The component, not the file

Built for the saved slot's component only and merged into the stored file. Nothing in a spec
depends on which other components share its document: the mock rule's other arm is per unit
(`test_specs._mocked_callee_ids`), and a Dynamic Behaviour spec runs its own component only.
`test_review_swe4_rederive` pins it: a component re-derived alone and merged gives the file a
whole-document build gives, byte for byte.
"""
from __future__ import annotations

import json
import os
import posixpath
import sys
from typing import Any, Callable, Dict, Iterable, List, Sequence

from sqlalchemy import select

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

TEST_SPECS = "test_specs.json"
UT_EXPORT = "ut_export.json"
TEST_SPECS_VIEW = "testSpecs"
UT_EXPORT_VIEW = "utExport"


# ---------------------------------------------------------------------------
# the save's side
# ---------------------------------------------------------------------------
def make_save_deriver(conn, models) -> Callable[..., Sequence[str]]:
    """The `derive=` a save hands `override_service`: the SWE.4 views the saved kind reaches,
    re-derived for the saved slot's component (`rederive`). Every other kind returns nothing.

    `models` is the save's `ModelAccess`, holding the artifacts the save read and corrected; a
    plain model dict is accepted too. See `model_of` for where the rest comes from.
    """
    def _derive(*, version_id, slot_kind, location=None, flowchart_id=None, **_kw):
        from review.derive import views_for
        from review.export_guard import SWE4_VIEWS

        if not SWE4_VIEWS & set(views_for(slot_kind)):
            return []
        ident = flowchart_id or (location.entry_key if location is not None else "") or ""
        if "|" not in ident:
            return []
        component = ident.split("|", 1)[0]
        try:
            return rederive(conn, version_id, component,
                            lambda: model_of(models, conn, version_id))
        except Exception as exc:                   # noqa: BLE001 -- see below
            # The reviewer's correction is worth more than this copy of it. A spec that cannot
            # be rebuilt is left as it was and not stamped, so the export guard keeps calling
            # SWE.4 stale until Phase 3 rebuilds it -- the truth, and said out loud. A database
            # error is different: the transaction is gone, and the save must fail with it.
            from sqlalchemy.exc import SQLAlchemyError
            if isinstance(exc, SQLAlchemyError):
                raise
            from core.logging_setup import get_logger
            get_logger("review").warning(
                "the SWE.4 specs of %s in version %s were not re-derived at save (%s); SWE.4 "
                "stays stale until Phase 3 runs", component, version_id, exc)
            return []

    return _derive


def model_of(models, conn, version_id: str) -> Dict[str, Any]:
    """The model the SWE.4 views read -- what `run_views._load_model` loads.

    What the save already holds comes from `models`; the rest is read through the SAVE'S
    connection. Not through the repository, which opens a connection of its own: once the save
    has written, that is a second connection inside one transaction -- on SQLite it waits on the
    save's own lock, and under a single-connection pool it rolls the save back when it closes.
    Both read the same loaders (`model_store.load_*`), and the save's connection also sees the
    model write it has just made.
    """
    from core import model_store
    from core.model_io import COMPONENTS, DATA_DICTIONARY, FUNCTIONS, GLOBALS, UNITS
    if isinstance(models, dict):
        return models
    loaders = {FUNCTIONS: model_store.load_functions, GLOBALS: model_store.load_globals,
               UNITS: model_store.load_units, COMPONENTS: model_store.load_components,
               DATA_DICTIONARY: model_store.load_types}
    out = {}
    for name, load in loaders.items():
        held = models.loaded(name) if models is not None else None
        out[name] = held if held is not None else (load(conn, version_id) or {})
    return out


# ---------------------------------------------------------------------------
# the re-derivation
# ---------------------------------------------------------------------------
def rederive(conn, version_id: str, component: str, model) -> List[str]:
    """Re-derive `component`'s SWE.4 specs, and the UT export built from them, in every stored
    directory that carries them. Returns the views re-derived: `testSpecs`, and `utExport` when
    every export covering the component was rebuilt too.

    `component` is spelled as the model's keys spell it (`Layer1.Sample-Core`). `model` is the
    model dict, or a callable returning it, called only when there is something to re-derive.

    The views returned are stamped for the component as a whole (`export_guard.stamp_saved`), so
    when any directory covering it cannot be rebuilt, nothing is written and nothing returned.
    """
    from review.export_guard import DERIVATION_RECORD, component_id, read_record

    comp = component_id(component)
    paths = _paths(conn, version_id)
    dirs = sorted({posixpath.dirname(p) for p in paths if posixpath.basename(p) == TEST_SPECS})
    if not comp or not dirs:
        return []

    records = _contents(conn, version_id, [_join(d, DERIVATION_RECORD) for d in dirs])
    found = []
    for d in dirs:
        record = read_record(records.get(_join(d, DERIVATION_RECORD)) or "") or {}
        views = record.get("views") or {}
        entry = views.get(TEST_SPECS_VIEW)
        if not isinstance(entry, dict) or comp not in (entry.get("components") or ()):
            continue                       # this document does not carry the component
        if not isinstance(entry.get("context"), dict):
            return []                      # built before the settings were kept -- see docstring
        found.append((d, entry["context"], views.get(UT_EXPORT_VIEW)))
    if not found:
        return []

    from core.model_io import DATA_DICTIONARY
    from review import phase3_overrides as p3
    from review.carry_forward import overrides_for_config
    from review.rerender import write_output_row
    from views import ut_export
    from views.test_specs import build as build_specs
    from views.test_steps import cfgs_from_entries

    stored = _contents(conn, version_id,
                       [_join(d, name) for d, _c, _u in found for name in (TEST_SPECS, UT_EXPORT)])
    specs = {}
    for d, _c, _u in found:
        try:
            specs[d] = json.loads(stored.get(_join(d, TEST_SPECS)) or "")
        except ValueError:
            return []                      # unreadable: nothing to merge into, nothing written
        if not isinstance(specs[d], dict):
            return []

    whole = model() if callable(model) else model
    corrections = overrides_for_config(conn, version_id)
    labels = corrections.get(p3.NODE_LABEL_KIND) or {}
    shapes = corrections.get(p3.NODE_LABEL_SHAPES) or {}

    exports_rebuilt = True
    for d, context, ut_entry in found:
        config = {"views": context.get("views") or {}, "layers": context.get("layers") or {},
                  "_analyzerAllowedComponents": [component]}
        layer = context.get("layerComponents")
        scoped = narrow(whole, layer) if layer else whole

        fresh = build_specs(scoped, config, cfgs_from_entries(
            _flowcharts(conn, version_id, paths, d, labels, shapes)), verbose=False)
        merged = merge(specs[d], fresh, component)
        spec_path = _join(d, TEST_SPECS)
        _write_if_changed(write_output_row, conn, version_id, spec_path,
                          json.dumps(merged, indent=2), stored.get(spec_path))

        ut_path = _join(d, UT_EXPORT)
        if ut_path in stored:
            ut_config = config
            if isinstance(ut_entry, dict) and isinstance(ut_entry.get("context"), dict):
                ut_config = {"views": ut_entry["context"].get("views") or {}}
            payload = ut_export.build(merged, whole.get(DATA_DICTIONARY) or {}, ut_config)
            _write_if_changed(write_output_row, conn, version_id, ut_path,
                              json.dumps(payload, indent=2), stored.get(ut_path))
        elif isinstance(ut_entry, dict) and comp in (ut_entry.get("components") or ()):
            exports_rebuilt = False        # recorded, but no row to rebuild

    # An export recorded for the component in a directory whose specs do not cover it cannot be
    # vouched for either.
    covered = {d for d, _c, _u in found}
    for d in dirs:
        if d in covered:
            continue
        record = read_record(records.get(_join(d, DERIVATION_RECORD)) or "") or {}
        ut_entry = (record.get("views") or {}).get(UT_EXPORT_VIEW)
        if isinstance(ut_entry, dict) and comp in (ut_entry.get("components") or ()):
            exports_rebuilt = False
    return [TEST_SPECS_VIEW] + ([UT_EXPORT_VIEW] if exports_rebuilt else [])


def merge(stored: Dict[str, Any], fresh: Dict[str, Any], component: str) -> Dict[str, Any]:
    """`stored` with `component`'s units and Dynamic Behaviour specs taken from `fresh`, in the
    layout the view writes: `unitNames` first, the units in their stored order, `dynamicSpecs`
    last. A unit the fresh build no longer has is dropped; a new one goes after the others."""
    from review.export_guard import component_id
    from views.dynamic_specs import DYNAMIC_KEY

    comp = component_id(component)
    reserved = ("unitNames", DYNAMIC_KEY)

    def ours(key) -> bool:
        return component_id(str(key).split("|", 1)[0]) == comp

    units: Dict[str, Any] = {}
    for key, value in stored.items():
        if key in reserved:
            continue
        if not ours(key):
            units[key] = value
        elif key in fresh:
            units[key] = fresh[key]
    for key, value in fresh.items():
        if key not in reserved and key not in units:
            units[key] = value

    old_names, new_names = stored.get("unitNames") or {}, fresh.get("unitNames") or {}
    names = {}
    for key, value in units.items():
        source = new_names if ours(key) else old_names
        names[key] = source.get(key, (value or {}).get("name", key)
                                if isinstance(value, dict) else key)

    old_dyn = stored.get(DYNAMIC_KEY) if isinstance(stored.get(DYNAMIC_KEY), dict) else {}
    new_dyn = fresh.get(DYNAMIC_KEY) or {}
    dynamic: Dict[str, Any] = {}
    for key, specs in old_dyn.items():
        if component_id(key) != comp:
            dynamic[key] = specs
        elif key in new_dyn:
            dynamic[key] = new_dyn[key]
    for key, specs in new_dyn.items():
        dynamic.setdefault(key, specs)

    out: Dict[str, Any] = {"unitNames": names}
    out.update(units)
    out[DYNAMIC_KEY] = dynamic
    return out


def narrow(model: Dict[str, Any], components: Iterable[str]) -> Dict[str, Any]:
    """The model narrowed to `components`, as Phase 3 narrows it to a layer --
    `run_views._filter_model_to_components`, restated because importing `run_views` resets the
    process's run context. A test keeps the two equal."""
    lower = {c.lower().replace(" ", "-") for c in components}
    out = dict(model)
    for key in ("functions", "globalVariables", "units"):
        if key in model:
            out[key] = {k: v for k, v in model[key].items() if k.split("|")[0].lower() in lower}
    if "components" in model:
        out["components"] = {k: v for k, v in model["components"].items() if k.lower() in lower}
    return out


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------
def _join(directory: str, name: str) -> str:
    return posixpath.join(directory, name) if directory else name


def _paths(conn, version_id: str) -> List[str]:
    vof = s.version_output_files
    return [r.rel_path for r in conn.execute(select(vof.c.rel_path)
                                             .where(vof.c.version_id == version_id))]


def _contents(conn, version_id: str, paths: Iterable[str]) -> Dict[str, str]:
    """`{rel_path: content}` for the rows that exist. Chunked: SQLite caps bound parameters."""
    vof = s.version_output_files
    wanted = list(dict.fromkeys(p for p in paths if p))
    out: Dict[str, str] = {}
    for i in range(0, len(wanted), 500):
        for r in conn.execute(select(vof.c.rel_path, vof.c.content)
                              .where(vof.c.version_id == version_id,
                                     vof.c.rel_path.in_(wanted[i:i + 500]))):
            out[r.rel_path] = r.content
    return out


def _flowcharts(conn, version_id, paths, directory, labels, shapes) -> List[Any]:
    """The directory's flowchart files as `test_steps.load_cfgs` reads them -- `flowcharts/*.json`
    in name order, `_summary.json` and unreadable files skipped -- with every label correction
    applied as the `flowcharts` view applies it. The save that triggered this patched one stored
    copy of its flowchart; a directory holding another copy is corrected here, in memory."""
    from review import phase3_overrides as p3

    fc_dir = _join(directory, "flowcharts")
    wanted = sorted(p for p in paths
                    if posixpath.dirname(p) == fc_dir and p.endswith(".json")
                    and posixpath.basename(p) != "_summary.json")
    files = []
    for _path, text in sorted(_contents(conn, version_id, wanted).items()):
        try:
            entries = json.loads(text or "[]")
        except ValueError:
            continue
        if isinstance(entries, list):
            if labels:
                p3.apply_to_flowchart_json(entries, labels, shapes)
            files.append(entries)
    return files


def _write_if_changed(write, conn, version_id, rel_path, text, before) -> None:
    """A row nobody's correction changed is left as it is: rewriting it would make "what did this
    save change" unanswerable from the table."""
    if text != before:
        write(conn, version_id, rel_path, text)
