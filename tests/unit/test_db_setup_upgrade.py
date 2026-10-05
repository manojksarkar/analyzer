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
import datetime
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


class TestTheMigrationStamp:
    """RF-4: setup built the schema without Alembic and stamped nothing, so the next `alembic
    upgrade head` started from the first migration and failed on a table that already existed.
    Setup now stamps the head; proved on PostgreSQL 2026-10-04 (stamped, then `upgrade head` a
    no-op)."""

    def test_the_head_setup_stamps_is_the_newest_migration(self):
        import glob
        import re
        from db_setup import _alembic_head
        head = _alembic_head()
        revisions = []
        for p in glob.glob(os.path.join(PROJECT_ROOT, "alembic", "versions", "*.py")):
            m = re.search(r'^revision\s*=\s*["\']([^"\']+)', open(p, encoding="utf-8").read(), re.M)
            if m:
                revisions.append(m.group(1))
        assert head in revisions and head == sorted(revisions)[-1]

    def test_setup_stamps_after_the_schema_is_in_place(self):
        src = open(os.path.join(PROJECT_ROOT, "tools", "db_setup.py"), encoding="utf-8").read()
        main = src[src.index("def main"):src.index("def _alembic_head")]
        assert main.index("_add_missing_columns(") < main.index("_stamp_head(eng)")

    def _stamped(self, tmp_path, version):
        eng = sa.create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
        if version is not None:
            with eng.begin() as cx:
                cx.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) "
                                   "NOT NULL PRIMARY KEY)"))
                if version:
                    cx.execute(sa.text("INSERT INTO alembic_version VALUES (:v)"), {"v": version})
        from db_setup import _stamp_head
        said = _stamp_head(eng)
        with eng.connect() as cx:
            return said, [r[0] for r in cx.execute(sa.text("SELECT version_num FROM "
                                                           "alembic_version"))]

    def test_a_database_with_no_stamp_is_stamped_at_the_head(self, tmp_path):
        from db_setup import _alembic_head
        assert self._stamped(tmp_path, None)[1] == [_alembic_head()]
        (tmp_path / "empty").mkdir()
        assert self._stamped(tmp_path / "empty", "")[1] == [_alembic_head()]

    def test_an_older_revision_of_this_checkout_is_moved_to_the_head(self, tmp_path):
        from db_setup import _alembic_head
        assert self._stamped(tmp_path, "0010_text_overrides")[1] == [_alembic_head()]

    def test_a_newer_branch_s_revision_is_left_as_it_is(self, tmp_path):
        """Several branches share a database. Stamping over a revision this checkout does not
        have made Alembic apply that branch's migration again (review 2026-10-04)."""
        said, stamp = self._stamped(tmp_path, "0017_from_another_branch")
        assert stamp == ["0017_from_another_branch"] and "left as it is" in said

    def test_a_revision_before_the_foreign_key_migration_is_left_as_it_is(self, tmp_path):
        said, stamp = self._stamped(tmp_path, "0004_kb_and_plans")
        assert stamp == ["0004_kb_and_plans"] and "left as it is" in said

    def test_a_renumbered_revision_is_read_as_its_new_id(self, tmp_path):
        """`0017_input_output_names` was `0015_input_output_names` before its branch was rebased
        onto develop. A database `alembic upgrade head` stamped there is moved to the head, not
        left at an id no checkout has -- where the next `alembic upgrade head` fails."""
        from db_setup import _alembic_head
        assert self._stamped(tmp_path, "0015_input_output_names")[1] == [_alembic_head()]


# ---------------------------------------------------------------------------
# 0017: two slot kinds renamed where they are stored as data
# ---------------------------------------------------------------------------
_T0 = datetime.datetime(2026, 10, 1, 10, 0, tzinfo=datetime.timezone.utc)
_T1 = datetime.datetime(2026, 10, 5, 10, 0, tzinfo=datetime.timezone.utc)


def _stored_before_0017(eng):
    """Corrections saved under the old kind names -- and, on F3, F4 and F5, the case a plain
    rename cannot survive: the new code saved one under the new name before the upgrade, on a
    slot that already had one under the old name."""
    def row(kind, key, llm, human, *, at=_T0, orphaned=False):
        return {"version_id": "v1", "slot_kind": kind, "slot_key": key, "llm_text": llm,
                "human_text": human, "is_orphaned": orphaned, "updated_by": "u1",
                "updated_at": at, "llm_model": "m-" + llm, "llm_cache_version": 3}

    def hist(kind, key, seq, human, at=_T0):
        return {"version_id": "v1", "slot_kind": kind, "slot_key": key, "seq": seq,
                "human_text": human, "updated_by": "u1", "updated_at": at}

    def queued(kind, key, reason, source=("description", "F0"), at=_T0):
        return {"version_id": "v1", "slot_kind": kind, "slot_key": key, "reason": reason,
                "source_slot_kind": source[0], "source_slot_key": source[1],
                "requested_by": "u1", "requested_at": at}

    with eng.begin() as cx:
        cx.execute(sa.insert(s.text_overrides), [
            row("behaviourInputName", "F1", "LLM in", "Reviewed in"),
            row("behaviourOutputName", "F1", "LLM out", "Reviewed out"),
            row("description", "F1", "LLM description", "Reviewed description"),
            # F3: the old row in force, and a new-name twin saved later -- which took the old
            # correction's words for the original, as the model held them by then.
            row("behaviourInputName", "F3", "LLM original", "First fix"),
            row("inputName", "F3", "First fix", "Second fix", at=_T1),
            # F5: the old row an orphan -- not in force, so its original is not the slot's.
            row("behaviourInputName", "F5", "Stale original", "Stale fix", orphaned=True),
            row("inputName", "F5", "Fresh original", "Fresh fix", at=_T1),
        ])
        cx.execute(sa.insert(s.text_override_history), [
            hist("behaviourInputName", "F1", 1, "Reviewed in"),
            hist("behaviourOutputName", "F1", 1, "Reviewed out"),
            hist("behaviourInputName", "F3", 1, "Draft fix"),
            hist("behaviourInputName", "F3", 2, "First fix"),
            hist("inputName", "F3", 1, "Second fix", _T1),
        ])
        cx.execute(sa.insert(s.regeneration_queue), [
            queued("description", "F2", "callee F1 corrected",
                   source=("behaviourOutputName", "F1")),
            queued("behaviourInputName", "F4", "older entry"),
            queued("inputName", "F4", "newer entry", at=_T1),
        ])


def _snapshot(eng):
    """The three tables, comparable across databases."""
    out = {}
    with eng.connect() as cx:
        for t in (s.text_overrides, s.text_override_history, s.regeneration_queue):
            names = [c.name for c in t.columns if c.name != "history_id"]
            out[t.name] = sorted(tuple(str(r[n]) for n in names)
                                 for r in cx.execute(sa.select(t)).mappings())
    return out


def _kinds(eng):
    with eng.connect() as cx:
        return {k for (k,) in cx.execute(sa.text(
            "SELECT slot_kind FROM text_overrides UNION SELECT slot_kind FROM "
            "text_override_history UNION SELECT slot_kind FROM regeneration_queue UNION "
            "SELECT source_slot_kind FROM regeneration_queue"))}


def _kinds_database(tmp_path, name="kinds.db"):
    eng = sa.create_engine("sqlite:///" + str(tmp_path / name).replace("\\", "/"))
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects), {"id": "p1", "name": "P", "created_at": _T0})
        cx.execute(sa.insert(s.versions), {"id": "v1", "project_id": "p1", "version": "v1",
                                           "created_at": _T0})
    _stored_before_0017(eng)
    return eng


def _migrate(eng, direction="upgrade"):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from db_setup import _migration
    m = _migration("0017_input_output_names")
    with eng.begin() as cx:
        with Operations.context(MigrationContext.configure(cx)):
            getattr(m, direction)()


def _override(eng, kind, key):
    with eng.connect() as cx:
        return cx.execute(sa.select(s.text_overrides).where(
            s.text_overrides.c.slot_kind == kind, s.text_overrides.c.slot_key == key)).first()


class TestMigration0017RenamesTheInputOutputNameKinds:
    """`behaviourInputName` / `behaviourOutputName` are `inputName` / `outputName` from
    2026-10-05. A correction stores its kind as DATA, in three tables, and a row left under an
    old name is a correction nothing reads (REVIEW_UPDATE_HANDOVER §2.1)."""

    def test_no_old_name_is_left_anywhere(self, tmp_path):
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        assert not {"behaviourInputName", "behaviourOutputName"} & _kinds(eng)

    def test_a_correction_keeps_its_words_and_its_original(self, tmp_path):
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        r = _override(eng, "inputName", "F1")
        assert (r.llm_text, r.human_text, r.llm_model) == ("LLM in", "Reviewed in", "m-LLM in")
        assert _override(eng, "outputName", "F1").human_text == "Reviewed out"
        assert _override(eng, "description", "F1").human_text == "Reviewed description"

    def test_both_names_on_one_slot_merge_like_a_second_save(self, tmp_path):
        """The newer row keeps the reviewer's words and takes the original from the older one,
        which goes. Renamed as it is, the older row breaks the unique key and stops the
        migration; left behind, it is a correction under a kind nothing reads."""
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        r = _override(eng, "inputName", "F3")
        assert (r.human_text, r.llm_text, r.llm_model) == (
            "Second fix", "LLM original", "m-LLM original")
        with eng.connect() as cx:
            n = cx.execute(sa.select(sa.func.count()).select_from(s.text_overrides)
                           .where(s.text_overrides.c.slot_key == "F3")).scalar()
        assert n == 1

    def test_an_orphans_original_is_not_taken(self, tmp_path):
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        r = _override(eng, "inputName", "F5")
        assert (r.human_text, r.llm_text) == ("Fresh fix", "Fresh original")

    def test_the_history_becomes_one_list_oldest_first(self, tmp_path):
        """`seq` counts per slot: the newer edits move past the older ones' last."""
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        h = s.text_override_history
        with eng.connect() as cx:
            got = cx.execute(sa.select(h.c.seq, h.c.human_text)
                             .where(h.c.slot_kind == "inputName", h.c.slot_key == "F3")
                             .order_by(h.c.seq)).fetchall()
        assert [tuple(r) for r in got] == [(1, "Draft fix"), (2, "First fix"),
                                           (3, "Second fix")]

    def test_the_queue_keeps_one_entry_per_slot(self, tmp_path):
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        q = s.regeneration_queue
        with eng.connect() as cx:
            f4 = cx.execute(sa.select(q.c.slot_kind, q.c.reason)
                            .where(q.c.slot_key == "F4")).fetchall()
            f2 = cx.execute(sa.select(q.c.source_slot_kind)
                            .where(q.c.slot_key == "F2")).scalar()
        assert [tuple(r) for r in f4] == [("inputName", "newer entry")]
        assert f2 == "outputName"

    def test_running_it_again_changes_nothing(self, tmp_path):
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        once = _snapshot(eng)
        _migrate(eng)
        assert _snapshot(eng) == once

    def test_downgrade_puts_the_old_names_back(self, tmp_path):
        eng = _kinds_database(tmp_path)
        _migrate(eng)
        _migrate(eng, "downgrade")
        assert not {"inputName", "outputName"} & _kinds(eng)
        assert _override(eng, "behaviourInputName", "F1").human_text == "Reviewed in"

    def test_setup_does_exactly_what_the_migration_does(self, tmp_path, monkeypatch):
        """`analyzer.py setup` upgrades a database Alembic never stamped, with the migration's
        own statements: the two databases come out identical, and stay so on a re-run."""
        import db_setup
        by_alembic = _kinds_database(tmp_path, "alembic.db")
        _migrate(by_alembic)
        by_setup = _kinds_database(tmp_path, "setup.db")
        monkeypatch.setenv("DATABASE_URL", str(by_setup.url))
        monkeypatch.setattr(sys, "argv", ["db_setup.py"])
        assert db_setup.main() == 0
        assert _snapshot(by_setup) == _snapshot(by_alembic)
        assert db_setup.main() == 0
        assert _snapshot(by_setup) == _snapshot(by_alembic)

    def test_setup_renames_before_it_stamps(self):
        """Stamped first, a database would read as being at 0017 while it still held the old
        names, and `alembic upgrade head` would never rename them."""
        src = open(os.path.join(PROJECT_ROOT, "tools", "db_setup.py"), encoding="utf-8").read()
        main = src[src.index("def main"):src.index("def _alembic_head")]
        assert main.index('_migration("0017_input_output_names")') < main.index("_stamp_head(eng)")
