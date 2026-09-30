"""Re-export must find the version's source wherever it is, and put it back when it is nowhere.

Phase 3 reads the C++ SOURCE again, so a re-export needs the commit on disk. It used to look in
exactly one folder and, finding nothing, answer "generate again" -- a full LLM run to recover what
is at most a git checkout. Reported from a real session, on a version whose re-export had worked a
few days earlier:

    Re-export reads the SOURCE for line numbers and flowcharts, so it needs the commit on disk.
    Generate again to restore it.

Three ways the source was there, or recoverable, and the one lookup missed it -- each tested
below with real git repositories, because the failure lives in how git and the folder names
interact, which a mock would decide in advance.
"""
import datetime
import os
import shutil
import subprocess

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

from api.db.postgres import schema as s

GIT = shutil.which("git")
pytestmark = [pytest.mark.unit,
              pytest.mark.skipif(GIT is None, reason="git is not installed")]
NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _git(*args, cwd=None):
    r = subprocess.run([GIT, "-c", "user.email=t@t", "-c", "user.name=t",
                        "-c", "init.defaultBranch=main", *args],
                       cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """A repository with 60 commits -- more than the 50 a shallow clone keeps.

    Built ONCE, with a single `git fast-import`. Committing in a loop is three git processes per
    commit, and on Windows 180 process spawns per test turned this file into a five-minute run.
    """
    d = tmp_path_factory.mktemp("upstream")
    _git("init", "--bare", str(d))
    stream = []
    for i in range(60):
        body = "int v%d;\n" % i
        msg = "c%d" % i
        stream.append("commit refs/heads/main\n"
                      "committer t <t@t> %d +0000\n"
                      "data %d\n%s\n"
                      "M 644 inline f.c\n"
                      "data %d\n%s\n" % (1700000000 + i, len(msg), msg, len(body), body))
    # BYTES, not text: text mode on Windows rewrites "\n" as "\r\n", and fast-import then reads
    # the branch name as "refs/heads/main\r" and refuses it.
    r = subprocess.run([GIT, "-C", str(d), "fast-import", "--quiet"],
                       input="".join(stream).encode("utf-8"), capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    shas = _git("-C", str(d), "rev-list", "--reverse", "main").split()
    assert len(shas) == 60
    return {"path": str(d), "url": "file:///" + str(d).replace("\\", "/"), "shas": shas}


# ---------------------------------------------------------------------------
# the git layer: a commit older than the shallow window
# ---------------------------------------------------------------------------
class TestACommitOutsideTheShallowWindow:
    """`ensure_commit_checkout` clones the newest 50 commits. Re-exporting an OLDER version --
    one generated before the branch moved on -- is exactly when its commit has left that window,
    and the checkout failed with nothing to say why."""

    def test_it_is_fetched_on_a_fresh_clone(self, repo, tmp_path):
        from incremental.clone import ensure_commit_checkout
        from incremental import git_ops
        oldest = repo["shas"][0]
        dest = str(tmp_path / "ws" / oldest[:16])
        ensure_commit_checkout(dest, repo["url"], "main", oldest)
        assert git_ops.current_commit(dest) == oldest

    def test_it_is_fetched_into_an_existing_shallow_checkout(self, repo, tmp_path):
        """A checkout that exists but lacks the commit -- another version of the same project
        was generated here first."""
        from incremental.clone import ensure_commit_checkout, shallow_clone
        from incremental import git_ops
        dest = str(tmp_path / "ws" / "shared")
        shallow_clone(repo["url"], dest, ref="main", depth=5)
        oldest = repo["shas"][0]
        assert not git_ops.commit_exists(dest, oldest), "the fixture must start without it"
        ensure_commit_checkout(dest, repo["url"], "main", oldest)
        assert git_ops.current_commit(dest) == oldest

    def test_a_commit_that_does_not_exist_says_so(self, repo, tmp_path):
        from incremental.clone import ensure_commit_checkout
        from incremental.git_ops import GitError
        dest = str(tmp_path / "ws" / "nope")
        with pytest.raises(GitError) as exc:
            ensure_commit_checkout(dest, repo["url"], "main", "0" * 40)
        assert "could not be fetched" in str(exc.value)


# ---------------------------------------------------------------------------
# finding the checkout
# ---------------------------------------------------------------------------
@pytest.fixture
def db(tmp_path, monkeypatch, repo):
    eng = sa.create_engine("sqlite:///" + str(tmp_path / "db.sqlite").replace("\\", "/"))
    s.metadata.create_all(eng)
    with eng.begin() as cx:
        cx.execute(sa.insert(s.projects).values(id="p", name="p", repo_url=repo["path"],
                                                default_branch="main", created_at=NOW))
        cx.execute(sa.insert(s.versions).values(
            id="v1", project_id="p", version="v1", commit_sha=repo["shas"][-1],
            branch="main", status="in_review", created_at=NOW))
        cx.execute(sa.insert(s.versions).values(
            id="v2", project_id="p", version="v2", status="draft", created_at=NOW))
    import core.db as core_db
    monkeypatch.setattr(core_db, "get_engine", lambda *a, **k: eng)
    monkeypatch.setattr(core_db, "is_database_configured", lambda *a, **k: True)
    return eng


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "workspaces"
    (root / "p").mkdir(parents=True)
    return str(root)


def _checkout(repo, dest, sha):
    _git("clone", "--quiet", repo["path"], dest)
    _git("checkout", "--quiet", sha, cwd=dest)


def _base_path(db, value):
    with db.begin() as cx:
        cx.execute(sa.update(s.versions).where(s.versions.c.id == "v1").values(base_path=value))


class TestFindingIt:
    def test_in_place(self, db, ws, repo):
        from incremental.source_checkout import locate_or_restore
        sha = repo["shas"][-1]
        _checkout(repo, os.path.join(ws, "p", sha[:16]), sha)
        assert locate_or_restore("p", "v1", workspaces_root=ws).how == "in place"

    def test_a_short_sha_folder(self, db, ws, repo):
        """`generate --commit 8b3e313f` names the folder from what was TYPED and records the
        full sha, so the lookup by `full[:16]` missed a folder sitting right there."""
        from incremental.source_checkout import locate_or_restore
        sha = repo["shas"][-1]
        _checkout(repo, os.path.join(ws, "p", sha[:8]), sha)
        out = locate_or_restore("p", "v1", workspaces_root=ws)
        assert out.how == "short-sha folder" and out.path.endswith(sha[:8])

    def test_another_working_copy(self, db, ws, repo, tmp_path):
        """`workspaces/` is gitignored, so a second clone of the analyzer starts with none of it
        while the shared database lists every version. `base_path` says where it really is."""
        from incremental.source_checkout import locate_or_restore
        sha = repo["shas"][-1]
        elsewhere = str(tmp_path / "other_copy" / "workspaces" / "p" / sha[:16])
        _checkout(repo, elsewhere, sha)
        _base_path(db, elsewhere)
        out = locate_or_restore("p", "v1", workspaces_root=ws)
        assert out.how == "base_path" and out.path == elsewhere

    def test_restored_when_nowhere(self, db, ws, repo):
        """A clone of one commit -- not the full LLM run "generate again" used to mean."""
        from incremental.source_checkout import locate_or_restore
        from incremental import git_ops
        out = locate_or_restore("p", "v1", workspaces_root=ws)
        assert out.how == "restored"
        assert git_ops.current_commit(out.path) == repo["shas"][-1]

    def test_restored_into_a_working_copy_with_no_workspace_at_all(self, db, tmp_path, repo):
        """The freshest case: `workspaces/<pid>/` does not exist. `Workspace(...)` raises there,
        which would have stopped the lookup before it tried anything."""
        from incremental.source_checkout import locate_or_restore
        empty_root = str(tmp_path / "fresh_clone" / "workspaces")
        assert not os.path.exists(empty_root)
        assert locate_or_restore("p", "v1", workspaces_root=empty_root).how == "restored"

    def test_a_folder_at_the_wrong_commit_is_not_used(self, db, ws, repo):
        """The right NAME with the wrong SOURCE would produce line numbers for different code,
        and nothing downstream could tell. Every candidate is verified to be AT the commit."""
        from incremental.source_checkout import locate_or_restore
        from incremental import git_ops
        sha = repo["shas"][-1]
        wrong = os.path.join(ws, "p", sha[:8])
        _checkout(repo, wrong, repo["shas"][10])           # right prefix, wrong commit
        out = locate_or_restore("p", "v1", workspaces_root=ws)
        assert out.path != wrong
        assert git_ops.current_commit(out.path) == sha


class TestSayingWhyNot:
    def test_a_reserved_version_is_named_as_never_generated(self, db, ws):
        """The user's `v2`: reserved by onboard, never generated, so it has no commit. "No commit
        recorded" was true and useless; this says what it means and what CAN be re-exported."""
        from incremental.source_checkout import SourceUnavailable, locate_or_restore
        with pytest.raises(SourceUnavailable) as exc:
            locate_or_restore("p", "v2", workspaces_root=ws)
        msg = str(exc.value)
        assert "never generated" in msg and "v1" in msg

    def test_an_unknown_version_lists_the_real_ones(self, db, ws):
        from incremental.source_checkout import SourceUnavailable, locate_or_restore
        with pytest.raises(SourceUnavailable) as exc:
            locate_or_restore("p", "v9", workspaces_root=ws)
        assert "v1" in str(exc.value)

    def test_no_repository_recorded(self, db, ws):
        from incremental.source_checkout import SourceUnavailable, locate_or_restore
        with db.begin() as cx:
            cx.execute(sa.update(s.projects).values(repo_url=None))
        with pytest.raises(SourceUnavailable) as exc:
            locate_or_restore("p", "v1", workspaces_root=ws)
        assert "no repository recorded" in str(exc.value)


class TestBothFrontDoorsUseIt:
    """The export guard taught this once already: a rule in `analyzer.py` only protects the
    terminal. The API's re-export spawns run.py directly and must resolve the source the same way."""

    def test_the_cli(self):
        src = open(os.path.join(PROJECT_ROOT, "analyzer.py"), encoding="utf-8").read()
        body = src[src.index("def _checkout_for"):src.index("def cmd_status")]
        assert "locate_or_restore(" in body
        assert "Generate again to restore it" not in body

    def test_the_api(self):
        src = open(os.path.join(PROJECT_ROOT, "api", "services", "pipeline_runner.py"),
                   encoding="utf-8").read()
        body = src[src.index("def _do_reexport"):src.index("def _do_reexport") + 4000]
        assert "locate_or_restore(" in body

    def test_the_api_no_longer_demands_a_model_folder_on_disk(self):
        """The model is ROWS; run.py asks the repository. A disk check refused every re-export
        on a host that had not generated the version itself."""
        src = open(os.path.join(PROJECT_ROOT, "api", "services", "pipeline_runner.py"),
                   encoding="utf-8").read()
        body = src[src.index("def _do_reexport"):src.index("def _do_reexport") + 4000]
        assert "Version model not found" not in body
