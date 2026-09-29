"""Domain dataclass <-> table row conversion (docs/production-redesign/07, PG-2).

The domain layer (`api/models/domain.py`) stays storage-agnostic, so this is the one
place that knows the few differences between a dataclass field and its column:

  * three fields collide with SQL reserved words / the chosen column name:
      Version.tag      -> versions.version   (the D-3 identity)
      Document.group   -> documents.component
      DocumentSection.order -> document_sections.ord
      Function.group   -> job_functions.component
  * AnalysisJob.phases is a list of AnalysisPhase dataclasses <-> a JSON array.

Everything else maps by name. Columns with no matching field (e.g. the engine-written
versions.parse_fingerprint, or job_functions.job_id) are simply left to the repository.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Type

from ...models.domain import (
    User, Project, ProjectMember, AccessRequest, Version, Commit, AnalysisJob,
    AnalysisPhase, Document, DocumentSection, DocumentAssignment, Function,
    CompareResult, DocumentDiff, Notification,
)

# domain field name -> column name (only where they differ)
_RENAMES: dict[type, dict[str, str]] = {
    Version: {"tag": "version"},
    Document: {"group": "component"},
    DocumentSection: {"order": "ord"},
    Function: {"group": "component"},
}


# Fields read from the database but never written by the API. `Version.warnings` is derived
# from `versions.run_report`, the manifest only the engine writes: writing it back from an
# object read before the run finished would erase what the run reported.
_READ_ONLY: dict[type, set] = {Version: {"warnings"}}


def to_row(obj: Any) -> dict:
    """A dataclass -> a dict of column values (only the domain's own fields)."""
    renames = _RENAMES.get(type(obj), {})
    skip = _READ_ONLY.get(type(obj), set())
    row: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        if f.name in skip:
            continue
        val = getattr(obj, f.name)
        if f.name == "phases" and val is not None:            # AnalysisJob
            val = [dataclasses.asdict(p) for p in val]
        row[renames.get(f.name, f.name)] = val
    return row


def from_row(cls: Type, row: Any) -> Any:
    """A result row -> a domain dataclass. Columns absent from the dataclass are ignored."""
    mapping = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    renames = _RENAMES.get(cls, {})
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        col = renames.get(f.name, f.name)
        if col not in mapping:
            continue
        val = mapping[col]
        if f.name == "phases" and val is not None:            # AnalysisJob
            val = [AnalysisPhase(**p) for p in val]
        kwargs[f.name] = val
    if cls is Version:
        report = mapping.get("run_report")
        warns = report.get("warnings") if isinstance(report, dict) else None
        kwargs["warnings"] = [str(w) for w in warns] if isinstance(warns, list) else []
    return cls(**kwargs)
