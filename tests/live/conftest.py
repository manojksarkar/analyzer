"""Live-database tests: read a REAL project's rows and assert what must be true of them.

Run against a database that already holds a generated project. Nothing here writes: every
connection is opened with `connect()`, never `begin()`, so a test cannot commit even by
mistake.

    python -m pytest tests/live --project-id vis-aspice1 -v
    python -m pytest tests/live --project-id P --live-versions v5,v7 -v
    python -m pytest tests/live --project-id P -v -k hash

Why a pytest suite rather than another audit script: one line per assertion with its own
name, `-k` to run a subset while chasing one thing, and a failure that names the invariant
instead of a paragraph to read. The audit tool answers "is this project healthy"; this
answers "which specific invariant is broken", which is the question that leads to a fix.

Skipped, never passed, when a precondition is absent -- a version with no flowchart output
cannot prove anything about flowcharts, and saying so is the point. An empty check is not a
pass; that mistake has cost this project two real runs.
"""
from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "engine")]


def pytest_addoption(parser):
    parser.addoption("--project-id", action="store", default=None,
                     help="the project to audit. Without it the live suite is skipped.")
    parser.addoption("--live-versions", action="store", default=None,
                     help="comma-separated version ids; default every version")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: reads a real database")


def _project_id(config):
    return config.getoption("--project-id")


# ---------------------------------------------------------------------------
# one connection, read-only, shared by every test
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def eng(request):
    pid = _project_id(request.config)
    if not pid:
        pytest.skip("live suite needs --project-id")
    try:
        from core.db import get_engine, is_database_configured
        if not is_database_configured():
            pytest.skip("no database is configured (DATABASE_URL or the config db section)")
        return get_engine()
    except Exception as exc:                       # pragma: no cover - environment
        pytest.skip("cannot reach the database: %s" % exc)


@pytest.fixture(scope="session")
def project_id(request):
    pid = _project_id(request.config)
    if not pid:
        pytest.skip("live suite needs --project-id")
    return pid


@pytest.fixture(scope="session")
def db(eng):
    """Read-only query helpers. `connect()`, not `begin()` -- nothing here can commit."""
    import sqlalchemy as sa

    class DB:
        def rows(self, q, **params):
            with eng.connect() as cx:
                return cx.execute(sa.text(q), params).fetchall()

        def scalar(self, q, **params):
            with eng.connect() as cx:
                return cx.execute(sa.text(q), params).scalar()

        def engine(self):
            return eng

    return DB()


@pytest.fixture(scope="session")
def versions(db, project_id, request):
    """[{id, commit, decision, baseline, status}] oldest first, honouring --live-versions."""
    rows = db.rows("select id, commit_sha, decision, baseline_version_id, pipeline_status "
                   "from versions where project_id = :p order by created_at", p=project_id)
    out = [dict(id=r[0], commit=r[1], decision=r[2], baseline=r[3], status=r[4]) for r in rows]
    only = request.config.getoption("--live-versions")
    if only:
        keep = {v.strip() for v in only.split(",") if v.strip()}
        out = [v for v in out if v["id"] in keep]
    if not out:
        pytest.skip("project %r has no versions (or --live-versions matched none)" % project_id)
    return out


@pytest.fixture(scope="session")
def by_id(versions):
    return {v["id"]: v for v in versions}


# ---------------------------------------------------------------------------
# model reads
# ---------------------------------------------------------------------------
_FN_SQL = (
    "select e.entity_key, v.source_hash, v.file, v.component, v.unit, v.visibility, "
    "v.direction, v.interface_id, v.content_hash, v.line, v.end_line "
    "from entity_versions v join entities e on e.entity_id = v.entity_id "
    "where v.version_id = :v and e.kind = 'function'")


@pytest.fixture(scope="session")
def functions(db):
    """vid -> {entity_key: row}. Cached: a big project has tens of thousands of rows.

    Carries no payload text, so a failure message can be pasted without shipping source
    code, doc comments or LLM output.
    """
    cache = {}

    def get(vid):
        if vid not in cache:
            cache[vid] = {r[0]: dict(hash=r[1], file=r[2], component=r[3], unit=r[4],
                                     visibility=r[5], direction=r[6], interface_id=r[7],
                                     content_hash=r[8], line=r[9], end_line=r[10])
                          for r in db.rows(_FN_SQL, v=vid)}
        return cache[vid]

    return get


@pytest.fixture(scope="session")
def real_functions(functions):
    """Only the rows with a payload.

    A row with a source_hash and NO payload is a HASH-ONLY entity and is deliberate:
    `persist_bare_entities` writes one for a hashed entity outside the model -- a
    file-scope macro, or a function outside the generated scope -- so `classify` still sees
    its hash next run, and `load_functions` skips it ("not a real function"). Auditing those
    for a file or a component produced 2818 spurious failures once already.
    """
    def get(vid):
        return {k: f for k, f in functions(vid).items() if f["content_hash"]}
    return get


@pytest.fixture(scope="session")
def bare_functions(functions):
    """Only the hash-only rows -- the complement of `real_functions`."""
    def get(vid):
        return {k: f for k, f in functions(vid).items() if not f["content_hash"]}
    return get


@pytest.fixture(scope="session")
def flowchart_dots(db):
    """vid -> {(unit, funcName): dot} from version_output_files.

    The STORED copy, which is what the API serves -- not the disk copy the DOCX embedded.
    Tests that care about the difference read both.
    """
    import json
    cache = {}

    def get(vid):
        if vid in cache:
            return cache[vid]
        out = {}
        for rel, content in db.rows(
                "select rel_path, content from version_output_files where version_id = :v",
                v=vid):
            rel = (rel or "").replace("\\", "/")
            if "/flowcharts/" not in rel or not rel.endswith(".json"):
                continue
            unit = os.path.basename(rel)[:-5]
            try:
                arr = json.loads(content)
            except Exception:
                continue
            for e in (arr if isinstance(arr, list) else []):
                n = (e.get("name") or "").strip()
                if n:
                    out[(unit, n)] = e.get("flowchart") or ""
        cache[vid] = out
        return out

    return get


@pytest.fixture(scope="session")
def version_pngs(project_id):
    """vid -> {png filename: md5}. PNGs are files by design (D-14), never rows."""
    import hashlib
    cache = {}

    def get(vid):
        if vid in cache:
            return cache[vid]
        out = {}
        base = os.path.join(PROJECT_ROOT, "workspaces", project_id, "versions", vid, "output")
        if os.path.isdir(base):
            for root, _d, files in os.walk(base):
                if os.path.basename(root) != "flowcharts":
                    continue
                for f in files:
                    if f.endswith(".png"):
                        p = os.path.join(root, f)
                        out[f] = hashlib.md5(open(p, "rb").read()).hexdigest()[:10]
        cache[vid] = out
        return out

    return get


# ---------------------------------------------------------------------------
# every test that takes `vid` runs once PER VERSION, so a failure names the version
# ---------------------------------------------------------------------------
def pytest_generate_tests(metafunc):
    if "vid" not in metafunc.fixturenames:
        return
    pid = _project_id(metafunc.config)
    if not pid:
        metafunc.parametrize("vid", [], ids=[])
        return
    try:
        from core.db import get_engine, is_database_configured
        import sqlalchemy as sa
        if not is_database_configured():
            metafunc.parametrize("vid", [], ids=[])
            return
        with get_engine().connect() as cx:
            ids = [r[0] for r in cx.execute(sa.text(
                "select id from versions where project_id = :p order by created_at"),
                {"p": pid})]
    except Exception:
        ids = []
    only = metafunc.config.getoption("--live-versions")
    if only:
        keep = {v.strip() for v in only.split(",") if v.strip()}
        ids = [v for v in ids if v in keep]
    metafunc.parametrize("vid", ids, ids=ids or None)
