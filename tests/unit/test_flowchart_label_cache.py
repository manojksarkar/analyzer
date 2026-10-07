"""Node labels are cached by CONTENT (the pipeline's largest unbounded LLM cost).

Nothing cached these. Every run re-labelled every function, so at a gateway admitting one call
per three seconds a 14-flowchart component spent 225 seconds waiting on the LLM — and spent it
again on the next run with not a line changed. Descriptions had a cache since M-B; labels never
did, which made flowcharts the most expensive phase by a wide margin.

The risky part is not the caching, it is applying a cached label to the WRONG node. The CFG is
derived deterministically from the source, so the source hash covers the node ids too — until
the CFG BUILDER changes, at which point ids shift while the hash does not. So the stored node-id
set is compared exactly and a mismatch re-generates rather than mislabelling a diagram, which
would be worse than the cost it saves.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [ROOT, os.path.join(ROOT, "engine"), os.path.join(ROOT, "engine", "flowchart")]

import flowchart_engine as fe          # noqa: E402
from models import NodeType             # noqa: E402


class _Node:
    def __init__(self, node_id, node_type=NodeType.ACTION, label=""):
        self.node_id, self.node_type, self.label = node_id, node_type, label


class _Cfg:
    def __init__(self, nodes):
        self.nodes = {n.node_id: n for n in nodes}


class _Cache:
    def __init__(self, data=None):
        self.data = data or {}
        self.puts = []

    def get(self, eid, ch):
        return self.data.get((eid, ch))

    def put(self, eid, ch, val, metadata=None):
        self.puts.append(val)
        self.data[(eid, ch)] = val


def _cfg():
    return _Cfg([_Node("s", NodeType.START), _Node("n1"), _Node("n2"), _Node("e", NodeType.END)])


class TestTheKey:
    def test_same_source_and_model_is_the_same_key(self):
        cfg = type("C", (), {"llm_model": "m1"})()
        assert fe._label_cache_key("int f(){}", cfg) == fe._label_cache_key("int f(){}", cfg)

    def test_changed_source_changes_the_key(self):
        cfg = type("C", (), {"llm_model": "m1"})()
        assert fe._label_cache_key("int f(){}", cfg) != fe._label_cache_key("int f(){ }", cfg)

    def test_a_different_model_changes_the_key(self):
        a = type("C", (), {"llm_model": "m1"})()
        b = type("C", (), {"llm_model": "m2"})()
        assert fe._label_cache_key("int f(){}", a) != fe._label_cache_key("int f(){}", b)


class TestApplying:
    def test_a_full_hit_fills_every_labelable_node(self, monkeypatch):
        cache = _Cache({("k", "k"): json.dumps({"n1": "do a", "n2": "do b"})})
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        cfg = _cfg()
        assert fe._apply_cached_labels(cfg, "k", None) is True
        assert cfg.nodes["n1"].label == "do a"
        assert cfg.nodes["n2"].label == "do b"

    def test_sentinels_are_not_required_in_the_payload(self):
        """START/END carry no LLM label, so they must not make every lookup a miss."""
        cache = _Cache({("k", "k"): json.dumps({"n1": "a", "n2": "b"})})
        cfg = _cfg()
        assert set(json.loads(cache.get("k", "k"))) == {"n1", "n2"}
        assert {n.node_id for n in cfg.nodes.values()
                if n.node_type in (NodeType.START, NodeType.END)} == {"s", "e"}

    def test_a_node_id_mismatch_regenerates(self, monkeypatch):
        """The guard that matters: a changed CFG builder shifts ids while the source hash is
        unchanged. Applying then would attach labels to the wrong nodes."""
        cache = _Cache({("k", "k"): json.dumps({"n1": "a", "nX": "b"})})
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        cfg = _cfg()
        assert fe._apply_cached_labels(cfg, "k", None) is False
        assert cfg.nodes["n1"].label == ""       # nothing applied

    def test_a_miss_returns_false(self, monkeypatch):
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: _Cache())
        assert fe._apply_cached_labels(_cfg(), "k", None) is False

    def test_no_cache_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: None)
        assert fe._apply_cached_labels(_cfg(), "k", None) is False

    def test_corrupt_payload_regenerates_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: _Cache({("k", "k"): "not json"}))
        assert fe._apply_cached_labels(_cfg(), "k", None) is False


class TestStoring:
    def test_it_stores_only_labelable_nodes(self, monkeypatch):
        cache = _Cache()
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        cfg = _cfg()
        cfg.nodes["n1"].label = "a"
        cfg.nodes["n2"].label = "b"
        fe._store_labels(cfg, "k", None)
        assert json.loads(cache.puts[0]) == {"n1": "a", "n2": "b"}

    def test_nothing_labelable_stores_nothing(self, monkeypatch):
        cache = _Cache()
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        fe._store_labels(_Cfg([_Node("s", NodeType.START)]), "k", None)
        assert cache.puts == []


class TestWiring:
    def test_cache_version_reaches_the_key(self):
        """Bumping llm.cacheVersion must invalidate labels as it does descriptions — it is the
        only lever for "the prompt changed, re-label everything"."""
        src = open(os.path.join(ROOT, "engine", "views", "flowcharts.py"), encoding="utf-8").read()
        assert '"--llm-cache-version"' in src
        eng = open(os.path.join(ROOT, "engine", "flowchart", "flowchart_engine.py"),
                   encoding="utf-8").read()
        assert "llm_cache_version=args.llm_cache_version" in eng
        assert 'cache_version=ver' in eng

    def test_the_run_lands_its_labels_before_it_ends(self, monkeypatch):
        """`put` buffers: a batch is written every 1,000 rows or 60 s. Nothing flushed this cache,
        so a run's last minute of labels was lost at exit and paid for again next run."""
        flushed = []
        monkeypatch.setattr(fe, "_label_cache",
                            lambda cfg: type("C", (), {"flush": lambda self: flushed.append(1)})())
        fe._flush_labels(None)
        assert flushed == [1]
        eng = open(os.path.join(ROOT, "engine", "flowchart", "flowchart_engine.py"),
                   encoding="utf-8").read()
        run = eng[eng.index("\ndef run(config"):]
        assert run.index("_flush_labels(config)") < run.index("writer.write_all(file_results)")

    def test_labels_share_the_description_cache_table(self):
        eng = open(os.path.join(ROOT, "engine", "flowchart", "flowchart_engine.py"),
                   encoding="utf-8").read()
        assert '_LABEL_NS = "flowchart_labels"' in eng
        assert "from llm_core.cache import EntityCache" in eng


class TestFallbacksAreNeverCached:
    """A timed-out LLM must not become permanent.

    When the LLM returns nothing usable the generator substitutes mechanical labels so the
    diagram still renders. Caching those would make a transient outage stick: every later run
    would hit the cache, never retry, and the flowcharts would quietly stay mechanical with no
    error anywhere.
    """

    def test_a_fallback_label_blocks_the_write(self, monkeypatch):
        """Which nodes fell back is now told to us by the generator, not guessed from the
        label text — so the test declares it the same way the generator does."""
        cache = _Cache()
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        cfg = _cfg()
        cfg.nodes["n1"].label = "Reads the sensor"
        cfg.nodes["n2"].label = "Check: x > 0"        # mechanical fallback
        fe._store_labels(cfg, "k", None, frozenset({"n2"}))
        assert cache.puts == [], "a fallback label was cached and would never be retried"

    def test_a_clean_result_is_cached(self, monkeypatch):
        cache = _Cache()
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        cfg = _cfg()
        cfg.nodes["n1"].label = "Reads the sensor"
        cfg.nodes["n2"].label = "Doubles the reading"
        fe._store_labels(cfg, "k", None)
        assert json.loads(cache.puts[0]) == {"n1": "Reads the sensor",
                                             "n2": "Doubles the reading"}

    def test_a_missing_label_blocks_the_write(self, monkeypatch):
        """Partial coverage is the same hazard: the gap would be cached as final."""
        cache = _Cache()
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        cfg = _cfg()
        cfg.nodes["n1"].label = "Reads the sensor"
        cfg.nodes["n2"].label = ""
        fe._store_labels(cfg, "k", None)
        assert cache.puts == []


class TestWritingAChartAgain:
    """FAST_WORD_FILE_UPDATES P5. The key is the source's, and a corrected description moves no
    source: a chart whose label prompts held the rejected text would get the same labels back
    from the cache for ever. A chart named for rewriting skips the cache, and its new labels
    replace the cached ones -- unless the LLM fell back on a node, when it keeps the old."""

    class _Gen:
        def __init__(self, labels, fell_back=()):
            self.labels, self.fallback_node_ids, self.calls = labels, frozenset(fell_back), 0

        def label_cfg(self, cfg, func_entry, source_code, base_path):
            self.calls += 1
            for nid, text in self.labels.items():
                cfg.nodes[nid].label = text

    class _ReplacingCache(_Cache):
        def __init__(self, data=None):
            super().__init__(data)
            self.replaced = []

        def replace(self, eid, ch, val):
            self.replaced.append(val)
            self.data[(eid, ch)] = val

    def _setup(self, monkeypatch, tmp_path, cached=None):
        from config import EngineConfig
        config = EngineConfig(functions_json_path="", metadata_json_path="", out_dir="",
                              rewrite_keys=frozenset({"K"}),
                              rewrite_report=str(tmp_path / "rewritten"))
        key = fe._label_cache_key("src", config)
        cache = self._ReplacingCache({(key, key): json.dumps(cached)} if cached else {})
        monkeypatch.setattr(fe, "_label_cache", lambda cfg: cache)
        entry = type("E", (), {"key": "K", "qualified_name": "ns::k"})()
        return config, cache, entry

    def _report(self, tmp_path):
        p = tmp_path / "rewritten"
        return p.read_text(encoding="utf-8").split() if p.exists() else []

    def test_a_named_chart_skips_the_cache_and_replaces_it(self, monkeypatch, tmp_path):
        config, cache, entry = self._setup(monkeypatch, tmp_path, {"n1": "old a", "n2": "old b"})
        gen = self._Gen({"n1": "new a", "n2": "new b"})
        cfg = _cfg()
        fe._label_chart(cfg, entry, "src", "", gen, config, None)
        assert gen.calls == 1
        assert json.loads(cache.replaced[0]) == {"n1": "new a", "n2": "new b"}
        assert self._report(tmp_path) == ["K"]

    def test_a_fallback_keeps_the_earlier_labels_and_reports_nothing(self, monkeypatch,
                                                                      tmp_path):
        config, cache, entry = self._setup(monkeypatch, tmp_path, {"n1": "old a", "n2": "old b"})
        cfg = _cfg()
        fe._label_chart(cfg, entry, "src", "", self._Gen({"n1": "new a", "n2": "Check: x"},
                                                         fell_back={"n2"}), config, None)
        assert (cfg.nodes["n1"].label, cfg.nodes["n2"].label) == ("old a", "old b")
        assert cache.replaced == [] and cache.puts == []
        assert self._report(tmp_path) == []

    def test_any_other_chart_still_comes_from_the_cache(self, monkeypatch, tmp_path):
        config, cache, _entry = self._setup(monkeypatch, tmp_path, {"n1": "old a", "n2": "old b"})
        other = type("E", (), {"key": "OTHER", "qualified_name": "ns::o"})()
        gen = self._Gen({"n1": "new a", "n2": "new b"})
        cfg = _cfg()
        fe._label_chart(cfg, other, "src", "", gen, config, None)
        assert gen.calls == 0 and cfg.nodes["n1"].label == "old a"

    def test_the_knowledge_base_is_brought_up_to_date_only_when_the_llm_writes(self,
                                                                               monkeypatch,
                                                                               tmp_path):
        """A chart's purpose, callers' and callees' descriptions come from the knowledge base,
        which Phase 2 wrote; the model's corrections go over it first -- and a run whose every
        chart is cached reads none of them, so pays nothing."""
        config, _cache, entry = self._setup(monkeypatch, tmp_path, {"n1": "a", "n2": "b"})
        seen = []
        monkeypatch.setattr(fe, "_with_current_descriptions", lambda kb, cfg: seen.append(kb))
        other = type("E", (), {"key": "OTHER", "qualified_name": "ns::o"})()
        fe._label_chart(_cfg(), other, "src", "", self._Gen({}), config, "KB")
        assert seen == []
        fe._label_chart(_cfg(), entry, "src", "", self._Gen({"n1": "x", "n2": "y"}), config, "KB")
        assert seen == ["KB"]

    def test_the_request_names_the_charts_and_where_to_report(self, tmp_path):
        req = tmp_path / "req.json"
        req.write_text(json.dumps({"keys": ["A", "B"], "report": "R"}), encoding="utf-8")
        assert fe._read_rewrite_request(str(req)) == {"keys": ["A", "B"], "report": "R"}
        assert fe._read_rewrite_request(None) == {}
