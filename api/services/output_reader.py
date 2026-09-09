"""OutputReader (PG-5b) — read a version's Phase-3 view outputs, Postgres-first with a disk
fallback.

PG-5a persists the text/JSON view files (interface tables, flowchart + unit-diagram mermaid,
behaviour rows) to the ``version_output_files`` table. This reader lets the API consume those
views from Postgres when they're there, and fall back to the on-disk snapshot
(``workspaces/<pid>/versions/<ver…>/output/`` or the commit dir) when they're not — e.g. the
in-memory/json backends, or versions produced before PG-5a. Binary assets (PNG/DOCX) are NOT
handled here; they stay as files (D-14) and keep their existing disk resolution.

Self-contained: reads the API's own ``version_output_files`` schema via the SQL backend's engine;
no import from the engine package.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


class OutputReader:
    """Reads view-output text files for one version. ``rel_path`` is a POSIX path relative to the
    version's ``output/`` dir (e.g. ``"My-Sample/interface_tables.json"``). Postgres wins when it
    has the file; otherwise the on-disk snapshot dir is used."""

    def __init__(self, db: Any, version_id: Optional[str], snap_dir: Optional[Path]):
        self.db = db
        self.version_id = version_id
        self.snap_dir = snap_dir            # Path to workspaces/<pid>/versions/<ver…> (or commit dir), or None
        self._pg: Optional[dict] = None     # lazily-loaded {rel_path: content} from PG; {} once loaded-and-empty

    # -- Postgres --------------------------------------------------------------
    def _pg_files(self) -> dict:
        if self._pg is None:
            self._pg = {}
            engine = getattr(self.db, "_engine", None)
            if engine is not None and self.version_id:
                try:
                    from sqlalchemy import select
                    from ..db.postgres import schema as s
                    vof = s.version_output_files
                    with engine.connect() as cx:
                        self._pg = {r.rel_path: r.content for r in cx.execute(
                            select(vof.c.rel_path, vof.c.content)
                            .where(vof.c.version_id == self.version_id))}
                except Exception:               # no such table yet / not SQL — fall back to disk
                    self._pg = {}
        return self._pg

    def has_pg(self) -> bool:
        """True when this version's view outputs are served from Postgres."""
        return bool(self._pg_files())

    # -- reads -----------------------------------------------------------------
    def read_text(self, rel_path: str) -> Optional[str]:
        """The content of one view file — Postgres first, else the disk snapshot, else None."""
        pg = self._pg_files()
        if rel_path in pg:
            return pg[rel_path]
        if self.snap_dir is not None:
            p = self.snap_dir / "output" / rel_path
            if p.is_file():
                try:
                    return p.read_text(encoding="utf-8")
                except OSError:
                    return None
        return None

    def groups(self) -> set[str]:
        """The set of top-level output subdirs (component groups) that have view files."""
        pg = self._pg_files()
        if pg:
            return {rel.split("/", 1)[0] for rel in pg if "/" in rel}
        if self.snap_dir is not None:
            out = self.snap_dir / "output"
            if out.is_dir():
                return {d.name for d in out.iterdir() if d.is_dir()}
        return set()
