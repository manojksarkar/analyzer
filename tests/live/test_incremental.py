"""Cross-version invariants: the ones the incremental design actually rests on.

A version is compared against ITS OWN baseline -- the pair the run reasoned about -- not
against the version before it in time.
"""
import pytest

pytestmark = pytest.mark.live


def _fc_key(entity_key):
    """`component|unit|qname|params` -> the (unit, name) the flowchart output is keyed by."""
    parts = entity_key.split("|")
    if len(parts) < 3:
        return None
    return (parts[1], parts[2].split("::")[-1])


class TestBaselineSelection:
    def test_the_baseline_is_not_at_the_same_commit(self, versions, by_id):
        bad = [(v["id"], v["baseline"]) for v in versions
               if v["baseline"] and by_id.get(v["baseline"], {}).get("commit") == v["commit"]]
        assert not bad, (
            "%d version(s) are built on a baseline at THEIR OWN commit.\n"
            "Git counts a commit as its own ancestor, so such a baseline sits at distance 0 "
            "and wins selection. The run then finds no changed files, re-parses nothing, "
            "and the new version is a verbatim COPY of the old one while still reporting "
            "decision=incremental.\n      %s"
            % (len(bad), "\n      ".join("%s -> %s" % p for p in bad)))

    def test_every_baseline_reference_resolves(self, versions, by_id):
        orphan = [v["id"] for v in versions if v["baseline"] and v["baseline"] not in by_id]
        assert not orphan, (
            "%d version(s) name a baseline that no longer exists, so nothing can be "
            "carried forward and an incremental run silently becomes a full one.\n      %s"
            % (len(orphan), "\n      ".join(orphan)))

    def test_no_baseline_cycle(self, versions, by_id):
        for v in versions:
            seen, cur = set(), v["id"]
            while cur and cur in by_id:
                if cur in seen:
                    pytest.fail("%s's baseline chain loops back on itself at %s"
                                % (v["id"], cur))
                seen.add(cur)
                cur = by_id[cur].get("baseline")

    def test_every_version_reached_a_terminal_state(self, versions):
        bad = [(v["id"], v["status"]) for v in versions
               if (v["status"] or "") not in ("complete", "failed", None)]
        assert not bad, (
            "%d version(s) never reached a terminal pipeline_status. A non-terminal "
            "version is skipped as a baseline candidate, so every later run silently "
            "falls back to a worse one and reuse drops to zero.\n      %s"
            % (len(bad), "\n      ".join("%s = %s" % p for p in bad)))


class TestAChangedFunctionIsRegenerated:
    """The whole point of incremental: an edit must reach the picture."""

    def _pair(self, versions, by_id, vid):
        v = by_id.get(vid)
        if not v or not v["baseline"] or v["baseline"] not in by_id:
            pytest.skip("version %s has no baseline inside the audited set" % vid)
        return v["baseline"]

    def test_a_changed_hash_produced_a_changed_flowchart(
            self, versions, by_id, functions, flowchart_dots, vid):
        base = self._pair(versions, by_id, vid)
        fb, ft = functions(base), functions(vid)
        db_, dt = flowchart_dots(base), flowchart_dots(vid)
        if not dt or not db_:
            pytest.skip("%s or its baseline stored no flowchart output" % vid)

        changed = [k for k in ft if k in fb and ft[k]["hash"] != fb[k]["hash"]]
        stale, comparable = [], 0
        for k in changed:
            fk = _fc_key(k)
            if not fk or fk not in dt or fk not in db_:
                continue
            comparable += 1
            if dt[fk] == db_[fk]:
                stale.append("%s [%s]" % (k, ft[k]["file"] or "?"))
        if not comparable:
            pytest.skip("%s: no changed function has a flowchart in both versions" % vid)
        assert not stale, (
            "%s vs baseline %s: %d of %d changed function(s) kept the baseline's "
            "flowchart.\n"
            "The parse saw the change and the flowchart did not follow -- either the plan "
            "excluded the function, or a cross-version splice returned the baseline's "
            "graph. Run tools/flowchart_lineage.py on one of these names.\n      %s"
            % (vid, base, len(stale), comparable, "\n      ".join(sorted(stale)[:8])))

    def test_the_graph_and_the_picture_come_from_one_version(
            self, versions, by_id, flowchart_dots, version_pngs, vid):
        base = self._pair(versions, by_id, vid)
        dt, db_ = flowchart_dots(vid), flowchart_dots(base)
        pt, pb = version_pngs(vid), version_pngs(base)
        if not (dt and db_ and pt and pb):
            pytest.skip("%s: graphs or images are missing on one side" % vid)

        split = []
        for fk in dt:
            if fk not in db_:
                continue
            stem = "%s_%s" % fk
            mine_t = {f: h for f, h in pt.items() if f.startswith(stem)}
            mine_b = {f: h for f, h in pb.items() if f.startswith(stem)}
            if not mine_t or not mine_b:
                continue
            if (dt[fk] == db_[fk]) != (mine_t == mine_b):
                split.append("%s|%s  DOT %s / PNG %s"
                             % (fk[0], fk[1],
                                "same" if dt[fk] == db_[fk] else "changed",
                                "same" if mine_t == mine_b else "changed"))
        assert not split, (
            "%s vs baseline %s: %d function(s) whose graph and image disagree.\n"
            "A PNG is rendered FROM its DOT. A DOT that holds still while the image moves "
            "means the stored graph is not what produced the picture in the document; the "
            "reverse means a stale image is served for a regenerated graph.\n      %s"
            % (vid, base, len(split), "\n      ".join(sorted(split)[:8])))


class TestIncrementalAccounting:
    def test_an_incremental_version_names_a_baseline(self, versions):
        bad = [v["id"] for v in versions
               if v["decision"] == "incremental" and not v["baseline"]]
        assert not bad, (
            "%d version(s) record decision=incremental with no baseline. Nothing was "
            "reused, so the label is wrong and the reuse report is meaningless.\n      %s"
            % (len(bad), "\n      ".join(bad)))

    def test_an_incremental_version_did_not_reparse_everything(
            self, functions, versions, by_id, vid):
        """A useful incremental run leaves most hashes alone. If every function changed,
        the run was a full parse wearing an incremental label -- or change detection is
        broken in the direction that costs money rather than correctness."""
        v = by_id.get(vid)
        if not v or v["decision"] != "incremental" or not v["baseline"]:
            pytest.skip("%s is not an incremental version with a baseline" % vid)
        if v["baseline"] not in by_id:
            pytest.skip("%s's baseline is outside the audited set" % vid)
        fb, ft = functions(v["baseline"]), functions(vid)
        shared = [k for k in ft if k in fb]
        if len(shared) < 50:
            pytest.skip("%s shares too few functions with its baseline to judge" % vid)
        changed = [k for k in shared if ft[k]["hash"] != fb[k]["hash"]]
        pct = 100.0 * len(changed) / len(shared)
        assert pct < 90, (
            "%s vs baseline %s: %.0f%% of shared functions changed (%d of %d).\n"
            "An incremental run that re-derives nearly everything is either a full parse "
            "mislabelled, or a sign the hashes were recomputed differently between the two "
            "versions -- the same source hashing differently is what a lost or "
            "differently-keyed `hashes` artifact looks like from here."
            % (vid, v["baseline"], pct, len(changed), len(shared)))
