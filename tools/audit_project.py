"""Audit everything a project stored, and every invariant the incremental design relies on.

Read-only. Run it after any generate; it changes nothing and needs no LLM.

`check_db.py` already checks that the rows are STRUCTURALLY sound — no orphans, no dangling
blobs, no missing snapshots. This checks that they are CORRECT: that change detection can
actually detect change, that a function whose code moved got a new flowchart, that a stored
blob is the hash it claims to be, that a baseline is a real ancestor. Every check here exists
because the condition it looks for happened on a real project and nothing reported it:

  * 2069 of 2818 functions carried sha256("") as their source hash, so they were UNCHANGED
    in every comparison forever and their flowcharts could never regenerate;
  * a version at the target commit won baseline selection, so a re-run produced a verbatim
    copy of the version it was meant to replace and called it incremental;
  * a cross-version splice landed the PNG but not the DOT, so the stored graph and the
    picture in the document came from different versions;
  * a flowchart split across `_part_N_of_M.png` images was never spliced at all, so one
    function updated and the one beside it kept last version's picture.

None raised an error. Each was found by measuring, which is what this automates.

**An empty check is not a pass.** Every check reports how many rows it examined, so a
vacuous pass is visible rather than reassuring.

**The report carries no source code**, no doc comments and no LLM-generated text — function
names, file paths, hashes and counts only.

    python tools/audit_project.py --project-id P
    python tools/audit_project.py --project-id P --out audit.txt
    python tools/audit_project.py --project-id P --versions v5,v7,v9

Exit 0 = nothing wrong. 1 = findings. 2 = could not run.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

ERROR, WARN, INFO, OK = "ERROR", "WARN", "INFO", "OK"
_MAX_EXAMPLES = 8

# hash_tokens([]) — the constant every entity libclang could not tokenise collapsed onto.
EMPTY_HASH = hashlib.sha256(b"").hexdigest()
_SRC_EXTS = (".cpp", ".cc", ".cxx", ".c", ".c++")


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
class Report:
    """Findings, plus what each check EXAMINED.

    A check that looked at nothing and found nothing is not a pass, and this codebase has
    been burned by exactly that: a diagnostic reported success twice while examining an
    empty set, and cost two real runs on a 2817-function project to notice.
    """

    def __init__(self):
        self.section = ""
        self.rows = []          # (section, level, code, headline, examined, examples, why, ask)

    def start(self, name):
        self.section = name

    def add(self, level, code, headline, *, examined, examples=None, why="", ask=""):
        self.rows.append((self.section, level, code, headline, examined,
                          list(examples or [])[:_MAX_EXAMPLES], why, ask))

    def ok(self, code, headline, *, examined):
        self.add(OK, code, headline, examined=examined)

    def skipped(self, code, headline, why=""):
        self.add(INFO, code, headline, examined=0, why=why)

    @property
    def errors(self):
        return [r for r in self.rows if r[1] == ERROR]

    @property
    def warnings(self):
        return [r for r in self.rows if r[1] == WARN]

    def render(self) -> str:
        out = []
        cur = None
        for sec, level, code, headline, examined, examples, why, ask in self.rows:
            if sec != cur:
                cur = sec
                out += ["", "=" * 78, sec, "=" * 78]
            mark = {OK: "  ok  ", ERROR: " FAIL ", WARN: " warn ", INFO: " --   "}[level]
            out.append("%s %-6s %s" % (mark, code, headline))
            out.append("            examined: %s" % examined)
            for e in examples:
                out.append("            - %s" % e)
            if why:
                for line in _wrap(why, 62):
                    out.append("            %s" % line)
            if ask:
                for line in _wrap("NEEDED TO FIX: " + ask, 62):
                    out.append("            %s" % line)
        return "\n".join(out)


def _wrap(text, width):
    words, line, lines = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------
class Ctx:
    """Everything the checks read, loaded once."""

    def __init__(self, eng, sa, s, project_id, only):
        self.eng, self.sa, self.s, self.project_id = eng, sa, s, project_id
        with eng.connect() as cx:
            self.versions = [dict(id=r[0], commit=r[1], decision=r[2], baseline=r[3],
                                  status=r[4], created=r[5])
                             for r in cx.execute(sa.text(
                                 "select id, commit_sha, decision, baseline_version_id, "
                                 "pipeline_status, created_at from versions "
                                 "where project_id = :p order by created_at"),
                                 {"p": project_id})]
        if only:
            keep = {v.strip() for v in only.split(",") if v.strip()}
            self.versions = [v for v in self.versions if v["id"] in keep]
        self.vids = [v["id"] for v in self.versions]
        self.by_id = {v["id"]: v for v in self.versions}
        self._fns = {}
        self._dots = {}

    def functions(self, vid):
        """{entity_key: dict(hash, file, line, end_line, component, unit, visibility,
        direction, interface_id, content_hash)} — no payload text."""
        if vid in self._fns:
            return self._fns[vid]
        q = ("select e.entity_key, v.source_hash, v.file, v.line, v.end_line, v.component, "
             "v.unit, v.visibility, v.direction, v.interface_id, v.content_hash "
             "from entity_versions v join entities e on e.entity_id = v.entity_id "
             "where v.version_id = :v and e.kind = 'function'")
        with self.eng.connect() as cx:
            out = {r[0]: dict(hash=r[1], file=r[2], line=r[3], end_line=r[4], component=r[5],
                              unit=r[6], visibility=r[7], direction=r[8], interface_id=r[9],
                              content_hash=r[10])
                   for r in cx.execute(self.sa.text(q), {"v": vid})}
        self._fns[vid] = out
        return out

    def dots(self, vid):
        """{(unit, funcName) -> dot} from the STORED output files, not from disk."""
        if vid in self._dots:
            return self._dots[vid]
        out = {}
        with self.eng.connect() as cx:
            rows = cx.execute(self.sa.text(
                "select rel_path, content from version_output_files where version_id = :v"),
                {"v": vid}).fetchall()
        for rel, content in rows:
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
        self._dots[vid] = out
        return out

    def version_dir(self, vid):
        return os.path.join(_ROOT, "workspaces", self.project_id, "versions", vid)

    def pngs(self, vid):
        """{png filename -> md5} from disk (PNGs are not stored in the database)."""
        out = {}
        base = os.path.join(self.version_dir(vid), "output")
        for root, _d, files in os.walk(base) if os.path.isdir(base) else []:
            if os.path.basename(root) != "flowcharts":
                continue
            for f in files:
                if f.endswith(".png"):
                    p = os.path.join(root, f)
                    out[f] = hashlib.md5(open(p, "rb").read()).hexdigest()[:10]
        return out


# ---------------------------------------------------------------------------
# A. version chain
# ---------------------------------------------------------------------------
def check_versions(ctx, rep):
    rep.start("A. VERSION CHAIN — is each run built on what it claims?")
    vs = ctx.versions
    if not vs:
        rep.skipped("A0", "no versions for this project", "check the --project-id")
        return

    bad_status = [v["id"] for v in vs if (v["status"] or "") not in ("complete", "failed", None)]
    rep.add(ERROR if bad_status else OK, "A1",
            "%d version(s) never reached a terminal pipeline_status" % len(bad_status)
            if bad_status else "every version reached a terminal state",
            examined="%d versions" % len(vs), examples=bad_status,
            why="A non-terminal version is skipped as a baseline candidate, so every later "
                "run silently falls back to a worse one and reuse drops to zero.",
            ask="the pipeline_status value and whether that run crashed.")

    same = [(v["id"], v["baseline"]) for v in vs
            if v["baseline"] and ctx.by_id.get(v["baseline"], {}).get("commit") == v["commit"]]
    rep.add(ERROR if same else OK, "A2",
            "%d version(s) are built on a baseline AT THEIR OWN COMMIT" % len(same)
            if same else "no version is built on a baseline at its own commit",
            examined="%d versions" % len(vs),
            examples=["%s -> baseline %s (same commit)" % (a, b) for a, b in same],
            why="Git counts a commit as its own ancestor, so such a baseline has distance 0 "
                "and wins selection. The run then finds no changed files, re-parses nothing, "
                "and the new version is a verbatim COPY of the old one while reporting "
                "decision=incremental.",
            ask="the ids above; re-generate them with --base-version naming a real ancestor.")

    orphan = [v["id"] for v in vs if v["baseline"] and v["baseline"] not in ctx.by_id]
    rep.add(WARN if orphan else OK, "A3",
            "%d version(s) name a baseline that no longer exists" % len(orphan)
            if orphan else "every baseline reference resolves",
            examined="%d versions" % len(vs), examples=orphan,
            why="The baseline was deleted. Nothing can be carried forward from it, so an "
                "incremental run against it silently becomes a full one.")

    inc_no_base = [v["id"] for v in vs if v["decision"] == "incremental" and not v["baseline"]]
    rep.add(WARN if inc_no_base else OK, "A4",
            "%d version(s) say decision=incremental but name no baseline" % len(inc_no_base)
            if inc_no_base else "every incremental version names a baseline",
            examined="%d versions" % len(vs), examples=inc_no_base)


# ---------------------------------------------------------------------------
# B. change detection
# ---------------------------------------------------------------------------
def check_hashes(ctx, rep):
    rep.start("B. CHANGE DETECTION — can this project detect a change at all?")
    for v in ctx.versions:
        fns = ctx.functions(v["id"])
        if not fns:
            rep.skipped("B0", "version %s has no function rows" % v["id"])
            continue
        empty = sorted(k for k, f in fns.items() if f["hash"] == EMPTY_HASH)
        blank = sorted(k for k, f in fns.items() if not f["hash"])
        pct = (100.0 * len(empty) / len(fns)) if fns else 0

        rep.add(ERROR if empty else OK, "B1",
                "%s: %d of %d functions (%.0f%%) carry the EMPTY-TOKEN hash"
                % (v["id"], len(empty), len(fns), pct) if empty
                else "%s: no function carries the empty-token hash" % v["id"],
                examined="%d functions" % len(fns), examples=empty,
                why="sha256(\"\") is what hash_cursor produced when libclang returned no "
                    "tokens. Every entity holding it is UNCHANGED in every comparison "
                    "forever, so its flowchart and description can never be regenerated by "
                    "a code edit. Fixed in db_util/hashing; a version parsed before that "
                    "fix still carries it and must be regenerated, not reused as a baseline.",
                ask="this count and the version id.")

        rep.add(ERROR if blank else OK, "B2",
                "%s: %d function(s) have NO source_hash" % (v["id"], len(blank)) if blank
                else "%s: every function has a source_hash" % v["id"],
                examined="%d functions" % len(fns), examples=blank,
                why="Change detection cannot run for an entity with no hash.")

        # B2 counts rows with no hash. Knowing WHICH rows those are decides the fix, and
        # the two populations are easy to confuse: a hash-only row (payload absent, hash
        # present) is by design, while a real function with a payload and NO hash means the
        # `hashes` artifact did not reach persist_functions. Cross-tabulate so the report
        # says which, and check whether the hashed keys and the payload keys even describe
        # the same functions -- a disjoint pair means the two sides are keyed differently,
        # which is a completely different bug from a lost artifact.
        real = {k: f for k, f in fns.items() if f.get("content_hash")}
        bare = {k: f for k, f in fns.items() if not f.get("content_hash")}
        real_no_hash = sorted(k for k, f in real.items() if not f["hash"])
        bare_no_hash = sorted(k for k, f in bare.items() if not f["hash"])
        rep.add(ERROR if real_no_hash else OK, "B4",
                "%s: %d real function(s) have a payload but NO source_hash"
                % (v["id"], len(real_no_hash)) if real_no_hash
                else "%s: every real function has a source_hash" % v["id"],
                examined="%d real, %d hash-only" % (len(real), len(bare)),
                examples=real_no_hash,
                why="persist_functions takes source_hash from the `hashes` artifact. A "
                    "payload with no hash means `hashes` was empty or keyed differently "
                    "when the model was persisted, so change detection is dead for the "
                    "NEXT run even though this run's document is fine.",
                ask="the B5 line below, which says whether the two key sets overlap.")
        if bare_no_hash:
            rep.add(WARN, "B4b",
                    "%s: %d hash-only row(s) have no hash either" % (v["id"], len(bare_no_hash)),
                    examined="%d hash-only rows" % len(bare),
                    examples=bare_no_hash,
                    why="A row carrying neither a payload nor a hash serves no purpose.")

        # Do the hashed keys and the payload keys describe the same functions? Compare on
        # component|unit|qualifiedName, ignoring the parameter-type tail, because that tail
        # is the part Phase 1 and Phase 2 spell differently (`params` vs `parameters`).
        if real_no_hash and bare:
            def _stem3(k):
                return "|".join(k.split("|")[:3])
            overlap = {_stem3(k) for k in real} & {_stem3(k) for k in bare}
            rep.add(WARN if overlap else INFO, "B5",
                    "%s: %d function name(s) appear in BOTH the payload set and the "
                    "hash-only set" % (v["id"], len(overlap)) if overlap
                    else "%s: the payload set and the hash-only set are different functions"
                         % v["id"],
                    examined="%d real, %d hash-only" % (len(real), len(bare)),
                    examples=sorted(overlap)[:_MAX_EXAMPLES],
                    why="Overlap means ONE function was stored twice under two different "
                        "keys -- the parameter-type tail is spelled differently by the two "
                        "phases, so the hash never finds its function. No overlap means the "
                        "hash-only rows are genuinely other entities (out of scope), and "
                        "the missing hashes are a lost `hashes` artifact instead.",
                    ask="this line decides between a key-spelling bug and a lost artifact.")

        dup = collections.Counter(f["hash"] for f in fns.values() if f["hash"])
        big = sorted(((h, n) for h, n in dup.items() if n > 3 and h != EMPTY_HASH),
                     key=lambda x: -x[1])
        rep.add(WARN if big else OK, "B3",
                "%s: %d hash value(s) shared by more than 3 functions" % (v["id"], len(big))
                if big else "%s: no suspicious hash clusters" % v["id"],
                examined="%d distinct hashes" % len(dup),
                examples=["%d functions share %s" % (n, h[:12]) for h, n in big[:5]],
                why="Identical bodies hash identically, which is expected for trivial "
                    "getters. A large cluster is not.")


# ---------------------------------------------------------------------------
# C. incremental correctness
# ---------------------------------------------------------------------------
def check_incremental(ctx, rep):
    rep.start("C. INCREMENTAL CORRECTNESS — did a changed function get a new flowchart?")
    pairs = [(v["baseline"], v["id"]) for v in ctx.versions
             if v["baseline"] and v["baseline"] in ctx.by_id]
    if not pairs:
        rep.skipped("C0", "no version has a baseline inside the audited set",
                    "generate a second version, or widen --versions.")
        return

    for base, vid in pairs:
        fb, ft = ctx.functions(base), ctx.functions(vid)
        db, dt = ctx.dots(base), ctx.dots(vid)
        if not dt:
            rep.skipped("C1", "%s: no stored flowchart output to compare" % vid,
                        "flowcharts may be disabled (views.flowcharts) or the outputs were "
                        "never captured into version_output_files.")
            continue

        changed = [k for k in ft if k in fb and ft[k]["hash"] != fb[k]["hash"]]
        # Map an entity key to the (unit, funcName) the flowchart output is keyed by.
        def _fc_key(entity_key):
            parts = entity_key.split("|")
            if len(parts) < 3:
                return None
            return (parts[1], parts[2].split("::")[-1])

        stale, checked = [], 0
        for k in changed:
            fk = _fc_key(k)
            if not fk or fk not in dt or fk not in db:
                continue
            checked += 1
            if dt[fk] == db[fk]:
                stale.append("%s [%s]" % (k, ft[k]["file"] or "?"))
        rep.add(ERROR if stale else OK, "C1",
                "%s: %d changed function(s) kept the baseline's flowchart" % (vid, len(stale))
                if stale else "%s: every changed function got a new flowchart" % vid,
                examined="%d changed functions, %d comparable" % (len(changed), checked),
                examples=stale,
                why="The parse saw the change and the flowchart did not follow. Either the "
                    "plan excluded the function, or a cross-version splice returned the "
                    "baseline's graph.",
                ask="these names, plus `tools/flowchart_lineage.py --name <one of them>`.")

        # A DOT and its PNG are the same artifact seen twice: the image is rendered FROM the
        # graph. If one moves and the other does not, they came from different versions.
        pb, pt = ctx.pngs(base), ctx.pngs(vid)
        if not pt:
            rep.skipped("C2", "%s: no PNGs on disk to cross-check" % vid,
                        "image rendering may be off (views.flowcharts=false), which is a "
                        "valid configuration.")
            continue
        split = []
        for fk in dt:
            if fk not in db:
                continue
            stem = "%s_%s" % fk
            mine_t = {f: h for f, h in pt.items() if f.startswith(stem)}
            mine_b = {f: h for f, h in pb.items() if f.startswith(stem)}
            if not mine_t or not mine_b:
                continue
            dot_same, png_same = dt[fk] == db[fk], mine_t == mine_b
            if dot_same != png_same:
                split.append("%s|%s  DOT %s / PNG %s"
                             % (fk[0], fk[1], "same" if dot_same else "changed",
                                "same" if png_same else "changed"))
        rep.add(ERROR if split else OK, "C3",
                "%s: %d function(s) whose DOT and PNG disagree" % (vid, len(split))
                if split else "%s: every DOT and PNG moved together" % vid,
                examined="%d functions with images in both versions" % len(pt),
                examples=split,
                why="A PNG is rendered from its DOT. A DOT that holds still while the image "
                    "moves means the stored graph is not what produced the picture in the "
                    "document; the reverse means a stale image is served for a new graph.",
                ask="these names and `tools/flowchart_lineage.py` for one of them.")


# ---------------------------------------------------------------------------
# D. model completeness
# ---------------------------------------------------------------------------
def check_model_shape(ctx, rep):
    rep.start("D. MODEL COMPLETENESS — is every field the document needs present?")
    for v in ctx.versions:
        # HASH-ONLY rows are excluded, and that is not a loophole. `persist_bare_entities`
        # deliberately writes an entity_versions row carrying ONLY a source_hash for a
        # hashed entity that is not part of the model -- a file-scope macro, or a function
        # outside the generated scope -- so `classify` can still see its hash next run.
        # `load_functions` skips them for the same reason ("hash-only entity, not a real
        # function"). Auditing them for a file or a component reported 2818 failures on a
        # healthy project and buried the one finding that mattered.
        allf = ctx.functions(v["id"])
        fns = {k: f for k, f in allf.items() if f.get("content_hash")}
        bare = len(allf) - len(fns)
        rep.add(INFO, "D0",
                "%s: %d real function(s) with a payload, %d hash-only row(s)"
                % (v["id"], len(fns), bare),
                examined="%d function rows" % len(allf),
                why="A hash-only row is deliberate: a hashed entity outside the generated "
                    "model, kept so change detection can still see it. Only the real ones "
                    "are checked below.")
        if not fns:
            continue
        for code, field, level, why in (
                ("D1", "file", ERROR, "Without a file an entity cannot be matched to a git "
                                      "diff, so it is invisible to every incremental run."),
                ("D2", "component", ERROR, "Scope filtering and per-component documents "
                                           "both key on this."),
                ("D3", "unit", ERROR, "The interface tables and unit diagrams are per unit."),
                ("D4", "visibility", WARN, "A function with no visibility cannot be placed "
                                           "in the public or private interface table."),
                ("D5", "direction", WARN, "The interface table's Direction column."),
                ("D6", "interface_id", WARN, "An interface id is what the SWE.3 tables and "
                                             "the traceability matrix reference the entry "
                                             "by; a blank one drops it from both.")):
            missing = sorted(k for k, f in fns.items() if not f.get(field))
            rep.add(level if missing else OK, code,
                    "%s: %d function(s) with no %s" % (v["id"], len(missing), field)
                    if missing else "%s: every function has %s" % (v["id"], field),
                    examined="%d functions" % len(fns), examples=missing, why=why)


# ---------------------------------------------------------------------------
# E. storage integrity
# ---------------------------------------------------------------------------
def check_storage(ctx, rep):
    rep.start("E. STORAGE INTEGRITY — is a stored blob the hash it claims to be?")
    sa = ctx.sa
    with ctx.eng.connect() as cx:
        rows = cx.execute(sa.text(
            "select b.content_hash, b.payload from content_blobs b "
            "where b.content_hash in (select distinct content_hash from entity_versions "
            "where version_id in :vids and content_hash is not null)"
        ).bindparams(sa.bindparam("vids", expanding=True)), {"vids": ctx.vids or [""]}).fetchall()

    from core.model_store import _content_hash
    mismatched, nul = [], []
    for h, payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if _content_hash(payload) != h:
            mismatched.append(h[:16])
        if _has_nul(payload):
            nul.append(h[:16])

    rep.add(ERROR if mismatched else OK, "E1",
            "%d content blob(s) do not hash to their content_hash" % len(mismatched)
            if mismatched else "every content blob hashes to its content_hash",
            examined="%d blobs" % len(rows), examples=mismatched,
            why="content_blobs is content-addressed: the hash IS the identity. A mismatch "
                "means the payload was altered after hashing (a scrub applied on the way in, "
                "for instance), so the reuse index will never match this entity again.",
            ask="the hashes above.")

    rep.add(ERROR if nul else OK, "E2",
            "%d stored blob(s) contain a NUL character" % len(nul) if nul
            else "no stored blob contains a NUL character",
            examined="%d blobs" % len(rows), examples=nul,
            why="PostgreSQL cannot represent a NUL in text or jsonb. If one is stored the "
                "scrub was bypassed, and the next write of the same content will fail.")

    with ctx.eng.connect() as cx:
        dangling = [r[0] for r in cx.execute(sa.text(
            "select distinct ev.content_hash from entity_versions ev "
            "left join content_blobs b on b.content_hash = ev.content_hash "
            "where ev.version_id in :vids and ev.content_hash is not null "
            "and b.content_hash is null"
        ).bindparams(sa.bindparam("vids", expanding=True)), {"vids": ctx.vids or [""]})]
    rep.add(ERROR if dangling else OK, "E3",
            "%d entity payload pointer(s) have no blob" % len(dangling) if dangling
            else "every entity payload pointer resolves to a blob",
            examined="%d versions" % len(ctx.vids),
            examples=[h[:16] for h in dangling],
            why="The entity reads back with no payload — no parameters, no description.")


def _has_nul(value):
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    return False


# ---------------------------------------------------------------------------
# F. include map
# ---------------------------------------------------------------------------
def check_include_map(ctx, rep):
    rep.start("F. INCLUDE MAP — can a header change reach the files that include it?")
    from core import model_store
    for v in ctx.versions:
        with ctx.eng.connect() as cx:
            m = model_store.load_tu_includes(cx, v["id"]) or {}
        if not m:
            rep.add(WARN, "F1", "%s: no include map stored" % v["id"], examined="0 TUs",
                    why="A narrowed parse against this version as a baseline cannot narrow "
                        "anything and falls back to a full parse — correct, but slow.")
            continue
        src = {k: hs for k, hs in m.items() if (k or "").lower().endswith(_SRC_EXTS)}
        edges = sum(len(h or []) for h in src.values())
        per = (edges / len(src)) if src else 0.0
        zero = sorted(k for k, h in src.items() if not h)
        rep.add(WARN if src and per < 5.0 else OK, "F2",
                "%s: %.1f in-repo headers per source file (%d files)" % (v["id"], per, len(src)),
                examined="%d TUs, %d source files" % (len(m), len(src)),
                examples=zero[:_MAX_EXAMPLES],
                why="Real C/C++ sources include tens of in-repo headers each. A low figure "
                    "means #include resolution failed, and the narrowed parse then "
                    "under-selects: a changed HEADER reaches nothing. Editing a .c still "
                    "works because a changed .c matches itself directly.",
                ask="this number and whether a compile_commands.json is configured for the "
                    "project's cores.")


# ---------------------------------------------------------------------------
# G. output vs database
# ---------------------------------------------------------------------------
def check_outputs(ctx, rep):
    rep.start("G. OUTPUT — does the rendered document match what the database holds?")
    sa = ctx.sa
    for v in ctx.versions:
        vid = v["id"]
        with ctx.eng.connect() as cx:
            n_out = cx.execute(sa.text(
                "select count(*) from version_output_files where version_id = :v"),
                {"v": vid}).scalar() or 0
            docs = [r[0] for r in cx.execute(sa.text(
                "select docx_path from documents where version_id = :v"), {"v": vid})]
        rep.add(WARN if not n_out else OK, "G1",
                "%s: %d stored output file(s)" % (vid, n_out),
                examined="%d rows" % n_out,
                why="Phase 3 renders these and the API reads them from the database. Zero "
                    "means the capture step did not run, so the UI has no views for this "
                    "version even though the document may exist on disk.")

        missing = [p for p in docs if p and not os.path.isfile(
            p if os.path.isabs(p) else os.path.join(_ROOT, p))]
        rep.add(WARN if missing else OK, "G2",
                "%s: %d recorded document(s) are not on disk" % (vid, len(missing))
                if missing else "%s: every recorded document exists on disk" % vid,
                examined="%d documents" % len(docs), examples=missing,
                why="The row says a document was produced; the file is gone. Anything "
                    "reading the path gets an error instead of a document.")

        # The DB is the authority for the DOTs; disk is what the DOCX embedded.
        dots, pngs = ctx.dots(vid), ctx.pngs(vid)
        if dots and pngs:
            no_png = sorted("%s|%s" % k for k in dots
                            if not any(f.startswith("%s_%s" % k) for f in pngs))
            rep.add(WARN if no_png else OK, "G3",
                    "%s: %d flowchart(s) have a graph but no image" % (vid, len(no_png))
                    if no_png else "%s: every stored flowchart has an image" % vid,
                    examined="%d graphs, %d images" % (len(dots), len(pngs)),
                    examples=no_png,
                    why="The document has a flowchart section with an empty picture slot. "
                        "Expected when image rendering is off; a defect when it is on.")


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--versions", help="comma-separated subset; default every version")
    ap.add_argument("--out", default="audit_report.txt",
                    help="write the report here as well as to the console")
    a = ap.parse_args(argv)

    try:
        import sqlalchemy as sa
        from core.db import get_engine, database_url, _redact
        from api.db.postgres import schema as s
        eng = get_engine()
    except Exception as exc:
        print("cannot reach the database: %s" % exc, file=sys.stderr)
        return 2

    ctx = Ctx(eng, sa, s, a.project_id, a.versions)
    if not ctx.versions:
        print("no versions for project %r (or --versions matched none)." % a.project_id)
        return 2

    rep = Report()
    rep.start("CONTEXT")
    try:
        dsn = _redact(database_url())
    except Exception:
        dsn = "?"
    rep.add(INFO, "CTX", "project %s on %s" % (a.project_id, dsn),
            examined="%d versions" % len(ctx.versions),
            examples=["%-10s commit=%-13s decision=%-12s baseline=%-10s status=%s"
                      % (v["id"], (v["commit"] or "?")[:12], v["decision"] or "?",
                         v["baseline"] or "-", v["status"] or "?")
                      for v in ctx.versions])

    for fn in (check_versions, check_hashes, check_incremental,
               check_model_shape, check_storage, check_include_map, check_outputs):
        try:
            fn(ctx, rep)
        except Exception as exc:                      # one broken check must not hide the rest
            rep.add(WARN, "X", "%s could not run: %s: %s"
                    % (fn.__name__, type(exc).__name__, exc), examined="0")

    body = rep.render()
    n_err, n_warn = len(rep.errors), len(rep.warnings)
    tail = ["", "=" * 78, "SUMMARY - paste this whole file back if anything failed", "=" * 78,
            "  %d FAIL, %d warn, %d checks run" % (n_err, n_warn, len(rep.rows)),
            "  project %s, versions: %s" % (a.project_id, ", ".join(ctx.vids)),
            "", "  The report contains names, paths, hashes and counts - no source code,",
            "  no comments and no LLM-generated text."]
    if n_err:
        tail += ["", "  FAILED CHECKS:"]
        tail += ["    %-5s %s" % (r[2], r[3]) for r in rep.errors]
    else:
        tail += ["", "  Nothing failed. Note what each check EXAMINED above: a check that",
                 "  looked at 0 rows proves nothing, and says so rather than passing."]
    text = body + "\n" + "\n".join(tail) + "\n"
    # ASCII-only: this file is meant to be copied out of a Windows console, whose cp1252
    # codepage turns anything else into replacement characters. A mangled report is one more
    # thing to explain when the whole point is to explain the findings.
    text = text.encode("ascii", "replace").decode("ascii")
    print(text)
    try:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("written to %s" % a.out)
    except OSError as exc:
        print("could not write %s: %s" % (a.out, exc), file=sys.stderr)
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
