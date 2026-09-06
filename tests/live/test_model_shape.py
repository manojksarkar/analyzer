"""Does every function the document needs carry the fields the document reads?

Only rows WITH a payload are checked. A row with a source_hash and no payload is a
HASH-ONLY entity and is deliberate -- see `real_functions` in conftest.
"""
import pytest

pytestmark = pytest.mark.live


def _sample(keys, n=8):
    return "\n      ".join(sorted(keys)[:n])


def _missing(real, field):
    return [k for k, f in real.items() if not f.get(field)]


class TestFieldsTheIncrementalRunNeeds:
    def test_every_function_has_a_file(self, real_functions, vid):
        real = real_functions(vid)
        if not real:
            pytest.skip("no functions with a payload in %s" % vid)
        gone = _missing(real, "file")
        assert not gone, (
            "%s: %d of %d functions have no file.\n"
            "An entity with no file cannot be matched against a git diff, so it is "
            "invisible to every incremental run -- edits to it are never detected.\n      %s"
            % (vid, len(gone), len(real), _sample(gone)))

    def test_every_function_has_a_line_range(self, real_functions, vid):
        real = real_functions(vid)
        if not real:
            pytest.skip("no functions with a payload in %s" % vid)
        bad = [k for k, f in real.items()
               if not f.get("line") or (f.get("end_line") and f["end_line"] < f["line"])]
        assert not bad, (
            "%s: %d function(s) have no line, or an end before their start.\n"
            "The line range is what decides whether a diff hunk touched this function.\n"
            "      %s" % (vid, len(bad), _sample(bad)))


class TestFieldsTheDocumentNeeds:
    def test_every_function_has_a_component(self, real_functions, vid):
        real = real_functions(vid)
        if not real:
            pytest.skip("no functions with a payload in %s" % vid)
        gone = _missing(real, "component")
        assert not gone, (
            "%s: %d of %d functions have no component. Scope filtering and the "
            "per-component documents both key on it.\n      %s"
            % (vid, len(gone), len(real), _sample(gone)))

    def test_every_function_has_a_unit(self, real_functions, vid):
        real = real_functions(vid)
        if not real:
            pytest.skip("no functions with a payload in %s" % vid)
        gone = _missing(real, "unit")
        assert not gone, (
            "%s: %d of %d functions have no unit. The interface tables and the unit "
            "diagrams are per unit.\n      %s" % (vid, len(gone), len(real), _sample(gone)))

    def test_every_function_has_a_visibility(self, real_functions, vid):
        real = real_functions(vid)
        if not real:
            pytest.skip("no functions with a payload in %s" % vid)
        gone = _missing(real, "visibility")
        assert not gone, (
            "%s: %d of %d functions have no visibility, so they land in neither the public "
            "nor the private interface table -- they are simply absent from the "
            "document.\n      %s" % (vid, len(gone), len(real), _sample(gone)))

    def test_the_entity_key_matches_its_component_and_unit(self, real_functions, vid):
        """`component|unit|qualifiedName|paramTypes` -- the key and the columns are two
        spellings of one fact, and a disagreement means one of them is wrong."""
        real = real_functions(vid)
        if not real:
            pytest.skip("no functions with a payload in %s" % vid)
        bad = []
        for k, f in real.items():
            parts = k.split("|")
            if len(parts) < 2:
                continue
            if f.get("component") and parts[0] != f["component"]:
                bad.append("%s -> component column %r" % (k, f["component"]))
            elif f.get("unit") and parts[1] != f["unit"]:
                bad.append("%s -> unit column %r" % (k, f["unit"]))
        assert not bad, (
            "%s: %d function(s) whose key disagrees with their component/unit columns.\n"
            "Readers use both, so they must agree.\n      %s"
            % (vid, len(bad), "\n      ".join(bad[:8])))


class TestInterfaceIds:
    def test_no_interface_id_is_reused(self, real_functions, vid):
        import collections
        real = real_functions(vid)
        ids = [f["interface_id"] for f in real.values() if f.get("interface_id")]
        if not ids:
            pytest.skip("version %s records no interface ids" % vid)
        dupes = [(i, n) for i, n in collections.Counter(ids).items() if n > 1]
        assert not dupes, (
            "%s: %d interface id(s) are used by more than one function.\n"
            "The traceability matrix references an entry by its id, so a duplicate makes "
            "two functions indistinguishable in the document.\n      %s"
            % (vid, len(dupes),
               "\n      ".join("%s used by %d" % (i, n) for i, n in dupes[:8])))
