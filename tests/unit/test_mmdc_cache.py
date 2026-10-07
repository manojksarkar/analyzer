"""Unit tests for the content-addressed Mermaid->PNG cache (M-A, src/utils.py)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "engine"))

import utils  # noqa: E402


def test_key_stable_and_sensitive():
    k = utils.mermaid_cache_key("graph TD; A-->B", scale=2)
    assert k == utils.mermaid_cache_key("graph TD; A-->B", scale=2)       # stable
    assert k != utils.mermaid_cache_key("graph TD; A-->C", scale=2)       # text-sensitive
    assert k != utils.mermaid_cache_key("graph TD; A-->B", scale=3)       # opt-sensitive


def test_cache_hit_skips_mmdc(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_run(project_root, mermaid, png_path, *, scale=None, puppeteer=True, timeout=90):
        calls["n"] += 1
        os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
        with open(png_path, "wb") as f:
            f.write(b"PNG:" + (mermaid or "").encode())
        return True

    monkeypatch.setattr(utils, "_run_mmdc", fake_run)
    proj = str(tmp_path)
    a, b, c = (os.path.join(proj, "out", n) for n in ("a.png", "b.png", "c.png"))

    assert utils.render_mermaid_cached(proj, "graph TD; A-->B", a) is True
    assert calls["n"] == 1                                   # miss -> one render

    assert utils.render_mermaid_cached(proj, "graph TD; A-->B", b) is True
    assert calls["n"] == 1                                   # HIT -> no extra mmdc
    assert open(a, "rb").read() == open(b, "rb").read()      # identical bytes from cache

    assert utils.render_mermaid_cached(proj, "graph TD; X-->Y", c) is True
    assert calls["n"] == 2                                   # different diagram -> render


def test_failed_render_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "_run_mmdc", lambda *a, **k: False)
    proj = str(tmp_path)
    assert utils.render_mermaid_cached(proj, "graph TD; A-->B", os.path.join(proj, "x.png")) is False
    cache = os.path.join(proj, ".mmdc_cache")
    assert not os.path.isdir(cache) or not os.listdir(cache)   # nothing cached on failure


def _fake_picture(calls):
    def draw(project_root, text, png_path, **_kw):
        calls.append(project_root)
        os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
        with open(png_path, "wb") as f:
            f.write(b"PNG:" + (text or "").encode())
        return True
    return draw


class TestTheCachesAreTheInstallations:
    """FAST_WORD_FILE_UPDATES P3. A detached run works from a copy of the code
    (`runs/<version>/<time>/code`) that leaves the caches out; looked up beside that copy, every
    run started empty and drew every picture again -- 28 flowcharts to change one label. The
    caches belong to the installation's data root, which a detached run is given."""

    def test_without_a_data_root_the_cache_is_beside_the_code(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANALYZER_DATA_ROOT", raising=False)
        assert utils.picture_cache_dir(str(tmp_path), ".dot_cache") == os.path.join(str(tmp_path), ".dot_cache")

    def test_two_code_copies_share_the_mermaid_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANALYZER_DATA_ROOT", str(tmp_path / "data"))
        calls = []
        monkeypatch.setattr(utils, "_run_mmdc", _fake_picture(calls))
        first, second = (str(tmp_path / "runs" / v / "code") for v in ("v1", "v2"))
        assert utils.render_mermaid_cached(first, "graph TD; A-->B", str(tmp_path / "o1" / "a.png"))
        assert utils.render_mermaid_cached(second, "graph TD; A-->B", str(tmp_path / "o2" / "a.png"))
        assert calls == [first]                                   # drawn once, by the first run
        assert len(os.listdir(tmp_path / "data" / ".mmdc_cache")) == 1
        assert not os.path.exists(os.path.join(first, ".mmdc_cache"))

    def test_two_code_copies_share_the_flowchart_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANALYZER_DATA_ROOT", str(tmp_path / "data"))
        calls = []
        monkeypatch.setattr(utils, "_run_dot_render", _fake_picture(calls))
        first, second = (str(tmp_path / "runs" / v / "code") for v in ("v1", "v2"))
        dot = "digraph { a -> b }"
        assert utils.render_dot_cached(first, dot, str(tmp_path / "o1" / "f.png"))
        assert utils.render_dot_cached(second, dot, str(tmp_path / "o2" / "f.png"))
        assert calls == [first]
        assert len(os.listdir(tmp_path / "data" / ".dot_cache")) == 1

    def test_the_behaviour_view_draws_a_diagram_once_across_runs(self, tmp_path, monkeypatch):
        """It ran mmdc itself and never looked in a cache: every Phase 3 drew every behaviour
        diagram again. Now it shares the Mermaid cache, keyed as `render_mermaid_cached` keys
        the same text."""
        import subprocess
        from views import behaviour_diagram as view
        monkeypatch.setenv("ANALYZER_DATA_ROOT", str(tmp_path / "data"))
        drawn = []

        def fake_mmdc(cmd):
            out = cmd[cmd.index("-o") + 1]
            drawn.append(out)
            with open(out, "wb") as f:
                f.write(b"PNG")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        monkeypatch.setattr(view, "_render_png", fake_mmdc)
        target, caller = "Beta|Target|betaCompute|int", "Alpha|Caller|alphaRun|int"
        model = {
            "components": {"Alpha": {"units": ["Alpha|Caller"]}, "Beta": {"units": ["Beta|Target"]}},
            "units": {"Alpha|Caller": {"name": "Caller", "functionIds": [caller]},
                      "Beta|Target": {"name": "Target", "functionIds": [target]}},
            "functions": {target: {"qualifiedName": "betaCompute", "calledByIds": [caller],
                                   "callsIds": [], "visibility": "public"},
                          caller: {"qualifiedName": "alphaRun", "calledByIds": [],
                                   "callsIds": [target], "visibility": "public"}},
        }
        config = {"views": {"behaviourDiagram": True, "sequenceDiagrams": {"filterMode": "all_callers"}},
                  "llm": {"descriptions": False}}
        for run_dir in ("run1", "run2"):
            view.run(model, str(tmp_path / run_dir), str(tmp_path / "model"), config)
        assert len(drawn) == 1                                     # the second run copied it
        rows = __import__("json").load(open(tmp_path / "run2" / "behaviour_diagrams" / "_behaviour_pngs.json"))
        [row] = rows["_docxRows"]["Beta"]["Target"]
        assert row["pngPath"] and os.path.isfile(row["pngPath"])
        assert len(os.listdir(tmp_path / "data" / ".mmdc_cache")) == 1
