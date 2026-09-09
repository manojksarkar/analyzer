#!/usr/bin/env python3
"""Check what the analyzer stored, and report ONLY what looks wrong.

`dump_db.py` writes everything, which is unreadable once a project is real. This runs the
consistency checks instead and prints findings — a clean database produces a handful of lines
saying so.

Every check below exists because the condition it looks for actually happened here, and none of
them raised an error at the time:

  * a version whose `pipeline_status` never reached a terminal state was silently skipped as a
    baseline, giving 0% reuse on every later run;
  * `versions.base_path` left NULL made the flowchart engine resolve every source file against
    "", so every flowchart came back empty with the run still reporting success;
  * a `content_hash` with no `content_blobs` row reads back as an entity with no payload;
  * an empty `llm_description_cache` after an LLM run means every description is being re-paid
    for on the next run.

    python tools/check_db.py                     # console + check_db_report.txt
    python tools/check_db.py --version ver123    # one version
    python tools/check_db.py --quiet             # findings only, no OK lines

Exit 0 = nothing wrong found. 1 = findings. 2 = could not run the checks.
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_ROOT, os.path.join(_ROOT, "engine")]

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
_MAX_EXAMPLES = 5


class Report:
    """Findings plus a record of what was CHECKED, so a clean run is distinguishable from a
    run that checked nothing — the vacuous-pass failure this codebase has hit repeatedly."""

    def __init__(self):
        self.items = []
        self.checks = 0

    def check(self, ok: bool, level: str, headline: str, examples=None, fix: str = ""):
        self.checks += 1
        if not ok:
            self.items.append((level, headline, list(examples or [])[:_MAX_EXAMPLES], fix))

    def note(self, headline: str, examples=None):
        self.items.append((INFO, headline, list(examples or [])[:_MAX_EXAMPLES], ""))

    @property
    def errors(self):
        return [i for i in self.items if i[0] == ERROR]

    @property
    def warnings(self):
        return [i for i in self.items if i[0] == WARN]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=None, help="restrict the per-version checks")
    ap.add_argument("--out", default=None,
                    help="also write the report to this file (default: stdout only)")
    ap.add_argument("--quiet", action="store_true", help="findings only")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import sqlalchemy as sa
    from api.db.postgres import schema as s
    from core.db import database_url, get_engine, require_database, _redact, DatabaseUnavailable

    try:
        require_database()
    except DatabaseUnavailable as exc:
        print(exc)
        return 2

    eng = get_engine()
    r = Report()
    lines = []

    def scalar(q):
        with eng.connect() as cx:
            return cx.execute(q).scalar()

    def rows(q, n=_MAX_EXAMPLES + 1):
        with eng.connect() as cx:
            return cx.execute(q.limit(n)).all()

    # ---------------------------------------------------------------- versions
    vq = sa.select(s.versions)
    if args.version:
        vq = vq.where(s.versions.c.id == args.version)
    with eng.connect() as cx:
        versions = cx.execute(vq).mappings().all()

    if not versions:
        print("no versions in the database — generate one first, or check --version")
        return 2

    terminal = {"complete", "failed"}
    bad_status = [v["id"] for v in versions if (v["pipeline_status"] or "") not in terminal]
    r.check(not bad_status, ERROR,
            f"{len(bad_status)} version(s) never reached a terminal pipeline_status",
            bad_status,
            "Such a version is skipped as a baseline, so later runs report 0% reuse. A run that "
            "died mid-phase leaves this; delete the version or re-run it.")

    for col, why in (("base_path", "the flowchart engine resolves every source file from it — "
                                   "NULL means empty flowcharts with no error"),
                     ("project_name", "the DOCX cover and 1.1 Purpose use it"),
                     ("parse_fingerprint", "narrowed parse compares it to the baseline; without "
                                           "it the gate cannot run and every parse is full")):
        missing = [v["id"] for v in versions if not v[col]]
        r.check(not missing, ERROR if col == "base_path" else WARN,
                f"{len(missing)} version(s) have no {col}", missing, why)

    inc = [v for v in versions if (v["decision"] or "") == "incremental"]
    ids = {v["id"] for v in versions}
    orphan_base = [v["id"] for v in inc if v["baseline_version_id"]
                   and v["baseline_version_id"] not in ids]
    r.check(not orphan_base, ERROR,
            f"{len(orphan_base)} incremental version(s) name a baseline that does not exist",
            orphan_base, "The baseline was deleted; this version's reuse cannot be explained.")

    # ------------------------------------------------------- model completeness
    ev, cb, ent = s.entity_versions, s.content_blobs, s.entities
    for v in versions:
        vid = v["id"]
        n_ev = scalar(sa.select(sa.func.count()).select_from(ev).where(ev.c.version_id == vid))
        r.check(n_ev > 0, ERROR, f"version {vid} has NO entity_versions rows", [vid],
                "Phase 1 stored nothing. The document for this version cannot be rebuilt.")
        if not n_ev:
            continue

        dangling = rows(sa.select(ev.c.entity_key if "entity_key" in ev.c else ev.c.entity_id)
                        .select_from(ev.outerjoin(cb, cb.c.content_hash == ev.c.content_hash))
                        .where((ev.c.version_id == vid) & ev.c.content_hash.isnot(None)
                               & cb.c.content_hash.is_(None)))
        r.check(not dangling, ERROR,
                f"version {vid}: {len(dangling)} entity_version(s) point at a missing content blob",
                [str(x[0]) for x in dangling],
                "The payload is gone, so those entities read back empty.")

        n_kb = scalar(sa.select(sa.func.count()).select_from(s.knowledge_base)
                      .where(s.knowledge_base.c.version_id == vid))
        r.check(n_kb == 1, WARN, f"version {vid}: knowledge_base rows = {n_kb} (expected 1)", [vid],
                "Phase 2 builds descriptions WITHOUT repo-map/sibling context when this is absent "
                "— no error, just worse prose.")

        n_tu = scalar(sa.select(sa.func.count()).select_from(s.tu_includes)
                      .where(s.tu_includes.c.version_id == vid))
        r.check(n_tu > 0, WARN, f"version {vid}: no tu_includes rows", [vid],
                "Narrowed parse needs this to work out which TUs a change affects; without it "
                "every run does a full parse.")

        snaps = {x[0] for x in rows(sa.select(s.parse_snapshots.c.name)
                                    .where(s.parse_snapshots.c.version_id == vid), 50)}
        want = {"functions.json", "globalVariables.json", "dataDictionary.json", "hashes.json",
                "edges.json", "entity_files.json", "func_keys.json", "override_pairs.json",
                "metadata.json"}
        gap = want - snaps
        r.check(not gap, WARN, f"version {vid}: parse snapshot missing {len(gap)} artifact(s)",
                sorted(gap),
                "A narrowed parse against this baseline will fall back to a full parse.")

    # -------------------------------------------------------------- description
    # Descriptions live in content_blobs payloads; count entities that have none.
    for v in versions[:3]:                       # a sample is enough to spot a systemic gap
        vid = v["id"]
        n_fn = scalar(sa.select(sa.func.count()).select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id))
                      .where((ev.c.version_id == vid) & (ent.c.kind == "function")))
        if not n_fn:
            continue
        described = scalar(
            sa.select(sa.func.count())
            .select_from(ev.join(ent, ent.c.entity_id == ev.c.entity_id)
                         .join(cb, cb.c.content_hash == ev.c.content_hash))
            .where((ev.c.version_id == vid) & (ent.c.kind == "function")
                   & sa.cast(cb.c.payload, sa.Text).like('%"description"%')))
        pct = (described * 100 // n_fn) if n_fn else 0
        r.check(pct >= 50 or described == 0, WARN,
                f"version {vid}: only {described}/{n_fn} function(s) ({pct}%) carry a description",
                [vid], "Expected when LLM is off. With LLM on it means enrichment is not landing.")
        if described == 0:
            r.note(f"version {vid}: no function descriptions stored (LLM off for this run?)")

    # ------------------------------------------------------------------ caches
    lc = s.llm_description_cache
    ns_rows = rows(sa.select(lc.c.namespace, sa.func.count())
                   .group_by(lc.c.namespace), 20)
    ns = {x[0]: x[1] for x in ns_rows}
    total_cache = sum(ns.values())
    r.check(total_cache > 0, WARN, "llm_description_cache is EMPTY",
            [], "Every description and flowchart label will be regenerated on the next run. "
                "Expected only if every run so far used --no-llm.")
    if total_cache:
        for want_ns, what in (("llm_descriptions", "function descriptions"),
                              ("aux_descriptions", "struct/unit summaries"),
                              ("flowchart_labels", "flowchart node labels")):
            r.check(want_ns in ns, WARN,
                    f"no '{want_ns}' rows in llm_description_cache ({what} are not cached)",
                    sorted(ns), f"Those calls are re-paid on every run.")
        r.note("llm_description_cache namespaces: "
               + ", ".join(f"{k}={v}" for k, v in sorted(ns.items())))

    # ------------------------------------------------------------- reuse index
    ri = s.reuse_index
    n_ri = scalar(sa.select(sa.func.count()).select_from(ri))
    stale = rows(sa.select(ri.c.fingerprint).select_from(
        ri.outerjoin(s.versions, s.versions.c.id == ri.c.version_id))
        .where(s.versions.c.id.is_(None)))
    r.check(not stale, WARN,
            f"reuse_index has {len(stale)} pointer(s) to versions that no longer exist",
            [str(x[0])[:16] for x in stale],
            "Those fingerprints can never resolve; harmless but they never expire.")
    r.check(n_ri > 0 or len(versions) < 2, INFO, "reuse_index is empty", [],
            "Cross-version reuse cannot happen until a run seeds it.")

    # ------------------------------------------------------- orphans / garbage
    orphan_out = scalar(sa.select(sa.func.count()).select_from(
        s.version_output_files.outerjoin(
            s.versions, s.versions.c.id == s.version_output_files.c.version_id))
        .where(s.versions.c.id.is_(None)))
    r.check(not orphan_out, WARN,
            f"{orphan_out} version_output_files row(s) belong to a deleted version", [],
            "Cascade should have removed these.")

    unref = scalar(sa.select(sa.func.count()).select_from(
        cb.outerjoin(ev, ev.c.content_hash == cb.c.content_hash))
        .where(ev.c.content_hash.is_(None)))
    if unref:
        r.note(f"{unref} content_blob(s) are referenced by no entity_version "
               f"(dead weight from deleted versions; not an error)")

    # ---------------------------------------------------------------- output
    lines.append("=" * 78)
    lines.append("ANALYZER DATABASE CHECK")
    lines.append("=" * 78)
    lines.append(f"database : {_redact(database_url())}")
    lines.append(f"versions : {len(versions)}" + (f"  (filtered to {args.version})"
                                                  if args.version else ""))
    lines.append(f"checks   : {r.checks}")
    lines.append("")

    if r.checks == 0:
        lines.append("FAIL - ran ZERO checks, so a pass here would mean nothing.")
        print("\n".join(lines))
        return 2

    for level in (ERROR, WARN, INFO):
        group = [i for i in r.items if i[0] == level]
        if not group:
            continue
        lines.append("-" * 78)
        lines.append(f"{level}  ({len(group)})")
        lines.append("-" * 78)
        for _lvl, headline, examples, fix in group:
            lines.append(f"  * {headline}")
            for ex in examples:
                lines.append(f"      - {ex}")
            if fix:
                for ln in _wrap(fix, 72):
                    lines.append(f"      {ln}")
            lines.append("")

    lines.append("=" * 78)
    if r.errors:
        lines.append(f"RESULT: {len(r.errors)} error(s), {len(r.warnings)} warning(s) "
                     f"out of {r.checks} checks.")
    elif r.warnings:
        lines.append(f"RESULT: no errors; {len(r.warnings)} warning(s) out of {r.checks} checks.")
    else:
        lines.append(f"RESULT: all {r.checks} checks passed — nothing looks wrong.")
    lines.append("=" * 78)

    text = "\n".join(lines)
    if not args.quiet or r.errors or r.warnings:
        print(text)
    # Only when asked. It used to drop check_db_report.txt into the working directory
    # on every run, which for a command you run in order to LOOK at something is litter.
    if args.out:
        out = os.path.abspath(args.out)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"\nwritten to {out}  ({os.path.getsize(out):,} bytes)")
    return 1 if (r.errors or r.warnings) else 0


def _wrap(text: str, width: int):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


if __name__ == "__main__":
    raise SystemExit(main())
