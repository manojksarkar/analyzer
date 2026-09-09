"""Phase 1's macro set must be written where Phase 3 reads it.

parser.py resolves the -D flags for the run and writes them so the flowchart engine can
define exactly what the parse defined. The write was hardcoded to <repo>/model, and three
separate things were wrong with that:

  * Phase 3 READS the file from the RUN's model dir (views/flowcharts.py builds the path
    from model_dir_abs). Writing it to the repo root meant the flowchart engine never
    found it and built every CFG without the defines -- silently, since a missing file is
    simply "no macros". A version's model dir held only clang_include_paths.json.
  * <repo>/model is not tracked by git and the write does not create it, so a FRESH CLONE
    died at import with FileNotFoundError before Phase 1 could start. Existing working
    copies still had an empty model/ left from file mode, which is exactly why this
    survived: a green test run in a dirty checkout proved nothing.
  * It is shared state. run.py removed the identical hardcode for clang_include_paths.json
    because two concurrent jobs with different layer configs overwrite each other's flags;
    this one was left behind, so the loser rendered flowcharts under the wrong defines.
"""

import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, "engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _src(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _macros_write_block():
    src = _src(os.path.join("engine", "parser.py"))
    i = src.index("_macros_json = os.path.join(")
    return src[i:i + 600]


def test_written_to_the_run_model_dir_not_the_repo_root():
    block = _macros_write_block()
    assert "os.path.join(MODEL_DIR," in block
    assert "PROJECT_ROOT" not in block.split("\n")[0]


def test_the_directory_is_created_before_writing():
    """<repo>/model is untracked, so on a fresh clone nothing has made it yet."""
    block = _macros_write_block()
    assert "os.makedirs(MODEL_DIR, exist_ok=True)" in block


def test_reader_and_writer_agree():
    """The whole point: flowcharts.py reads from the run's model dir. If these two ever
    name different directories again, Phase 3 silently loses every -D flag."""
    view = _src(os.path.join("engine", "views", "flowcharts.py"))
    i = view.index("clang_macros_file = os.path.join(")
    reader = view[i:i + 200]
    assert "model_dir_abs" in reader
    assert "MODEL_DIR" in _macros_write_block()


def test_model_dir_is_resolved_after_the_model_root_flag():
    """MODEL_DIR is only the right answer because --model-root is applied before paths()
    is snapshotted. If that order is ever swapped, this write goes back to the repo root
    without anything failing."""
    src = _src(os.path.join("engine", "parser.py"))
    apply_at = src.index("apply_cli_run_context")
    snapshot_at = src.index("_p = _paths()")
    model_dir_at = src.index("MODEL_DIR = _p.model_dir")
    assert apply_at < snapshot_at < model_dir_at


def test_no_other_model_artifact_is_hardcoded_to_the_repo_root():
    """The sibling hardcode for clang_include_paths.json was removed for the same reason;
    catch a third one arriving."""
    src = _src(os.path.join("engine", "parser.py"))
    bad = re.findall(r'os\.path\.join\(PROJECT_ROOT,\s*"model"', src)
    assert not bad, "a model artifact is being written to the repo root again"
