"""Schema invariants (docs/production-redesign/07 §4, PG-1).

No live database: these assert the *design* — the pointer core, the three hashes,
the version-uniqueness rule (D-3), and that every per-version table cascade-deletes
with its version (so a new one can't be added without a delete story). A SQLite
build proves the whole thing is structurally sound.
"""
import os
import sys

import pytest
from sqlalchemy import create_engine

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from api.db.postgres.schema import metadata, PER_VERSION_TABLES


def _fk_to(table, target_table, column):
    """The ForeignKey on `table.column` pointing at `target_table`, or None."""
    col = table.c.get(column)
    if col is None:
        return None
    for fk in col.foreign_keys:
        if fk.column.table.name == target_table:
            return fk
    return None


class TestTableSet:
    def test_core_tables_present(self):
        names = set(metadata.tables)
        for expected in ("users", "projects", "versions", "analysis_jobs",
                         "documents", "entities", "entity_versions", "content_blobs",
                         "model_edges", "reuse_index", "tu_includes"):
            assert expected in names, f"missing table {expected!r}"

    def test_dropped_tables_absent(self):
        # organizations dropped (D-8); model_functions/globals/types replaced by the
        # entities/entity_versions/content_blobs manifest; entity_hashes folded in.
        for gone in ("organizations", "model_functions", "model_globals",
                     "model_types", "entity_hashes"):
            assert gone not in metadata.tables


class TestVersionIdentity:
    def test_unique_project_version(self):
        cols = {frozenset(c.name for c in uc.columns)
                for uc in metadata.tables["versions"].constraints
                if uc.__class__.__name__ == "UniqueConstraint"}
        assert frozenset({"project_id", "version"}) in cols, \
            "versions must be UNIQUE(project_id, version) (D-3)"

    def test_version_is_not_nullable(self):
        assert metadata.tables["versions"].c.version.nullable is False


class TestManifestOfPointers:
    def test_entity_versions_points_at_the_three_stores(self):
        ev = metadata.tables["entity_versions"]
        assert _fk_to(ev, "versions", "version_id")
        assert _fk_to(ev, "entities", "entity_id")
        assert _fk_to(ev, "content_blobs", "content_hash")

    def test_three_distinct_hashes(self):
        ev = metadata.tables["entity_versions"]
        for h in ("source_hash", "fingerprint", "content_hash"):
            assert h in ev.c, f"entity_versions missing {h} (D-15)"

    def test_content_blob_is_addressed_by_hash(self):
        cb = metadata.tables["content_blobs"]
        assert list(cb.primary_key.columns)[0].name == "content_hash"

    def test_entities_unique_per_project_key(self):
        cols = {frozenset(c.name for c in uc.columns)
                for uc in metadata.tables["entities"].constraints
                if uc.__class__.__name__ == "UniqueConstraint"}
        assert frozenset({"project_id", "entity_key"}) in cols


class TestImpactGraph:
    def test_single_edge_table_with_reverse_index(self):
        assert "model_edges" not in ("edge_calls",)  # sanity
        edges = metadata.tables["model_edges"]
        assert {"kind", "src_key", "dst_key", "mode"} <= set(edges.c.keys())
        # reverse traversal (who depends on X) must be indexed -> impact analysis
        indexed = [tuple(c.name for c in ix.columns) for ix in edges.indexes]
        assert ("version_id", "kind", "dst_key") in indexed


class TestRetention:
    def test_every_per_version_table_cascades_with_its_version(self):
        """A per-version table must FK version_id -> versions ON DELETE CASCADE, so
        deleting a version reclaims its rows in one statement (D-9 / retention)."""
        for name in PER_VERSION_TABLES:
            fk = _fk_to(metadata.tables[name], "versions", "version_id")
            assert fk is not None, f"{name} has no version_id -> versions FK"
            assert fk.ondelete == "CASCADE", f"{name}.version_id must ON DELETE CASCADE"


class TestBuilds:
    def test_metadata_builds_on_sqlite(self):
        # FKs resolve, no duplicate columns, all constraints construct.
        metadata.create_all(create_engine("sqlite://"))
