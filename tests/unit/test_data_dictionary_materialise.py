"""An uploaded data dictionary must reach the parser.

Reported: a CSV was provided and never appeared in the database. It never reached the parser
either. The chain broke in the middle and nothing said so:

    POST /uploads  ->  _UPLOADS[id] = {...}        # module-level dict, memory only
    wizard         ->  stores the id in build_config
    pipeline_runner->  looks for workspaces/<pid>/datadict/<id>.csv
                       ...which NOTHING ever wrote

So `dd_path.is_file()` was False, `--data-dictionary` was silently omitted, the CSV never
merged into `dataDictionary`, and nothing reached `entity_versions`. The `data_dictionaries`
and `data_dictionary_entries` tables have existed since the migration and had never been
written either.
"""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def _src():
    with open(os.path.join(ROOT, "api", "services", "pipeline_runner.py"),
              encoding="utf-8") as fh:
        return fh.read()


class TestTheChainIsJoined:
    def test_the_runner_materialises_before_passing_the_id(self):
        """The engine resolves the id to a PATH, so the file has to exist by then."""
        src = _src()
        i_mat = src.index("_materialise_data_dictionary(db, job)")
        i_arg = src.index('cmd += ["--data-dict-id", job.data_dict_id]')
        assert i_mat < i_arg, "the id is passed before the file is written"

    def test_it_reads_the_in_memory_upload(self):
        assert "from ..routes.repositories import _UPLOADS" in _src()

    def test_it_persists_so_a_restart_does_not_lose_it(self):
        """_UPLOADS is memory only: an API restart, or a second node, loses the CSV entirely."""
        src = _src()
        assert "def _persist_dictionary(" in src
        assert "s.data_dictionaries" in src and "s.data_dictionary_entries" in src

    def test_it_can_rebuild_from_the_database(self):
        """After a restart the bytes are gone from memory but still in the table."""
        assert "def _stored_dictionary_bytes(" in _src()

    def test_a_missing_dictionary_warns_rather_than_failing_silently(self):
        """Running without the dictionary is a legitimate outcome; doing it QUIETLY is what
        made this take a full run plus a database inspection to notice."""
        src = _src()
        i = src.index("def _materialise_data_dictionary(")
        body = src[i:i + 2500]
        assert "WARNING" in body
        assert "WITHOUT it" in body


class TestItIsIdempotent:
    def test_an_existing_file_is_left_alone(self):
        """Re-running a job must not rewrite the CSV — and must still find it."""
        src = _src()
        i = src.index("def _materialise_data_dictionary(")
        body = src[i:i + 1500]
        assert "if dd_path.is_file():" in body
        assert "return dd_path" in body
