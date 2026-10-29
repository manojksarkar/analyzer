"""A command-line run writes the live log (docs/spec/LIVE_LOGS_SPEC.md REQ-LL-01, -02).

The e2e pipeline is `analyzer.py generate --doc-type all`: every step is a process of its own,
and each must write records under the run's project and version, marked with its step, into
`<data root>/logs/live/`.
"""
import datetime as dt
import glob
import json
import os

from tests.e2e_paths import E2E_PID, E2E_VERSION_ID

from core.logging_setup import live_log_root

STEPS = {"Parse", "Derive", "Views", "Export SWE.3", "Export SWE.4"}


def _records_of_this_run():
    since = dt.datetime.now().astimezone() - dt.timedelta(hours=3)
    today = dt.date.today()
    for day in (today - dt.timedelta(days=1), today):
        for path in glob.glob(os.path.join(live_log_root(), day.isoformat(), "engine-*.jsonl")):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("version") == E2E_VERSION_ID and \
                            dt.datetime.fromisoformat(rec["ts"]) >= since:
                        yield rec


def test_every_step_of_the_run_writes_live_records(run_pipeline):
    records = list(_records_of_this_run())
    assert {r.get("step") for r in records} >= STEPS, sorted({str(r.get("step")) for r in records})
    # The project where the process is told it: the flowchart engine, which the flowcharts view
    # starts, gets the version only (a web run's lines then take the project from their job).
    assert all(r.get("project", E2E_PID) == E2E_PID and r["source"] == "engine" for r in records)


def test_the_run_records_its_server_settings_with_the_version(run_pipeline):
    """`output/_run_settings.json` (run.py `_record_run_settings`): one entry per run with this
    server's settings -- on disk, and in the database, where `analyzer.py runs` reads it."""
    from tests.e2e_paths import OUTPUT_DIR
    from core.config import RUN_SETTINGS_FILE
    from core.db import get_engine
    from sqlalchemy import select
    from api.db.postgres import schema as s
    with open(os.path.join(OUTPUT_DIR, RUN_SETTINGS_FILE), encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert on_disk and all({"at", "phases", "llmServer", "speedups", "llvm"} <= set(e) for e in on_disk)
    assert all(e["llmServer"]["apiKey"] in ("set", "none") for e in on_disk)
    vof = s.version_output_files
    with get_engine().connect() as cx:
        stored = cx.execute(select(vof.c.content, vof.c.group_name).where(
            vof.c.version_id == E2E_VERSION_ID, vof.c.rel_path == RUN_SETTINGS_FILE)).first()
    assert stored is not None and json.loads(stored.content) == on_disk
    assert stored.group_name is None          # no component's: listings and component saves skip it
