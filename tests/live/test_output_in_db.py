"""Is every text file under output/ actually IN the database?

The files being on disk proves nothing: `PgStore.capture_output` writes them to disk
first and persists to Postgres second, and that second step is wrapped in a bare
`except Exception: pass` ("best-effort -- disk output is intact"). A failure there leaves
a complete-looking output directory and an empty `version_output_files`, silently.

That matters for anything that reads the model from the database rather than the disk --
the API, the HTML view, and any future edit feature. Disk and database can disagree and
nothing reports it.

PNG and DOCX are excluded on purpose (D-14): binaries stay as files.
"""
import os

import pytest

pytestmark = pytest.mark.live

# What persist_output_files stores. Anything else under output/ is deliberately a file.
TEXT_EXTS = (".json", ".mmd", ".txt", ".md", ".csv", ".dot", ".svg", ".html")
BINARY_EXTS = (".png", ".docx")


def _disk_text_files(project_id, vid):
    """{posix rel path under output/} for every text file on disk."""
    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "workspaces", project_id, "versions", vid, "output")
    if not os.path.isdir(root):
        return None, root
    out = set()
    for base, _d, files in os.walk(root):
        for f in files:
            if f.lower().endswith(TEXT_EXTS):
                rel = os.path.relpath(os.path.join(base, f), root)
                out.add(rel.replace("\\", "/"))
    return out, root


class TestEveryTextOutputReachedTheDatabase:
    def test_the_version_stored_any_output_at_all(self, db, vid):
        n = db.scalar("select count(*) from version_output_files where version_id = :v", v=vid)
        assert n, (
            "%s: version_output_files is EMPTY.\n"
            "capture_output persists these, and its database write is best-effort -- it "
            "swallows every exception. An empty table with output on disk means that write "
            "failed and nothing said so. The API and the HTML view read from here, so this "
            "version has no views for them." % vid)

    def test_no_text_file_on_disk_is_missing_from_the_database(self, db, project_id, vid):
        disk, root = _disk_text_files(project_id, vid)
        if disk is None:
            pytest.skip("no output directory on this machine for %s (%s)" % (vid, root))
        if not disk:
            pytest.skip("%s: output directory holds no text files" % vid)
        stored = {(r[0] or "").replace("\\", "/") for r in db.rows(
            "select rel_path from version_output_files where version_id = :v", v=vid)}
        missing = sorted(disk - stored)
        assert not missing, (
            "%s: %d of %d text file(s) under output/ have no database row.\n"
            "Disk and database disagree, and capture_output's persist step swallows its "
            "own failures, so nothing reported it. Anything reading from the database -- "
            "the API, the HTML view -- cannot see these.\n      %s"
            % (vid, len(missing), len(disk), "\n      ".join(missing[:10])))

    def test_no_database_row_is_missing_from_disk(self, db, project_id, vid):
        """The other direction: a row for a file the run did not produce is stale.

        version_output_files is replaced per version on each capture, so a leftover row
        means a file that existed in an earlier render and does not now -- the document
        would still show it.
        """
        disk, _root = _disk_text_files(project_id, vid)
        if disk is None:
            pytest.skip("no output directory on this machine for %s" % vid)
        stored = {(r[0] or "").replace("\\", "/") for r in db.rows(
            "select rel_path from version_output_files where version_id = :v", v=vid)}
        if not stored:
            pytest.skip("%s stored no output files" % vid)
        extra = sorted(stored - disk)
        assert not extra, (
            "%s: %d database row(s) name a file that is not on disk.\n      %s"
            % (vid, len(extra), "\n      ".join(extra[:10])))


class TestTheEditableTextIsReachable:
    """Every LLM-written string a review feature would edit must be addressable.

    Flowchart node labels are the one that is easy to get wrong: the stored `flowchart`
    field is a RENDERING (Graphviz DOT), and editing it would be editing generated syntax.
    The label lives in `cfg.nodes[].label`, which the SWE.4 port started storing beside it
    -- that is the thing to edit, with the DOT, the PNG and the Test Steps all re-derived
    from it.
    """

    def test_stored_flowcharts_carry_their_cfg(self, db, vid):
        import json
        rows = db.rows(
            "select rel_path, content from version_output_files "
            "where version_id = :v and rel_path like '%flowcharts%'", v=vid)
        if not rows:
            pytest.skip("%s stored no flowchart output" % vid)
        with_cfg = without = 0
        examples = []
        for rel, content in rows:
            try:
                arr = json.loads(content)
            except Exception:
                continue
            for e in (arr if isinstance(arr, list) else []):
                if not e.get("flowchart"):
                    continue
                if (e.get("cfg") or {}).get("nodes"):
                    with_cfg += 1
                else:
                    without += 1
                    if len(examples) < 8:
                        examples.append("%s :: %s" % (rel, e.get("name", "?")))
        if not (with_cfg or without):
            pytest.skip("%s: no flowchart entries to check" % vid)
        assert not without, (
            "%s: %d of %d flowchart(s) have a rendering but no cfg.\n"
            "`flowchart` is Graphviz DOT -- generated syntax. The editable text is "
            "`cfg.nodes[].label`, and without the cfg there is nothing to edit and no way "
            "to re-derive the DOT, the PNG or the SWE.4 Test Steps from a correction.\n"
            "      %s" % (vid, without, with_cfg + without, "\n      ".join(examples)))
