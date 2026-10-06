"""Every translation unit is parsed with libclang's KeepGoing flag (`core.clang_options`).

Without CXTranslationUnit_KeepGoing (0x200), the first FATAL error in a translation unit -- a
missing `#include` -- makes clang stop instantiating templates for the rest of the file. A call
on a class-template member (`g_ring.push(p)`) then comes back as a CALL_EXPR with an empty
spelling and no referenced cursor, so Phase 1 records no call edge and no global read through
it, and `auto ftl_auto() { return g_ring.last(); }` keeps the return type `auto`. The sample's
includes all resolve, so no e2e test can see this; the office project's do not.

The fixture is two files written to tmp_path: a.cpp includes a header that does not exist, then
one that defines `template<class T,int N> class Ring`. The parser tests go through the parser's
own functions (`parse_file` + `parse_calls_and_globals`), not raw libclang, and need libclang,
so they skip without it.

Also here, because they exist for the same change: the parse fingerprint carries the options
(a narrowed parse must not merge onto a baseline parsed without them), a narrowed parse with no
changed TU still asks the fingerprint, and the incremental plan regenerates a function whose
calls moved while its source did not.
"""
import copy
import json
import os
import sys

import pytest

pytestmark = pytest.mark.unit

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ENGINE = os.path.join(ROOT, "engine")
_FLOWCHART = os.path.join(_ENGINE, "flowchart")
if _ENGINE not in sys.path:
    sys.path.insert(0, _ENGINE)

from core.clang_options import PARSE_KEEP_GOING        # noqa: E402
from incremental import engine as eng                  # noqa: E402

TYPES_H = """\
typedef unsigned int u32;
template <typename T, int N> class Ring {
public:
  void push(T v) { buf[n++ % N] = v; }
  T last() const { return buf[(n - 1) % N]; }
  T buf[N]; int n = 0;
};
struct Page { u32 lba; };
"""

A_CPP = """\
#include "missing_header.h"
#include "types.h"
static Ring<Page, 4> g_ring;
static void helper(u32 x) { (void)x; }
void ftl_write(u32 lba) { Page p{lba}; g_ring.push(p); helper(lba); }
u32 ftl_last() { return g_ring.last().lba; }
auto ftl_auto() { return g_ring.last(); }
"""

# The parser's registries a parse writes into; cleared before each fixture parse.
_REGISTRIES = ("functions", "globals_data", "call_graph", "reverse_call_graph",
               "global_access_reads", "global_access_writes", "_visited_function_keys",
               "_visited_call_keys", "_visited_global_access_keys", "_visited_usage_keys")


@pytest.fixture(scope="module")
def parser_mod():
    """Import parser.py (reads argv at import; also configures libclang)."""
    old_argv = sys.argv
    sys.argv = ["parser.py", ROOT]
    try:
        import parser as P
    except Exception as e:  # libclang missing / load failure
        pytest.skip(f"parser/libclang unavailable: {e}")
    finally:
        sys.argv = old_argv
    yield P


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("keep_going")
    (d / "types.h").write_text(TYPES_H, encoding="utf-8")
    (d / "a.cpp").write_text(A_CPP, encoding="utf-8")
    return d


def _parse(P, base, options=None):
    """Run Phase 1's two parses of a.cpp; return what they recorded, by plain name.

    `options` replaces the parser's TU options for this one parse (the control below). Every
    module-level container is restored afterwards: the parser's state is shared with every
    other test module that imports it.
    """
    saved = {n: (v, copy.copy(v)) for n, v in vars(P).items()
             if isinstance(v, (dict, set, list)) and not n.startswith("__")}
    real = (P.MODULE_BASE_PATH, P.is_project_file, P._TU_PARSE_OPTIONS, P.index)
    used = []

    class _Recording:
        """The parser's own index, with the options of each parse written down."""
        def parse(self, path, args=None, options=0, **kw):
            used.append(options)
            return real[3].parse(path, args=args, options=options, **kw)

    try:
        for name in _REGISTRIES:
            getattr(P, name).clear()
        P.MODULE_BASE_PATH = str(base)
        # is_project_file gates on the configured component map, which tmp_path is not in.
        P.is_project_file = lambda _p: True
        P.index = _Recording()
        if options is not None:
            P._TU_PARSE_OPTIONS = options
        path = str(base / "a.cpp")
        P.parse_file(path)
        P.parse_calls_and_globals(path)

        name = {k: f["functionName"] for k, f in P.functions.items()}
        gname = lambda vid: P.globals_data.get(vid, {}).get("qualifiedName", vid)  # noqa: E731
        return {
            "calls": {name[k]: [name.get(c, c) for c in cs] for k, cs in P.call_graph.items()},
            "reads": {name[k]: {gname(v) for v in vs}
                      for k, vs in P.global_access_reads.items() if k in name},
            "returns": {f["functionName"]: f.get("returnType") for f in P.functions.values()},
            "options": used,
        }
    finally:
        P.MODULE_BASE_PATH, P.is_project_file, P._TU_PARSE_OPTIONS, P.index = real
        for _n, (obj, before) in saved.items():
            obj.clear()
            obj.extend(before) if isinstance(obj, list) else obj.update(before)


@pytest.fixture(scope="module")
def parsed(parser_mod, fixture_dir):
    return _parse(parser_mod, fixture_dir)


@pytest.fixture(scope="module")
def parsed_without_the_flag(parser_mod, fixture_dir):
    return _parse(parser_mod, fixture_dir,
                  options=parser_mod._TU_PARSE_OPTIONS & ~PARSE_KEEP_GOING)


class TestPhase1KeepsGoingPastAMissingInclude:
    def test_both_parses_carry_the_flag(self, parsed):
        """parse_file and parse_calls_and_globals: two parses, one AST, both with KeepGoing."""
        assert len(parsed["options"]) == 2
        assert all(o & PARSE_KEEP_GOING for o in parsed["options"]), parsed["options"]

    def test_a_template_member_call_is_an_edge(self, parsed):
        assert "push" in parsed["calls"].get("ftl_write", [])
        assert parsed["calls"].get("ftl_last") == ["last"]
        assert parsed["calls"].get("ftl_auto") == ["last"]

    def test_a_plain_call_is_unchanged(self, parsed, parsed_without_the_flag):
        assert "helper" in parsed["calls"]["ftl_write"]
        assert "helper" in parsed_without_the_flag["calls"]["ftl_write"]

    def test_the_global_read_through_the_member_call_is_recorded(self, parsed):
        """The In/Out direction reads these sets, so the lost call cost a lost read too."""
        assert "g_ring" in parsed["reads"].get("ftl_last", set())
        assert "g_ring" in parsed["reads"].get("ftl_auto", set())

    def test_auto_is_deduced(self, parsed):
        assert parsed["returns"]["ftl_auto"] == "Page"

    def test_the_fixture_reproduces_the_loss_without_the_flag(self, parsed_without_the_flag):
        """The control: without KeepGoing this fixture loses exactly what the tests above
        assert. If a libclang upgrade stops losing it, this fails first -- and the tests above
        then no longer prove the flag matters."""
        calls = parsed_without_the_flag["calls"]
        assert calls.get("ftl_write") == ["helper"]
        assert "ftl_last" not in calls and "ftl_auto" not in calls
        assert parsed_without_the_flag["returns"]["ftl_auto"] == "auto"


class TestTheFlowchartEngineParsesTheSameWay:
    """The flowchart engine parses in its own process; its CFGs must come from the same AST."""

    @pytest.fixture(autouse=True)
    def _flowchart_on_path(self, parser_mod):
        # Appended, not prepended: `ast_engine` and `project_scanner` are unique names, and
        # the flowchart dir's `config`/`models` must not shadow anything for later modules.
        if _FLOWCHART not in sys.path:
            sys.path.append(_FLOWCHART)

    def test_its_full_parse_resolves_the_template_call(self, fixture_dir):
        import clang.cindex as ci
        from ast_engine.parser import TranslationUnitParser
        tu = TranslationUnitParser("c++14", []).get_tu_full(str(fixture_dir / "a.cpp"))
        resolved = {c.spelling: c.referenced is not None for c in tu.cursor.walk_preorder()
                    if c.kind == ci.CursorKind.CALL_EXPR and c.location.file
                    and c.location.file.name.endswith("a.cpp")}
        assert resolved.get("push") and resolved.get("last"), resolved

    def test_every_flowchart_parse_carries_the_flag(self):
        import project_scanner
        from ast_engine.parser import TranslationUnitParser
        assert TranslationUnitParser._PARSE_OPTIONS & PARSE_KEEP_GOING   # get_tu
        assert project_scanner._PARSE_OPTIONS & PARSE_KEEP_GOING


class TestTheFingerprintCarriesTheOptions:
    """A baseline parsed without KeepGoing must fail the narrowed-parse gate, or a narrowed
    parse re-parses only the changed files and keeps the lost calls everywhere else."""

    def test_the_options_are_hashed(self, parser_mod):
        args = parser_mod._fingerprint_args()
        assert args[-1] == f"--parse-options=0x{parser_mod._TU_PARSE_OPTIONS:x}"
        assert parser_mod._TU_PARSE_OPTIONS & PARSE_KEEP_GOING

    def test_a_baseline_parsed_without_them_does_not_match(self, parser_mod):
        from incremental.fingerprint import parse_fingerprint
        now = parser_mod._fingerprint_args()
        before = [a for a in now if not a.startswith("--parse-options=")]
        assert parse_fingerprint(now, base_path=ROOT) != parse_fingerprint(before, base_path=ROOT)


class TestANarrowedParseWithNoChangedTUAsksTheFingerprint:
    """No TU changed used to mean "reuse the baseline skeleton" without reaching the gate, so a
    regeneration of the same commit kept a baseline parsed with other flags -- here, without
    KeepGoing. The partial parse now runs over no files: it parses nothing and reports this
    run's fingerprint."""

    def _call(self, tmp_path, monkeypatch, partial_fp):
        base = tmp_path / "base"
        base.mkdir()
        for name, data in (("tu_includes", {"App/Main.cpp": []}),
                           ("entity_files", {"App|Main|main|int": "App/Main.cpp"}),
                           ("functions", {"App|Main|main|int": {"callsIds": []}}),
                           ("metadata", {"parseFingerprint": "baseline"})):
            (base / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
        model_dir = tmp_path / "model"
        seen = {"lists": [], "published": []}

        def _fake_run(*_a, extra_args=None, **_kw):
            listfile = extra_args[extra_args.index("--only-files") + 1]
            with open(listfile, encoding="utf-8") as fh:
                seen["lists"].append([ln.strip() for ln in fh if ln.strip()])
            (model_dir / "metadata.json").write_text(
                json.dumps({"parseFingerprint": partial_fp}), encoding="utf-8")
            return 0

        monkeypatch.setattr(eng.git_ops, "changed_files_status", lambda *_a, **_k: [])
        monkeypatch.setattr(eng, "_run_analyzer", _fake_run)
        monkeypatch.setattr(eng, "_write_parse_artifacts",
                            lambda _d, merged, **_k: seen["published"].append(merged))
        ok = eng._try_narrowed_parse(
            str(tmp_path / "cfg.json"), {"type": "project"}, True, None,
            str(tmp_path / "repo"), ROOT, str(model_dir),
            target="b" * 40, base_commit="a" * 40, base_parse_dir=str(base))
        return ok, seen, model_dir

    def test_other_flags_force_a_full_parse(self, tmp_path, monkeypatch):
        ok, seen, model_dir = self._call(tmp_path, monkeypatch, partial_fp="keep-going")
        assert ok is False, "the baseline skeleton was reused although it was parsed differently"
        assert seen["lists"] == [[]], "the partial parse must run, over no files"
        assert seen["published"] == []
        assert not (model_dir / "metadata.json").exists(), "the scratch parse was left behind"

    def test_the_same_flags_still_reuse_the_baseline(self, tmp_path, monkeypatch):
        ok, seen, model_dir = self._call(tmp_path, monkeypatch, partial_fp="baseline")
        assert ok is True
        assert len(seen["published"]) == 1
        assert "App|Main|main|int" in seen["published"][0]["functions"]
        assert not (model_dir / "metadata.json").exists(), "the scratch parse was left behind"


class TestAMovedCallRegeneratesWithNoSourceChange:
    """`classify` sees source hashes only. When the PARSE changes -- KeepGoing turning a lost
    template call into an edge -- every hash is the same, so the impact set came out empty and
    the run carried descriptions, behaviour names and unit diagrams forward from a baseline
    with another call graph. A function whose calls or global accesses moved now seeds the
    impact."""

    @staticmethod
    def _fns(a_calls, a_reads=()):
        return {
            "a": {"callsIds": list(a_calls), "calledByIds": ["top"],
                  "readsGlobalIds": list(a_reads)},
            "b": {"callsIds": [], "calledByIds": ["a"] if "b" in a_calls else []},
            "top": {"callsIds": ["a"], "calledByIds": []},
            "other": {"callsIds": [], "calledByIds": []},
        }

    H = {"a": "1", "b": "1", "top": "1", "other": "1"}

    def test_a_new_edge_regenerates_the_caller_and_its_callers(self):
        plan = eng.plan_incremental(self.H, dict(self.H), self._fns(["b"]), {}, self._fns([]))
        assert plan["depsMoved"] == {"a"}
        assert plan["impact"] == {"a", "top"}
        assert plan["reused"] == {"b", "other"}

    def test_a_new_global_read_regenerates_too(self):
        plan = eng.plan_incremental(self.H, dict(self.H), self._fns([], ["g"]), {},
                                    self._fns([]))
        assert plan["depsMoved"] == {"a"}

    def test_the_same_edges_regenerate_nothing(self):
        """The ordinary run: no hash moved, no edge moved -- nothing regenerates."""
        plan = eng.plan_incremental(self.H, dict(self.H), self._fns(["b"]), {}, self._fns(["b"]))
        assert plan["depsMoved"] == set()
        assert plan["impact"] == set()

    def test_order_alone_is_not_a_move(self):
        tgt, base = self._fns(["b", "other"]), self._fns(["other", "b"])
        assert eng.plan_incremental(self.H, dict(self.H), tgt, {}, base)["depsMoved"] == set()
