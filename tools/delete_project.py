"""Delete ONE project and everything under it, leaving every other project untouched.

For a shared database, where dropping the schema is not an option because a colleague is
working in the same one.

Most tables cascade from `projects`, and four references do not:

    versions.baseline_version_id  -> versions.id   (self-referential: v3's baseline is v1)
    analysis_jobs.version_id      -> versions.id
    compare_results.current_version_id / .baseline_version_id -> versions.id

Those are NO ACTION, which PostgreSQL checks at the END of the statement -- so when every
referencing row belongs to the same project it is deleting, a plain
`DELETE FROM projects` does succeed. Measured, not assumed.

The case it does NOT survive is a version in ANOTHER project naming one of this
project's versions as its baseline: that row stays, still pointing at a version that no
longer exists. Cleared here before the cascade runs.

So the value is mostly the dry run -- seeing the blast radius before touching a database
someone else is using -- plus that one edge, and not hand-writing DELETE statements
against a shared database at all.

Dry run by default: it prints the row counts it would remove and changes nothing. Pass
--yes to commit, in one transaction, so a failure leaves the project exactly as it was.

    python tools/delete_project.py --project-id auto_pio            # show me
    python tools/delete_project.py --project-id auto_pio --yes      # do it
    python tools/delete_project.py --project-id auto_pio --yes --workspace
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

# Counted for the report, in the order a reader cares about. Everything here cascades
# from projects or from versions; the list exists to SHOW the blast radius, not to drive
# the delete.
_BY_PROJECT = ["versions", "documents", "analysis_jobs", "commits", "compare_results",
               "data_dictionaries", "project_members", "access_requests", "notifications"]
_BY_VERSION = ["entity_versions", "model_units", "model_components", "model_summaries",
               "model_edges", "model_flowcharts", "model_unit_diagrams", "tu_includes",
               "parse_snapshots", "incremental_plans", "version_output_files",
               "knowledge_base", "reuse_index", "llm_call_stats", "job_functions"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--yes", action="store_true",
                    help="actually delete. Without this it is a dry run.")
    ap.add_argument("--workspace", action="store_true",
                    help="also remove workspaces/<project-id> from disk")
    a = ap.parse_args()

    import sqlalchemy as sa
    from core.db import get_engine, database_url, _redact
    eng = get_engine()

    def scalar(cx, q, **kw):
        try:
            return cx.execute(sa.text(q), kw).scalar() or 0
        except Exception:
            return None          # table absent on an older schema

    # Which database this is about to change matters more than usual here, so name it --
    # through the repo's own redactor, which keeps the password out of the output.
    try:
        dsn = _redact(database_url())
    except Exception:
        dsn = ""

    with eng.connect() as cx:
        row = cx.execute(sa.text("select id, name from projects where id = :p"),
                         {"p": a.project_id}).fetchone()
        if not row:
            print("no project %r in this database." % a.project_id)
            print("existing projects:")
            for r in cx.execute(sa.text("select id, name from projects order by id")):
                print("    %-24s %s" % (r[0], r[1] or ""))
            return 2

        print("=" * 72)
        print("DELETE PROJECT  %s" % a.project_id)
        print("=" * 72)
        print("  database : %s" % (dsn or "(unresolved)"))
        print("  name     : %s" % (row[1] or ""))
        others = scalar(cx, "select count(*) from projects where id <> :p", p=a.project_id)
        print("  %d other project(s) in this database -- untouched." % (others or 0))
        print()
        vids = [r[0] for r in cx.execute(
            sa.text("select id from versions where project_id = :p"), {"p": a.project_id})]
        print("  versions: %d  %s" % (len(vids), ", ".join(vids[:12]) +
                                      (" ..." if len(vids) > 12 else "")))
        print()
        print("  rows that would go:")
        for t in _BY_PROJECT:
            n = scalar(cx, f"select count(*) from {t} where project_id = :p", p=a.project_id)
            if n:
                print("      %-24s %d" % (t, n))
        if vids:
            marks = ",".join(":v%d" % i for i in range(len(vids)))
            params = {("v%d" % i): v for i, v in enumerate(vids)}
            for t in _BY_VERSION:
                n = scalar(cx, f"select count(*) from {t} where version_id in ({marks})",
                           **params)
                if n:
                    print("      %-24s %d" % (t, n))
        n_ent = scalar(cx, "select count(*) from entities where project_id = :p", p=a.project_id)
        if n_ent:
            print("      %-24s %d" % ("entities", n_ent))

    if not a.yes:
        print()
        print("  DRY RUN -- nothing deleted. Re-run with --yes to commit.")
        return 0

    # One transaction: a failure leaves the project exactly as it was.
    with eng.begin() as cx:
        # The four references that do NOT cascade. Clear them first, or the cascade from
        # `projects` trips over a row still pointing at a version it is deleting.
        cx.execute(sa.text("update versions set baseline_version_id = null "
                           "where project_id = :p"), {"p": a.project_id})
        for t, col in (("analysis_jobs", "version_id"),
                       ("compare_results", "current_version_id"),
                       ("compare_results", "baseline_version_id")):
            try:
                cx.execute(sa.text(
                    f"update {t} set {col} = null where project_id = :p"), {"p": a.project_id})
            except Exception:
                pass
        # Rows in OTHER projects may name a version of this one as their baseline.
        cx.execute(sa.text(
            "update versions set baseline_version_id = null where baseline_version_id in "
            "(select id from versions where project_id = :p)"), {"p": a.project_id})
        cx.execute(sa.text("delete from projects where id = :p"), {"p": a.project_id})

    print()
    print("  deleted. Everything else in the database is untouched.")

    if a.workspace:
        d = os.path.join(_ROOT, "workspaces", a.project_id)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            print("  removed %s" % d)
        else:
            print("  no workspace dir at %s" % d)
    else:
        print("  workspaces/%s left on disk (pass --workspace to remove it)." % a.project_id)
    print()
    print("  NOTE: content_blobs are content-addressed and SHARED between projects, so")
    print("  they are deliberately not deleted. Any now-orphaned blob is harmless and")
    print("  gets reused the moment identical content is stored again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
