"""Is a document's Word file out of date? -- docs/design/WORD_FILE_UPDATES.md §4.3.

One rule, for R9, A15, Approve, the update's scope and Submit: the Word FILE, not "would an
export-only run ship old text" (that is `export_guard`, the CLI's backstop). A document of component
*C* and type *T*, whose working .docx was written by a run that started at *W*
(`documents.word_file_at`), is out of date when

* ``corrections`` -- a correction in force that *T* prints was saved after *W*. Its key names *C*
  (a struct description, keyed by its type: a unit of *C* shows it in its stored unit header table,
  or no stored table can say), and its views include one *T*'s document is read from
  (`export_guard.views_read`: a label reaches SWE.3 only where SWE.3 prints flowcharts);
* ``layerAdded`` -- `version_components` says *C* is ``stale``: a layer added to the version since
  changed its model (the caller passes those, with the layers);
* ``pictures`` -- a corrected flowchart picture of *C* is still being drawn and *T* prints
  flowcharts.

Why not the derivation stamps: a save re-derives its component's SWE.4 rows and stamps them, so the
stamps said "up to date" while the SWE.4 .docx was the old one -- and Approve froze it. *W* is when
the run that wrote the file STARTED (its restore, then Phase 3, read everything after it), so a
correction saved while it ran counts as not in the file: the cautious answer.

Also here: `record_word_files`, which sets *W* for the documents whose .docx a run wrote, as its
output is stored.
"""
from __future__ import annotations

import datetime
import os
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence

from sqlalchemy import and_, update

from review.export_guard import (_aware, _component_of, _derivation_stamps, _rows_in_force,
                                 _swe3_built, component_id, views_read)
from api.db.postgres import schema as s

#: The file name of each document type's Word file in its component's output directory:
#: `<prefix>_<component dir>.docx` (as `api/services/doc_render.DOCX_PREFIX`).
DOCX_PREFIX = {"SWE.3": "software_detailed_design", "SWE.4": "software_unit_test_specification"}
DOC_TYPE = {"SWE.3": "swe3", "SWE.4": "swe4"}

CORRECTIONS, LAYER_ADDED, PICTURES = "corrections", "layerAdded", "pictures"


class WordFile(NamedTuple):
    """One document's working Word file, as the question needs it."""
    document_id: str
    component: str                          # the document's group: its output dir
    process: str                            # SWE.3 | SWE.4
    written_at: Optional[datetime.datetime]  # W; None when not known (no column, no file)


class FileState(NamedTuple):
    out_of_date: bool
    why: tuple                               # of CORRECTIONS, LAYER_ADDED, PICTURES, in that order
    corrections: int
    pictures: int
    layer: Optional[str]


UP_TO_DATE = FileState(False, (), 0, 0, None)


def states(conn, version_id: str, files: Sequence[WordFile], *,
           stale_layers: Optional[Dict[str, List[str]]] = None) -> Dict[str, FileState]:
    """`{document_id: FileState}` for `files` -- each judged by the rule above.

    `stale_layers`: `{component: [layer, ...]}` for the components `version_components` says are
    stale (the list may be empty: the layer was not recorded). What it reads -- the corrections in
    force, the stored records, the render queue, the unit header rows when a struct description is
    in question -- it reads once for all of them.
    """
    files = list(files)
    if not files:
        return {}
    stale = {component_id(c): list(v or []) for c, v in (stale_layers or {}).items()}
    rows = _rows_in_force(conn, version_id)

    from review.derive import component_of, views_for
    from review.render_queue import by_component
    pending = {c: n.pending for c, n in by_component(conn, version_id).items()}
    need_swe3 = any(f.process == "SWE.3" for f in files)
    swe3_built = _swe3_built(conn, version_id) if need_swe3 else None

    # Each correction once: (component or None, views it reaches, when, its type key for a struct).
    placed = []
    for r in rows:
        try:
            comp = _component_of(r.slot_kind, r.slot_key, component_of)
            views = views_for(r.slot_kind)
        except Exception:                           # noqa: BLE001 -- cannot place: every file
            comp, views = None, None
        placed.append((r.slot_kind, r.slot_key, comp, views,
                       _aware(r.updated_at) if r.updated_at else None))

    placement_cache: list = []

    def prints_struct(type_key: str, comp: str) -> bool:
        if not placement_cache:
            placement_cache.append(struct_placement(conn, version_id))
        return placement_cache[0].prints(type_key, comp)

    stamps_cache: list = []

    def stamps():
        if not stamps_cache:
            stamps_cache.append(_derivation_stamps(conn, version_id))
        return stamps_cache[0]

    out: Dict[str, FileState] = {}
    for f in files:
        comp = component_id(f.component)
        doc_type = DOC_TYPE.get(f.process)
        if doc_type is None:
            out[f.document_id] = UP_TO_DATE
            continue
        corrections = 0
        for kind, key, rcomp, views, when in placed:
            if views is None:
                corrections += 1                    # a correction this build cannot place
                continue
            read = views_read(views, doc_type, swe3_built)
            if not read:
                continue
            if rcomp is None:
                from review import slot as _slot
                try:
                    type_key = _slot.parse(kind, key).get("entity_key") or key
                except Exception:                   # noqa: BLE001
                    type_key = key
                if kind == _slot.STRUCT_DESCRIPTION and not prints_struct(type_key, comp):
                    continue
            elif rcomp != comp:
                continue
            if f.written_at is not None:
                if when is not None and when > _aware(f.written_at):
                    corrections += 1
            else:
                # No time for this file anywhere: the derivation stamps, as the guard reads them.
                st = stamps()
                held = [st.get((v, comp)) for v in read]
                if any(at is None or (when is not None and when > at) for at in held):
                    corrections += 1
        prints_pictures = bool(views_read(("flowcharts",), doc_type, swe3_built))
        pictures = pending.get(comp, 0) if prints_pictures else 0
        layers = stale.get(comp)
        why = tuple(w for w, on in ((CORRECTIONS, corrections > 0),
                                    (LAYER_ADDED, layers is not None),
                                    (PICTURES, pictures > 0)) if on)
        out[f.document_id] = FileState(
            bool(why), why, corrections, pictures,
            ", ".join(layers) if layers else None)
    return out


class StructPlacement(NamedTuple):
    """Which components' stored unit header tables show which struct, class or union.

    `known`: the components whose every stored unit-header row names its type (`typeKey`); only
    for those can "it does not show it" be said. A component with a row from before `typeKey`, or
    with no stored table at all, may show any of them -- the cautious reading, per component (one
    version-wide flag let a component updated by new code vouch for an old one)."""
    known: frozenset
    shows: Dict[str, frozenset]

    def prints(self, type_key: str, component: str) -> bool:
        comp = component_id(component)
        return comp not in self.known or comp in self.shows.get(type_key, frozenset())


def struct_placement(conn, version_id: str) -> StructPlacement:
    """`StructPlacement` from this version's stored `unit_headers.json` rows."""
    import json
    from sqlalchemy import select
    vof = s.version_output_files
    complete: Dict[str, bool] = {}
    shows: Dict[str, set] = {}
    for r in conn.execute(select(vof.c.rel_path, vof.c.content)
                          .where(vof.c.version_id == version_id,
                                 vof.c.rel_path.like("%unit_headers.json"))).fetchall():
        if not (r.rel_path or "").replace("\\", "/").endswith("unit_headers.json"):
            continue
        try:
            by_unit = json.loads(r.content or "{}") or {}
        except ValueError:
            by_unit = None
        if not isinstance(by_unit, dict):
            continue
        for unit_key, rows in by_unit.items():
            comp = component_id(str(unit_key).split("|", 1)[0])
            ok = complete.get(comp, True)
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                if "typeKey" not in row:
                    ok = False
                elif row.get("typeKey"):
                    shows.setdefault(row["typeKey"], set()).add(comp)
            complete[comp] = ok
    return StructPlacement(frozenset(c for c, ok in complete.items() if ok),
                           {k: frozenset(v) for k, v in shows.items()})


# ---------------------------------------------------------------------------
# when a run read what it writes
# ---------------------------------------------------------------------------
def wait_for_saves(engine, version_id: str) -> datetime.datetime:
    """Now -- taken while holding the version's save lock (`override_service._serialize_saves`,
    PostgreSQL), so every save already under way has committed first. An update sets its `since`
    with this once its job is visible: a save that stamped its time before then is in the rows the
    run restores; one that comes after is newer than `since` -- out of date, the truth -- or is
    refused by the hold (WORD_FILE_UPDATES §4.6). SQLite serialises writers by itself."""
    from review.override_service import _serialize_saves
    with engine.begin() as cx:
        _serialize_saves(cx, version_id)
        return datetime.datetime.now(datetime.timezone.utc)


def run_start(conn, version_id: str) -> Optional[datetime.datetime]:
    """When the version's current run started: its `version_runs` row while that run is still
    `running` (the process storing its output is that run). None otherwise."""
    from sqlalchemy import select
    t = s.version_runs
    try:
        r = conn.execute(select(t.c.started_at, t.c.outcome)
                         .where(t.c.version_id == version_id)).first()
    except Exception:                               # noqa: BLE001 -- no row to read
        return None
    if r is None or r.outcome != "running" or r.started_at is None:
        return None
    return _aware(r.started_at)


def components_touched_since(conn, version_id: str, since: datetime.datetime) -> List[str]:
    """The components a run that started at `since` asked for or started -- what run.py marks in
    `version_components` around each plan, whatever its scope (a group, a layer)."""
    from sqlalchemy import select
    t = s.version_components
    floor = _aware(since)
    out = []
    for r in conn.execute(select(t.c.component, t.c.requested_at, t.c.started_at)
                          .where(t.c.version_id == version_id)):
        when = [_aware(x) for x in (r.requested_at, r.started_at) if x is not None]
        if any(w >= floor for w in when):
            out.append(r.component)
    return sorted(out)


def unstored_dirs(conn, version_id: str, output_dir: str) -> List[str]:
    """The component directories under `output_dir` with no stored row at all: output the database
    has never seen -- a run cut short after making them and before storing (a generation stores
    once, at its end). Storing them replaces nothing, so it can revert nothing."""
    from sqlalchemy import distinct, select
    if not output_dir or not os.path.isdir(output_dir):
        return []
    vof = s.version_output_files
    have = {g for (g,) in conn.execute(select(distinct(vof.c.group_name))
                                       .where(vof.c.version_id == version_id)) if g}
    return sorted(d for d in os.listdir(output_dir)
                  if os.path.isdir(os.path.join(output_dir, d)) and d not in have)


def read_at(component_dir: str) -> Optional[datetime.datetime]:
    """When the run that derived `component_dir` read its inputs: the earliest `at` of its derivation
    record (`export_guard.DERIVATION_RECORD`), or None."""
    from review.export_guard import DERIVATION_RECORD, _parse, read_record
    rec = read_record(os.path.join(component_dir, DERIVATION_RECORD)) or {}
    times = [_parse((e or {}).get("at")) for e in (rec.get("views") or {}).values()
             if isinstance(e, dict)]
    times = [t for t in times if t is not None]
    return min(times) if times else None


def file_written_at(output_root: Optional[str], component: str,
                    process: str) -> Optional[datetime.datetime]:
    """The time a component's Word file of `process` was written on this machine (its mtime, UTC),
    or None when it is not here. For a document recorded before `word_file_at` existed."""
    prefix = DOCX_PREFIX.get(process)
    if not output_root or not prefix or not component:
        return None
    path = os.path.join(output_root, component, "%s_%s.docx" % (prefix, component))
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc)
    except OSError:
        return None


def written_by(output_dir: str, since: datetime.datetime,
               components: Optional[Iterable[str]] = None) -> List[tuple]:
    """`[(component dir, process)]` of the Word files under `output_dir` written at or after `since`
    -- the ones a run that started at `since` wrote. Only `components`' dirs when given."""
    if not output_dir or not os.path.isdir(output_dir):
        return []
    dirs = (list(dict.fromkeys(c for c in components if c)) if components is not None
            else sorted(d for d in os.listdir(output_dir)
                        if os.path.isdir(os.path.join(output_dir, d))))
    floor = _aware(since).timestamp()
    found = []
    for d in dirs:
        for process, prefix in DOCX_PREFIX.items():
            path = os.path.join(output_dir, d, "%s_%s.docx" % (prefix, d))
            try:
                if os.path.getmtime(path) >= floor:
                    found.append((d, process))
            except OSError:
                continue
    return found


def record_word_files(conn, version_id: str, output_dir: str, since: datetime.datetime,
                      components: Optional[Iterable[str]] = None) -> int:
    """Set `documents.word_file_at = since` for each document whose Word file this run wrote
    (`written_by`). Returns how many rows moved. A document not recorded yet gets its time when it
    is (`api/services/document_registry.py`)."""
    d = s.documents
    n = 0
    at = _aware(since)
    for component, process in written_by(output_dir, since, components):
        n += conn.execute(update(d).where(and_(d.c.version_id == version_id,
                                               d.c.component == component,
                                               d.c.process == process))
                          .values(word_file_at=at)).rowcount or 0
    return n
