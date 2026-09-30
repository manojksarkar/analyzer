"""`setup` must upgrade a database that already exists, not only create a new one.

`metadata.create_all()` creates MISSING TABLES and nothing else. It never alters a table that is
already there, so on a database that has been used before, every migration that adds a COLUMN to
an existing table is skipped in silence. The tables a branch adds appear, the setup looks like it
worked, and the missing column surfaces much later, mid-run, as

    UndefinedColumn: column model_units.description does not exist

from a SELECT that names every column the schema declares.

A fresh database hides this completely -- which is why it survived a full SQLite end-to-end run
and reached an office machine on the first real Postgres install.
"""
import os
import sys

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tools"))

from api.db.postgres import schema as s
from db_setup import _add_missing_columns

#: Tables this branch added. Excluded when building the "old" database so it looks pre-branch.
NEW_TABLES = {"text_overrides", "text_override_history", "view_derivations",
              "regeneration_queue", "render_jobs"}


def _old_database(tmp_path, drop=("model_units", "description")):
    """A database as it stands BEFORE this branch: no new tables, and one missing column."""
    eng = sa.create_engine("sqlite:///" + str(tmp_path / "old.db").replace("\\", "/"))
    old = sa.MetaData()
    table_name, column_name = drop
    for t in s.metadata.sorted_tables:
        if t.name in NEW_TABLES:
            continue
        sa.Table(t.name, old, *[c._copy() for c in t.columns
                                if not (t.name == table_name and c.name == column_name)])
    old.create_all(eng)
    return eng


def _columns(eng, table):
    return {c["name"] for c in sa.inspect(eng).get_columns(table)}


class TestSetupUpgradesAnExistingDatabase:
    def test_create_all_alone_does_not_add_the_column(self, tmp_path):
        """The bug itself. If this ever starts passing without the repair, SQLAlchemy changed
        and the rest of this file can go."""
        eng = _old_database(tmp_path)
        s.metadata.create_all(eng)
        assert "description" not in _columns(eng, "model_units"), (
            "create_all altered an existing table; the repair below is then unnecessary")

    def test_the_repair_adds_it(self, tmp_path):
        eng = _old_database(tmp_path)
        s.metadata.create_all(eng)
        added, blocked = _add_missing_columns(eng, s.metadata)
        assert "description" in _columns(eng, "model_units")
        assert any("model_units.description" in a for a in added)
        assert not blocked

    def test_the_select_that_failed_now_works(self, tmp_path):
        """The actual failing statement: a SELECT naming every declared column."""
        eng = _old_database(tmp_path)
        s.metadata.create_all(eng)
        _add_missing_columns(eng, s.metadata)
        with eng.connect() as cx:
            cx.execute(sa.select(s.model_units).where(s.model_units.c.version_id == "v1")).all()

    def test_existing_rows_survive(self, tmp_path):
        """An ALTER that dropped and recreated the table would pass every check above."""
        eng = _old_database(tmp_path)
        with eng.begin() as cx:
            cx.execute(sa.text(
                "INSERT INTO model_units (version_id, unit_key, component, name) "
                "VALUES ('v1', 'Comp|UnitA', 'Comp', 'UnitA')"))
        s.metadata.create_all(eng)
        _add_missing_columns(eng, s.metadata)
        with eng.connect() as cx:
            rows = cx.execute(sa.select(s.model_units)).all()
        assert len(rows) == 1 and rows[0].unit_key == "Comp|UnitA"
        assert rows[0].description is None

    def test_it_is_idempotent(self, tmp_path):
        """`setup` is documented as safe to re-run, and people do re-run it."""
        eng = _old_database(tmp_path)
        s.metadata.create_all(eng)
        _add_missing_columns(eng, s.metadata)
        again, _ = _add_missing_columns(eng, s.metadata)
        assert again == []

    def test_a_current_database_needs_nothing(self, tmp_path):
        eng = sa.create_engine("sqlite:///" + str(tmp_path / "new.db").replace("\\", "/"))
        s.metadata.create_all(eng)
        assert _add_missing_columns(eng, s.metadata) == ([], [])


class TestItRefusesRatherThanGuesses:
    def test_a_not_null_column_with_no_default_is_reported_not_attempted(self, tmp_path):
        """A table with rows cannot take a NOT NULL column without a default, and inventing a
        backfill value is how a schema repair becomes data corruption. It is named, and the
        caller is sent to Alembic.

        `text_overrides.human_text` is the example because it is NOT NULL with no default and is
        not part of a primary key -- most of the schema's NOT NULL columns are key columns,
        which cannot go missing in the first place.
        """
        eng = sa.create_engine("sqlite:///" + str(tmp_path / "nn.db").replace("\\", "/"))
        partial = sa.MetaData()
        for t in s.metadata.sorted_tables:
            sa.Table(t.name, partial,
                     *[c._copy() for c in t.columns
                       if not (t.name == "text_overrides" and c.name == "human_text")])
        partial.create_all(eng)

        added, blocked = _add_missing_columns(eng, s.metadata)
        assert any("text_overrides.human_text" in b for b in blocked), blocked
        assert "human_text" not in _columns(eng, "text_overrides"), (
            "it was added anyway; a NOT NULL column on a table with rows must be refused")

    def test_a_blocked_column_does_not_stop_the_others(self, tmp_path):
        """One column it cannot handle must not leave the rest of the schema unrepaired."""
        eng = sa.create_engine("sqlite:///" + str(tmp_path / "mix.db").replace("\\", "/"))
        partial = sa.MetaData()
        for t in s.metadata.sorted_tables:
            sa.Table(t.name, partial,
                     *[c._copy() for c in t.columns
                       if not (t.name == "text_overrides" and c.name == "human_text")
                       and not (t.name == "model_units" and c.name == "description")])
        partial.create_all(eng)

        added, blocked = _add_missing_columns(eng, s.metadata)
        assert any("model_units.description" in a for a in added)
        assert any("text_overrides.human_text" in b for b in blocked)

    def test_a_column_the_schema_no_longer_declares_is_left_alone(self, tmp_path):
        """It belongs to a newer branch, or to a migration someone is midway through. Dropping
        it to tidy a tool's output would delete data."""
        eng = sa.create_engine("sqlite:///" + str(tmp_path / "extra.db").replace("\\", "/"))
        s.metadata.create_all(eng)
        with eng.begin() as cx:
            cx.execute(sa.text("ALTER TABLE model_units ADD COLUMN from_the_future TEXT"))
        _add_missing_columns(eng, s.metadata)
        assert "from_the_future" in _columns(eng, "model_units")


class TestEveryAdditiveMigrationIsCovered:
    """Not just `0009`. The check is general, so any future column addition is handled too."""

    @pytest.mark.parametrize("table,column", [
        ("model_units", "description"),          # 0009 -- the one that broke
        ("text_overrides", "slot_shape"),        # 0011 -- survived only because its table is new
    ])
    def test_a_missing_column_from_any_branch_migration_is_added(self, tmp_path, table, column):
        eng = sa.create_engine(
            "sqlite:///" + str(tmp_path / ("m_%s.db" % column)).replace("\\", "/"))
        partial = sa.MetaData()
        for t in s.metadata.sorted_tables:
            sa.Table(t.name, partial, *[c._copy() for c in t.columns
                                        if not (t.name == table and c.name == column)])
        partial.create_all(eng)
        assert column not in _columns(eng, table)
        _add_missing_columns(eng, s.metadata)
        assert column in _columns(eng, table)
