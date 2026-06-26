"""Unit tests for the content-addressed Mermaid->PNG cache (M-A, src/utils.py)."""
import os
import sys

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

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
