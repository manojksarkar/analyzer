"""Refusing to export a document that would ship the previous text.

`REQ-AP-04`, and the piece that makes this feature reliable rather than merely correct.

`analyzer.py reexport --from-phase 4` is documented as *"export only"* and **skips Phase 3** — the
step that rebuilds the view rows the document is built from. A correction saved a second earlier
updates the model and the override table; the export then reads rows Phase 3 wrote last time and
ships the old wording, with nothing to notice. Moving output into the database did not fix this: it
is still the row Phase 3 wrote last time.

So the export asks rather than assumes, correction by correction:

    for every view the correction's text reaches, in the documents being exported:
        that component's last derivation of the view  <  the correction   =>  stale

A **check, not an assumption**. Even if some future write path forgets to re-derive, the export
still cannot quietly ship stale text — which is the whole reason it is a query over stored facts
and not a flag someone sets.

## What is recorded, and by whom

`view_derivations` holds one row per (version, view, component): when that view was last derived
for that component, from the corrections that existed at that moment. `group_name` carries the
component id (`component_id` form).

The rows are an index of the **records** stored with the output. Phase 3 leaves one in each output
directory it builds — `DERIVATION_RECORD`: the views it ran, the components they covered, and the
moment it read the corrections — and the record is stored as an output row like any other file.
Two writers keep the index:

* **The capture** (`stamp_recorded_derivations`) replaces the version's rows with what the stored
  records say, in the transaction that replaces the output rows. A stamp therefore never outlives
  the output it vouches for: a run that put older rows back put their older records back too.
* **A save that re-derives rows itself** (`stamp_saved`) marks the records of the directories it
  rebuilt — `saved`, per component — and moves the rows forward, in the save's transaction. The
  mark is what lets the next capture keep the stamp; a run that overwrites those rows overwrites
  the mark with them, and the correction reads as stale again, which is then the truth.

Why not one "the whole version was derived" row, as before: that wildcard (`PIPELINE_ALL`) was
written at capture whatever Phase 3 had done — after a SWE.3-only run, after an export-only run that
ran no Phase 3 at all, after a run scoped to one group — so it vouched for SWE.4 specs, other groups
and pictures nobody had rebuilt. Reproduced: a label corrected, a SWE.3 re-export (what the web app
runs), then `reexport --from-phase 4 --doc-type all` shipped the SWE.4 document with the old label
and no warning. Rows written before this change are ignored: a version with corrections and only
such rows reads as stale until it is re-derived once.

## Which views a document is built from

The SWE.4 deliverables — the document and the UT export — are read from `SWE4_VIEWS`, the test
specs and the export built from them; SWE.3 is built from every other view. `flowcharts` runs in a
SWE.4 Phase 3 too (`views.registry.DOC_TYPE_VIEWS["swe4"]`), but only as the specs' input: the specs
are what carries a label into SWE.4, so theirs is the stamp that counts. An export is judged only
on the views its documents are read from: a SWE.3 export is not held up by SWE.4 specs it does not
print, and a SWE.3 re-derive cannot wave a SWE.4 export through. With no document type given,
every view counts — the conservative answer.

## Cost when nobody has corrected anything

Which is every project today. The first query reads this version's corrections through
`ix_text_overrides_version_kind`; it returns nothing and the guard stops. No scan, no join.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Dict, Iterable, Iterator, NamedTuple, Optional, Tuple

from sqlalchemy import delete, insert, select, update

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from api.db.postgres import schema as s   # noqa: E402

#: The legacy `view_derivations.view_name`: one row claiming a whole Phase-3 output. No longer
#: written, and ignored by `staleness` -- see the module docstring.
PIPELINE_ALL = "*"

#: The record Phase 3 leaves in each output directory it builds, and `capture_output` turns into
#: rows. JSON: {"views": {view: {"at": iso, "components": [...], "docTypes": [...],
#: "context": {...}?, "saved": {component: iso}?}}} -- `saved` written by `stamp_saved`.
DERIVATION_RECORD = "_derivations.json"

#: The views the SWE.4 deliverables are read from, and SWE.3 never is. The rest of
#: `views.registry.DOC_TYPE_VIEWS["swe4"]` is `flowcharts`, the specs' input -- see the module
#: docstring; a test keeps the two in step.
SWE4_VIEWS = frozenset(("testSpecs", "utExport"))

DOC_TYPES = ("swe3", "swe4")


class StaleExport(Exception):
    """The document would carry text that a correction has already replaced."""


class Staleness(NamedTuple):
    is_stale: bool
    reason: str
    newest_override_at: Optional[datetime.datetime]
    oldest_derivation_at: Optional[datetime.datetime]
    override_count: int
    #: Pictures still being produced. Any of these blocks an export (REQ-IM-02).
    pending_renders: int = 0
    #: Renders that gave up. These do NOT block -- see `staleness`.
    failed_renders: int = 0

    def explain(self) -> str:
        """One line a CLI or an API error can print as-is."""
        bits = []
        if self.is_stale:
            bits.append(self.reason)
        if self.failed_renders:
            bits.append("%d flowchart image(s) could not be drawn and are out of date"
                        % self.failed_renders)
        if not bits:
            return "up to date"
        return "%s (%d correction(s) in this version)" % ("; ".join(bits), self.override_count)


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------
def doc_types_of(value) -> Optional[Tuple[str, ...]]:
    """`"all"`, `"swe3"`, `("swe3", "swe4")` or None -> a tuple of document types.

    None stays None, which means "every view" -- the conservative answer for a caller that does
    not say what it is about to export.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = (value,)
    out = []
    for v in value:
        v = (v or "").strip().lower()
        if v == "all":
            out.extend(DOC_TYPES)
        elif v in DOC_TYPES:
            out.append(v)
        elif v:
            raise ValueError("unknown document type %r; expected swe3, swe4 or all" % v)
    return tuple(dict.fromkeys(out))


def views_read(views: Iterable[str], doc_types, swe3_built: Optional[set] = None) -> set:
    """The subset of `views` that the documents of `doc_types` are read from.

    `swe3_built` is the views a SWE.3 run has built for the version (`_swe3_built`): SWE.3 prints
    only those -- the flowcharts, say, only where `views.flowcharts` is on. None when the records
    cannot say, and then every view but SWE.4's counts.
    """
    views = set(views)
    types = doc_types_of(doc_types)
    if types is None:
        return views
    out = set()
    if "swe3" in types:
        out |= {v for v in views
                if v not in SWE4_VIEWS and (swe3_built is None or v in swe3_built)}
    if "swe4" in types:
        out |= {v for v in views if v in SWE4_VIEWS}
    return out


def _stored_records(conn, version_id: str) -> Iterator[Tuple[str, dict]]:
    """`(rel_path, record)` for every derivation record stored with this version's output."""
    vof = s.version_output_files
    for r in conn.execute(select(vof.c.rel_path, vof.c.content)
                          .where(vof.c.version_id == version_id,
                                 vof.c.rel_path.like("%" + DERIVATION_RECORD))).fetchall():
        if r.rel_path.rsplit("/", 1)[-1] == DERIVATION_RECORD:
            record = read_record(r.content or "")
            if record is not None:
                yield r.rel_path, record


def _swe3_built(conn, version_id: str) -> Optional[set]:
    """The views a SWE.3 run has built for this version, from the stored records' `docTypes`.

    What a SWE.3 document can print: the exporter embeds the flowcharts only when
    `views.flowcharts` is on, and then the SWE.3 run builds them too. Without this a label
    correction held up every SWE.3 export of a version whose flowcharts only SWE.4 draws -- the
    default -- and no SWE.3 re-derive could clear it. None when there is no record, or one from
    before `docTypes`: then nobody can say, and every view counts.
    """
    out, seen = set(), False
    for _path, record in _stored_records(conn, version_id):
        for view, entry in (record.get("views") or {}).items():
            if not isinstance(entry, dict):
                continue
            if not isinstance(entry.get("docTypes"), list):
                return None
            seen = True
            if {"swe3", "all"} & set(entry["docTypes"]):
                out.add(view)
    return out if seen else None


def component_id(name: Optional[str]) -> str:
    """The form a component is stored and compared in: `Layer1.Sample Core` is
    `layer1.sample-core`. Unit keys spell it with hyphens, config with spaces, and the two must
    meet."""
    return (name or "").strip().replace(" ", "-").casefold()


def _aware(dt: datetime.datetime) -> datetime.datetime:
    """Compare in UTC.

    SQLite hands back naive datetimes where Postgres hands back aware ones, and comparing the two
    raises `TypeError` -- which, inside an export path, would read as a crash rather than as the
    stale-or-not answer the caller asked for.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def _iso(dt: datetime.datetime) -> str:
    return _aware(dt).astimezone(datetime.timezone.utc).isoformat()


def _component_of(slot_kind: str, slot_key: str, component_of) -> Optional[str]:
    """The component a correction belongs to, in `component_id` form -- or None when its key
    does not name one. Entity and unit keys start with `Component|`; a struct description's key
    is the type's own name (`Point`, `NS::Wrapped`), which names no component at all."""
    from review import slot as _slot
    parts = _slot.parse(slot_kind, slot_key)
    ident = parts.get("entity_key") or parts.get("unit_key") or parts.get("function_id") or ""
    if "|" not in ident:
        return None
    return component_id(component_of(slot_kind, slot_key))


# ---------------------------------------------------------------------------
# the question
# ---------------------------------------------------------------------------
def staleness(conn, version_id: str, doc_types=None, component: Optional[str] = None) -> Staleness:
    """Whether exporting `doc_types` of this version would ship text a correction replaced.

    `doc_types` is what the export writes -- `"swe3"`, `"swe4"`, `"all"` -- and only the views
    those documents are built from are asked about. None asks about every view.

    `component` narrows the question to one component's documents -- whether ITS Word file has
    every correction, which is what approving one document asks (REVIEW_APPROVE_API_SPEC A6,
    A15). A correction keyed by no component (a struct description) still counts, as everywhere
    else here: which unit prints it is not in its key. So does one this build cannot place.
    """
    from review.derive import component_of, views_for

    # The corrections IN FORCE. An orphan was written for code that has since changed: it is
    # never applied, so no document prints it and no view is behind it (REQ-ID-03). Asking about
    # it anyway made a version whose only corrections were orphans stale for ever -- "no
    # derivation of this view for that component was ever recorded" when the component is gone --
    # and a re-export could not clear that.
    rows = conn.execute(
        select(s.text_overrides.c.slot_kind, s.text_overrides.c.slot_key,
               s.text_overrides.c.updated_at)
        .where(s.text_overrides.c.version_id == version_id,
               s.text_overrides.c.is_orphaned.is_(False))).fetchall()
    if component:
        want = component_id(component)
        kept = []
        for r in rows:
            try:
                comp = _component_of(r.slot_kind, r.slot_key, component_of)
            except Exception:                       # noqa: BLE001 -- cannot place: keep it
                kept.append(r)
                continue
            if comp is None or comp == want:
                kept.append(r)
        rows = kept
    if not rows:
        # Nobody has corrected anything, which is every project today. Nothing to be stale
        # against, and the guard costs one indexed lookup.
        return Staleness(False, "no corrections", None, None, 0)
    count = len(rows)
    newest = max((_aware(r.updated_at) for r in rows if r.updated_at), default=None)

    # REQ-IM-02. A picture still being drawn makes the version unexportable however fresh the
    # TEXT is: an export now ships the new wording and the old image.
    #
    # A FAILED render does not block. It cannot be waited for, and blocking on it would make one
    # unrenderable flowchart permanently unexportable -- the cure worse than the disease. It is
    # reported instead, through `failed_renders` and `explain()`, so the document goes out with
    # somebody knowing the picture is stale rather than nobody.
    from review.render_queue import counts as _render_counts
    renders = _render_counts(conn, version_id)

    stamps: Dict[Tuple[str, str], datetime.datetime] = {}
    for r in conn.execute(select(s.view_derivations.c.view_name, s.view_derivations.c.group_name,
                                 s.view_derivations.c.derived_at)
                          .where(s.view_derivations.c.version_id == version_id)):
        if r.view_name == PIPELINE_ALL or not r.derived_at or not component_id(r.group_name):
            # A legacy wildcard, or a stamp that names no component, vouches for nothing --
            # see the module docstring.
            continue
        k = (r.view_name, component_id(r.group_name))
        at = _aware(r.derived_at)
        if k not in stamps or stamps[k] < at:
            stamps[k] = at

    def verdict(stale: bool, reason: str, oldest=None) -> Staleness:
        return Staleness(stale, reason, newest, oldest, count,
                         renders.pending, renders.failed)

    types = doc_types_of(doc_types)
    swe3_built = _swe3_built(conn, version_id) if types and "swe3" in types else None
    # Only a document with pictures waits for one: SWE.4 prints no flowchart, and SWE.3 only
    # where a SWE.3 run draws them.
    if renders.pending and (types is None or "flowcharts" in views_read(("flowcharts",), types,
                                                                        swe3_built)):
        return verdict(True, "%d flowchart image(s) are still being drawn" % renders.pending,
                       min(stamps.values()) if stamps else None)

    oldest = None
    for r in rows:
        try:
            views = views_read(views_for(r.slot_kind), types, swe3_built)
            comp = _component_of(r.slot_kind, r.slot_key, component_of)
        except Exception as exc:                    # noqa: BLE001 -- a row this build cannot place
            # Not evidence of freshness. A correction the guard cannot read is a correction it
            # cannot vouch for.
            return verdict(True, "a correction this build cannot place (%s %r: %s)"
                           % (r.slot_kind, r.slot_key, exc), oldest)
        when = _aware(r.updated_at) if r.updated_at else newest
        for view in sorted(views):
            if comp is None:
                # A key that names no component -- a struct description is keyed by its type.
                # Which unit's table prints it is not in the key, so every component's
                # derivation of the view must be newer: the cautious reading.
                held = [at for (v, _c), at in stamps.items() if v == view]
                at = min(held) if held else None
            else:
                at = stamps.get((view, comp))
            if at is None:
                # Corrections exist and NOTHING recorded a derivation of this view for this
                # component. That is not evidence of freshness, it is the absence of evidence --
                # so it counts as stale. A guard that reads "no data" as "fine" is the guard that
                # does not guard.
                return verdict(True, "corrections exist but no derivation of %s for %s was ever "
                                     "recorded" % (view, comp or "any component"), oldest)
            oldest = at if oldest is None or at < oldest else oldest
            if when and when > at:
                return verdict(True, "a correction is newer than the derived output (%s in %s, "
                                     "its %s)" % (r.slot_kind, comp or "the version", view),
                               oldest)
    return verdict(False, "up to date", oldest)


def assert_exportable(conn, version_id: str, doc_types=None) -> Staleness:
    """Raise `StaleExport` if exporting `doc_types` now would ship superseded text.

    A FAILED render does not raise -- see `staleness` -- but it is still said out loud, because
    `REQ-IM-03` promises the document never goes out stale *without somebody being told*. Silence
    here would make that promise false while the code looked fine.
    """
    st = staleness(conn, version_id, doc_types)
    if st.failed_renders and not st.is_stale:
        from core.logging_setup import get_logger
        get_logger("review").warning(
            "version %s is exportable, but %d flowchart image(s) could not be drawn and are out "
            "of date", version_id, st.failed_renders)
    if st.is_stale:
        raise StaleExport(
            "version %s is not safe to export: %s.\n"
            "  Re-derive the views first:\n"
            "    python analyzer.py reexport --project-id <pid> --version-id %s --from-phase 3"
            % (version_id, st.explain(), version_id))
    return st


# ---------------------------------------------------------------------------
# recording a derivation
# ---------------------------------------------------------------------------
def stamp_view_derivations(conn, version_id: str, pairs: Iterable[Tuple[str, str]],
                           at: datetime.datetime) -> int:
    """Record that each `(view, component)` was derived at `at`. Returns the rows written.

    Never moves a stamp backwards: two saves in one component must not undo each other. Moving one
    back is the capture's job alone, and it does that by replacing the rows
    (`stamp_recorded_derivations`).
    """
    vd = s.view_derivations
    at = _aware(at)
    n = 0
    for view, component in pairs:
        comp = component_id(component)
        if not view or not comp or view == PIPELINE_ALL:
            continue
        where = (vd.c.version_id == version_id, vd.c.view_name == view, vd.c.group_name == comp)
        row = conn.execute(select(vd.c.derived_at).where(*where)).first()
        if row is None:
            conn.execute(insert(vd).values(version_id=version_id, view_name=view,
                                           group_name=comp, derived_at=at))
            n += 1
        elif row.derived_at is None or _aware(row.derived_at) < at:
            conn.execute(update(vd).where(*where).values(derived_at=at))
            n += 1
    return n


def stamp_saved(conn, version_id: str, pairs: Iterable[Tuple[str, str]],
                at: datetime.datetime) -> int:
    """A save re-derived these `(view, component)` pairs at `at`: mark the stored records, then the
    rows. Returns the rows written.

    The caller vouches that it rebuilt the pair in **every** stored directory whose record covers
    it -- a stamp is per component, not per directory. Every such record is marked, so the next
    capture, which rebuilds the stamps from the records, keeps this one. A save that brought one
    copy up to date and left another must not call this.
    """
    from review.rerender import write_output_row

    pairs = [(v, component_id(c)) for v, c in pairs if v and component_id(c) and v != PIPELINE_ALL]
    if not pairs:
        return 0
    for rel_path, record in list(_stored_records(conn, version_id)):
        if any([mark_saved(record, view, comp, at) for view, comp in pairs]):
            write_output_row(conn, version_id, rel_path, record_text(record))
    return stamp_view_derivations(conn, version_id, pairs, at)


def mark_saved(record: dict, view: str, component: str, at: datetime.datetime) -> bool:
    """Note in `record` that a save re-derived `view` for `component` at `at`. Pure: the caller
    stores the record. False when the record does not cover the pair, or already says as much."""
    entry = ((record or {}).get("views") or {}).get(view)
    comp = component_id(component)
    if not isinstance(entry, dict) or comp not in (entry.get("components") or ()):
        return False
    saved = dict(entry.get("saved") or {})
    before = _parse(saved.get(comp))
    if before is not None and before >= _aware(at):
        return False
    saved[comp] = _iso(at)
    entry["saved"] = dict(sorted(saved.items()))
    return True


def stamps_from_records(records: Iterable[dict]) -> Dict[Tuple[str, str], datetime.datetime]:
    """`{(view, component): derived_at}` -- what a set of stored records vouches for.

    A component's time in one record is the later of the run's `at` and a save's mark. Across
    records the latest wins, as a stamp always has: one row per (view, component).
    """
    out: Dict[Tuple[str, str], datetime.datetime] = {}
    for record in records:
        for view, entry in ((record or {}).get("views") or {}).items():
            if not isinstance(entry, dict) or view == PIPELINE_ALL:
                continue
            at = _parse(entry.get("at"))
            saved = entry.get("saved") if isinstance(entry.get("saved"), dict) else {}
            for comp in entry.get("components") or ():
                comp = component_id(comp)
                when = max((t for t in (at, _parse(saved.get(comp))) if t is not None),
                           default=None)
                if not comp or when is None:
                    continue
                if (view, comp) not in out or out[(view, comp)] < when:
                    out[(view, comp)] = when
    return out


def _parse(value) -> Optional[datetime.datetime]:
    try:
        return _aware(datetime.datetime.fromisoformat(str(value))) if value else None
    except ValueError:
        return None


def record_text(record: dict) -> str:
    """A record as it is written to disk and stored -- one format, so a save's rewrite of the row
    and the next run's rewrite of the file differ only where the record does."""
    return json.dumps(record, indent=2, sort_keys=True)


def record_derivation(output_dir: str, views: Iterable[str], components: Iterable[str],
                      read_at: datetime.datetime, context: Optional[dict] = None,
                      doc_types: Optional[Dict[str, Iterable[str]]] = None) -> str:
    """Write what this Phase-3 run derived into `output_dir`, merged with earlier runs' records.

    `read_at` is when the run READ its inputs -- the model and the corrections, not when it
    finished -- so a correction saved while the views were being built is newer than the stamp and
    still reads as stale.

    A view this run did not build keeps the entry an earlier run left, which is exactly what makes a
    SWE.3-only run unable to vouch for SWE.4 specs. A view it did build gets a new entry, without
    the `saved` marks of the old one: this run's rows replace the ones those saves wrote.
    `doc_types` is `{view: [document types it was built for]}`; the entry's `docTypes`
    accumulates them across runs -- which documents print it (`_swe3_built`). `context` is the
    part of the run's config the SWE.4 views depend on;
    it is kept beside those views' entries so that a save can re-derive them exactly as Phase 3
    did (`review.swe4_rederive`). No secrets: views, layers, components.
    """
    path = os.path.join(output_dir, DERIVATION_RECORD)
    record = read_record(path) or {}
    entries = dict(record.get("views") or {})
    comps = sorted({component_id(c) for c in components if component_id(c)})
    for view in views:
        entry = {"at": _iso(read_at), "components": comps}
        if doc_types is not None:
            old = entries.get(view)
            before = old.get("docTypes") if isinstance(old, dict) else None
            entry["docTypes"] = sorted(set(before or ()) | set(doc_types.get(view) or ()))
        if context is not None and view in SWE4_VIEWS:
            entry["context"] = context
        entries[view] = entry
    record["views"] = dict(sorted(entries.items()))
    os.makedirs(output_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(record_text(record))
    return path


def forget_derivation(output_dir: str, views: Iterable[str]) -> None:
    """Drop `views` from the derivation record in `output_dir`: this run rebuilt them WITHOUT the
    reviewers' corrections, which could not be loaded. No stamp may vouch for them then -- with
    none, the guard calls them stale and asks for a re-derive, where a stamp would have let the
    LLM's text ship as up to date (RF-1). Other views keep what earlier runs recorded."""
    path = os.path.join(output_dir, DERIVATION_RECORD)
    record = read_record(path)
    if not record:
        return
    entries = {v: e for v, e in (record.get("views") or {}).items() if v not in set(views)}
    record["views"] = dict(sorted(entries.items()))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(record_text(record))


def read_record(path_or_text) -> Optional[dict]:
    """A derivation record from a file path or its JSON text; None when absent or unreadable."""
    try:
        if isinstance(path_or_text, str) and path_or_text.lstrip().startswith("{"):
            data = json.loads(path_or_text)
        else:
            if not os.path.isfile(path_or_text):
                return None
            with open(path_or_text, encoding="utf-8") as fh:
                data = json.load(fh)
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _records_under(output_root: str) -> Iterator[Tuple[str, dict]]:
    """`(directory, record)` for every derivation record below `output_root`."""
    if not output_root or not os.path.isdir(output_root):
        return
    for root, _dirs, files in os.walk(output_root):
        if DERIVATION_RECORD in files:
            rec = read_record(os.path.join(root, DERIVATION_RECORD))
            if rec:
                yield root, rec


def stamp_recorded_derivations(conn, version_id: str, output_root: str) -> int:
    """Replace this version's `view_derivations` rows with what the records under `output_root`
    say. Returns the rows written.

    Called where the output is captured, inside the transaction that replaces the output rows with
    the files under `output_root` -- so the stamps are replaced with the records that came with
    those files, and land with them or not at all. Replaced, not merged: a stamp a save wrote for
    rows this capture has just overwritten vouches for text that is no longer stored. A save's
    stamp survives exactly when its mark did (`stamp_saved`). An export-only run leaves the records
    as they were, so it changes no stamp -- it rebuilt nothing.
    """
    vd = s.view_derivations
    stamps = stamps_from_records(rec for _dir, rec in _records_under(output_root))
    conn.execute(delete(vd).where(vd.c.version_id == version_id))
    if stamps:
        conn.execute(insert(vd), [{"version_id": version_id, "view_name": view,
                                   "group_name": comp, "derived_at": at}
                                  for (view, comp), at in sorted(stamps.items())])
    return len(stamps)
