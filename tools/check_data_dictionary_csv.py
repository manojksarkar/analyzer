#!/usr/bin/env python3
"""Pre-flight validator for the external data-dictionary CSV (`--data-dictionary`).

The merge in `engine/parser.py::_merge_external_data_dictionary` is deliberately
forgiving: a row it cannot understand is skipped, not reported, and the run
continues to produce a document with every range showing "NA". This tool reads the
CSV the SAME way the parser does and says out loud what the parser stays quiet
about.

    python tools/check_data_dictionary_csv.py <csv>
    python tools/check_data_dictionary_csv.py <csv> --model-dir model
    python tools/check_data_dictionary_csv.py <csv> --model-dir model --quiet

Three passes, each usable on its own:

  A/B. STRUCTURE (csv only)    encoding, delimiter, header, and every row the
                               merge would silently drop, duplicate or wipe.
  C.   APPLIED   (--model-dir) did each row actually land in dataDictionary.json?
                               The merge writes top-level rows UNCONDITIONALLY, so
                               a name missing from the model means the CSV never
                               ran for that model — not that the type was rejected.
  D.   NA AUDIT  (--model-dir) every parameter / return / global type that still
                               resolves to "NA" through the real `get_range`, split
                               into "the CSV should have fixed this" and "add these
                               names to the CSV". This is the actionable list.

Exit code is 1 when any ERROR was found, else 0 — so CI or a wrapper script can
gate a pipeline run on it.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ERROR, WARN, INFO, OK = "ERROR", "WARN", "INFO", "OK"

# Columns the merge reads. Anything else in the header is ignored by the parser,
# which is exactly why a renamed column has to be reported here.
EXPECTED_COLUMNS = ["Name", "Kind", "EntryName", "Range", "Comment"]

# Kinds the merge or the views give meaning to. `enumerator`/`field` are child
# rows; the rest are top-level. A blank Kind defaults to `typedef` in the merge.
TOP_LEVEL_KINDS = {"typedef", "enum", "define", "struct", "class", "primitive"}
CHILD_KINDS = {"enumerator", "field"}

# Kinds whose child list the merge RESETS on a top-level row (parser.py:2262-2265).
RESETTING_KINDS = {"enum": "enumerators", "struct": "fields", "class": "fields"}

# `0-255`, `0-0xFF`, `-0x80-0x7F`, `-1-1`, plus the two sentinels the views print.
_NUM = r"-?(?:0[xX][0-9a-fA-F]+|\d+)"
RANGE_RE = re.compile(rf"^(?:NA|VOID|{_NUM}\s*-\s*{_NUM})$")

# A type key the rest of the pipeline can look up. `get_range` normalises away
# const/volatile/*/& before the lookup, so those must not be baked into a Name.
IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*$")


class Report:
    """Findings, grouped by pass, printed in one block at the end."""

    def __init__(self, limit: int = 20, quiet: bool = False):
        self.limit = limit
        self.quiet = quiet
        self.sections: list = []
        self.counts: Counter = Counter()

    def section(self, title: str) -> None:
        self.sections.append((title, []))

    def add(self, level: str, msg: str, detail: str = "", fix: str = "") -> None:
        self.counts[level] += 1
        if not self.sections:
            self.section("General")
        self.sections[-1][1].append((level, msg, detail, fix))

    def names(self, items: list) -> str:
        """Render a name list capped at --limit so a broken CSV cannot flood stdout."""
        shown = ", ".join(str(i) for i in items[: self.limit])
        extra = len(items) - self.limit
        return shown + (f", +{extra} more" if extra > 0 else "")

    def emit(self) -> int:
        for title, items in self.sections:
            if self.quiet:
                items = [i for i in items if i[0] in (ERROR, WARN)]
            if not items:
                continue
            print(f"\n=== {title} ===")
            for level, msg, detail, fix in items:
                print(f"  [{level:5}] {msg}")
                if detail:
                    for line in detail.splitlines():
                        print(f"           {line}")
                if fix:
                    print(f"           -> {fix}")
        print(f"\n{self.counts[ERROR]} error(s), {self.counts[WARN]} warning(s).")
        return 1 if self.counts[ERROR] else 0


# ---------------------------------------------------------------------------
# Pass A - file and header
# ---------------------------------------------------------------------------

def read_csv(path: str, rep: Report):
    """Read the file exactly as the parser does, reporting what would break it.

    The parser opens with `encoding="utf-8"` and catches only `csv.Error` - a
    cp1252-encoded export therefore raises an uncaught UnicodeDecodeError and
    kills Phase 1, so the encoding check is a hard error, not a nicety.
    """
    rep.section("A. File and header")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        rep.add(ERROR, f"cannot read {path}", str(exc))
        return None, []

    if not raw.strip():
        rep.add(ERROR, "file is empty", fix="Phase 1 aborts with sys.exit(2) on an empty CSV.")
        return None, []

    if raw.startswith(b"\xef\xbb\xbf"):
        rep.add(INFO, "UTF-8 BOM present", "The merge strips it from the header names.")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        rep.add(
            ERROR,
            "file is not UTF-8",
            str(exc),
            "Re-save as 'CSV UTF-8'. The parser opens with encoding='utf-8' and does "
            "NOT catch UnicodeDecodeError, so this aborts Phase 1 with a traceback.",
        )
        return None, []

    lines = text.splitlines()
    header = lines[0] if lines else ""
    commas, semis, tabs = header.count(","), header.count(";"), header.count("\t")
    if commas == 0 and (semis or tabs):
        rep.add(
            ERROR,
            f"header is not comma-delimited (found {semis} ';' and {tabs} tab)",
            f"header: {header[:120]}",
            "csv.DictReader is called with the default comma delimiter. Re-export "
            "with commas, or every row lands in one column and nothing merges.",
        )

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        rep.add(ERROR, "no header row", fix="Phase 1 aborts with sys.exit(2).")
        return None, []

    # Same normalisation the merge applies (parser.py:2197).
    fieldnames = [f.lstrip("﻿").strip() for f in reader.fieldnames]
    reader.fieldnames = fieldnames

    missing = [c for c in EXPECTED_COLUMNS if c not in fieldnames]
    unknown = [c for c in fieldnames if c and c not in EXPECTED_COLUMNS]
    if "Name" in missing:
        rep.add(
            ERROR,
            "no 'Name' column",
            f"header: {fieldnames}",
            "row.get('Name') is None for every row, so EVERY row is skipped and the "
            "merge reports 0 entries with no other sign of failure. A title row above "
            "the real header does this too.",
        )
    elif missing:
        rep.add(WARN, f"missing column(s): {', '.join(missing)}",
                fix="Read as empty. No Range column means no range is ever set.")
    if unknown:
        rep.add(WARN, f"column(s) the merge ignores: {', '.join(unknown)}",
                fix=f"Only {', '.join(EXPECTED_COLUMNS)} are read.")
    if not missing and not unknown:
        rep.add(OK, f"header matches: {', '.join(fieldnames)}")

    rows = [(reader.line_num, row) for row in reader]
    rep.add(INFO, f"{len(rows)} data row(s)")
    return fieldnames, rows


# ---------------------------------------------------------------------------
# Pass B - rows
# ---------------------------------------------------------------------------

def check_rows(rows: list, rep: Report) -> dict:
    """Row checks that mirror the merge's own branching, in the same order.

    Returns {top-level Name -> {kind, range, line, children}} for the later passes.
    """
    rep.section("B. Rows")
    parent_key = None
    top: dict = {}
    name_lines: dict = defaultdict(list)
    silently_dropped: list = []
    orphans: list = []
    overflow: list = []
    bad_range: list = []
    bad_name: list = []
    empty_range: list = []
    odd_kind: dict = defaultdict(list)

    for lineno, row in rows:
        # A field beyond the header lands under the restkey (None) - always an
        # unquoted comma inside Comment, which shifts every column after it.
        if row.get(None):
            overflow.append(lineno)

        name = (row.get("Name") or "").strip()
        kind = (row.get("Kind") or "").strip().lower()
        entry_nm = (row.get("EntryName") or "").strip()
        range_v = (row.get("Range") or "").strip()
        comment = (row.get("Comment") or "").strip()

        if not any((name, kind, entry_nm, range_v, comment)):
            continue  # blank separator line - harmless, the merge skips it too

        if not name and kind in CHILD_KINDS:
            # The merge also requires the parent to EXIST in the dictionary; here we
            # can only see whether a parent row appeared above it in the file.
            if parent_key is None or not entry_nm:
                orphans.append(lineno)
                continue
            top[parent_key]["children"].append((kind, entry_nm, range_v, lineno))
            if kind == "enumerator" and range_v and not re.fullmatch(r"-?\d+", range_v):
                bad_range.append(
                    f"L{lineno} {entry_nm}={range_v!r} (enumerator value must be an integer)")
            continue

        if not name:
            # `if not name: continue` in the merge - counted NOWHERE in its report.
            silently_dropped.append(
                f"L{lineno} Kind={kind or '(blank)'} EntryName={entry_nm or '(blank)'}")
            continue

        name_lines[name].append(lineno)
        parent_key = name
        effective_kind = kind or "typedef"

        if effective_kind not in TOP_LEVEL_KINDS:
            odd_kind[effective_kind].append(lineno)
        if not IDENT_RE.match(name):
            bad_name.append(f"L{lineno} {name!r}")
        if range_v and not RANGE_RE.match(range_v):
            bad_range.append(f"L{lineno} {name} Range={range_v!r}")
        if not range_v and effective_kind not in RESETTING_KINDS:
            empty_range.append(f"L{lineno} {name}")

        # A repeated Name overwrites the earlier entry, exactly as the merge does.
        top[name] = {"kind": effective_kind, "range": range_v, "line": lineno, "children": []}

    if overflow:
        rep.add(ERROR, f"{len(overflow)} row(s) have more fields than the header",
                f"lines: {rep.names(overflow)}",
                "An unquoted comma inside Comment. Every column after it is shifted, "
                "so Range holds the wrong text.")
    if silently_dropped:
        rep.add(ERROR, f"{len(silently_dropped)} row(s) will be dropped with NO trace",
                rep.names(silently_dropped),
                "Empty Name with a Kind that is not enumerator/field. The merge counts "
                "these in neither 'merged' nor 'orphan children' - this is what a "
                "merged-cell Excel export turns into.")

    dupes = {n: ls for n, ls in name_lines.items() if len(ls) > 1}
    if dupes:
        listed = [f"{n} (lines {', '.join(str(l) for l in ls)})" for n, ls in dupes.items()]
        rep.add(ERROR, f"{len(dupes)} duplicated Name(s)", rep.names(listed),
                "Last row wins. Worse, the second occurrence sees the entry the FIRST "
                "one wrote, so the merge report files it under 'matched a parsed type' "
                "even when the type is not in the source at all.")

    if orphans:
        rep.add(WARN, f"{len(orphans)} orphan child row(s)", f"lines: {rep.names(orphans)}",
                "No parent Name above them, or an empty EntryName. Skipped.")
    if bad_name:
        rep.add(WARN, f"{len(bad_name)} Name(s) are not plain type identifiers",
                rep.names(bad_name),
                "get_range strips const/volatile/*/& off the type BEFORE the lookup, so "
                "a Name carrying them can never match.")
    if bad_range:
        rep.add(WARN, f"{len(bad_range)} suspicious Range value(s)", rep.names(bad_range),
                "Expected NA, VOID, or <low>-<high> in decimal or 0x hex.")
    if empty_range:
        rep.add(WARN, f"{len(empty_range)} row(s) with an empty Range", rep.names(empty_range),
                "The merge only sets `range` when the cell is non-empty. For a type not "
                "present in the source that leaves it resolving to NA anyway.")
    for kind, lines in odd_kind.items():
        rep.add(WARN, f"unrecognised Kind {kind!r} on {len(lines)} row(s)",
                f"lines: {rep.names(lines)}",
                f"Stored verbatim. Known: {', '.join(sorted(TOP_LEVEL_KINDS | CHILD_KINDS))}.")

    # A top-level enum/struct row RESETS its child list before child rows append.
    # With no child rows below it, that reset is pure destruction of parsed data.
    wipers = [f"L{v['line']} {n} (kind={v['kind']})"
              for n, v in top.items()
              if v["kind"] in RESETTING_KINDS and not v["children"]]
    if wipers:
        rep.add(ERROR, f"{len(wipers)} row(s) will WIPE parsed children", rep.names(wipers),
                "A top-level enum/struct/class row resets enumerators/fields to [] and no "
                "child rows follow it, so libclang's own enumerator list is lost. Either "
                "list every child under it, or drop the row.")

    rep.add(INFO, f"{len(top)} distinct top-level name(s), "
                  f"{sum(len(v['children']) for v in top.values())} child row(s) attached")
    return top


# ---------------------------------------------------------------------------
# Pass C/D - cross-check against a generated model
# ---------------------------------------------------------------------------

def load_model(model_dir: str, rep: Report) -> dict:
    out: dict = {}
    for key, fname in (("dd", "dataDictionary.json"), ("fn", "functions.json"),
                       ("gv", "globalVariables.json")):
        path = os.path.join(model_dir, fname)
        try:
            with open(path, encoding="utf-8") as fh:
                out[key] = json.load(fh)
        except (OSError, ValueError) as exc:
            rep.add(WARN, f"cannot read {fname}", str(exc))
            out[key] = None
    return out


def dd_key(dd: dict, name: str, layer=None):
    """The dataDictionary key that answers for `name` in `layer`, or None.

    Mirrors `parser._dd_target_key` / `utils._visible_to_layer`: a layer's rows land
    on `name@<layer>` whenever the bare slot is owned by the global tier or another
    layer, so a bare-name lookup reports a perfectly applied layer CSV as "never
    reached the model". An entry stamped with a DIFFERENT layer is not an answer.
    """
    if layer:
        qualified = f"{name}@{layer}"
        if qualified in dd:
            return qualified
    entry = dd.get(name)
    if entry is None:
        return None
    if layer and entry.get("layer") not in (None, layer):
        return None
    return name


def check_applied(top: dict, dd: dict, rep: Report, layer=None) -> None:
    """Did the rows actually reach dataDictionary.json?

    The merge writes every top-level row unconditionally, so this is a clean
    yes/no on whether the CSV was in play when this model was generated.

    `layer` is the scope the CSV was merged under (`--data-dictionary-layer`); its
    rows are keyed `name@<layer>` when the bare name belongs to someone else.
    """
    rep.section("C. Did the CSV apply to this model?"
                + (f"  [layer {layer}]" if layer else ""))
    keys = {n: dd_key(dd, n, layer) for n in top}
    applied = [n for n in top if keys[n] is not None]
    missing = [n for n in top if keys[n] is None]

    if top and not applied:
        rep.add(ERROR, "NOT ONE row from this CSV is in dataDictionary.json",
                f"{len(missing)} name(s) checked",
                "The merge adds top-level rows unconditionally, so this model was "
                "generated WITHOUT --data-dictionary. There is no config.json key for "
                "it; check the run command, and note the web path silently omits the "
                "flag when workspaces/<pid>/datadict/<id>.csv is absent (an .xlsx "
                "upload is accepted but never converted).")
        return
    if missing:
        rep.add(ERROR, f"{len(missing)} row(s) did not reach the model", rep.names(missing),
                "The CSV ran but these names are absent - a stale model, or the rows "
                "were dropped structurally (see pass B).")
    if applied:
        rep.add(OK, f"{len(applied)} row(s) present in dataDictionary.json")

    # The wipe, observed in the model rather than predicted from the CSV.
    wiped = [n for n, v in top.items()
             if v["kind"] in RESETTING_KINDS and keys[n] is not None
             and not (dd[keys[n]].get(RESETTING_KINDS[v["kind"]]) or [])]
    if wiped:
        rep.add(ERROR, f"{len(wiped)} model entry(ies) have an EMPTY child list",
                rep.names(wiped),
                "The CSV row reset enumerators/fields and nothing refilled them. Any "
                "view listing enumerator values now prints nothing for these types.")

    # Being present is not the same as being useful.
    no_range = [n for n in applied
                if not str(dd[keys[n]].get("range") or "").strip()
                or str(dd[keys[n]].get("range")).strip() == "NA"]
    if no_range:
        rep.add(WARN, f"{len(no_range)} applied row(s) still carry no usable range",
                rep.names(no_range),
                "Present in the model but range is empty or 'NA', so the interface "
                "tables still print NA for them.")


def collect_used_types(fn: dict, gv: dict) -> Counter:
    """Every type spelling the interface tables ask `get_range` about."""
    used: Counter = Counter()
    for f in (fn or {}).values():
        for p in f.get("parameters") or []:
            t = (p.get("type") or "").strip()
            if t:
                used[t] += 1
        rt = (f.get("returnType") or "").strip()
        if rt:
            used[rt] += 1
    for g in (gv or {}).values():
        t = (g.get("type") or "").strip()
        if t:
            used[t] += 1
    return used


def _base_type(type_str: str) -> str:
    """The key `get_range` actually looks up, mirroring its normalisation.

    Kept in step with `utils.get_range` deliberately: this is only used to BUCKET a
    finding, never to decide the range itself, so a small divergence mislabels a
    line of advice rather than reporting a wrong range.
    """
    base = (type_str or "").replace("const ", "").replace("volatile ", "").strip()
    for sep in ("*", "&"):
        if sep in base:
            base = base.split(sep)[0].strip()
    return base


def _is_derived(type_str: str) -> bool:
    """Pointer, reference, array or function-pointer spelling - never a scalar."""
    return any(ch in (type_str or "") for ch in "*&[(")


def check_na(top: dict, model: dict, rep: Report, layer=None) -> None:
    rep.section("D. Types still resolving to NA"
                + (f"  [layer {layer}]" if layer else ""))
    dd, fn, gv = model.get("dd"), model.get("fn"), model.get("gv")
    if dd is None or (fn is None and gv is None):
        rep.add(WARN, "skipped - model files unavailable")
        return

    # The real resolver, imported rather than reimplemented: a second copy of the
    # precedence rules would drift from utils.py and quietly report the wrong thing.
    sys.path.insert(0, os.path.join(ROOT, "engine"))
    try:
        from utils import get_range
    except Exception as exc:  # noqa: BLE001 - any import failure means skip, not crash
        rep.add(WARN, "skipped - cannot import engine/utils.py", str(exc),
                "Run from the repo root so `engine/` and its `core` package import.")
        return

    used = collect_used_types(fn, gv)
    # Scoped like every other dictionary read: unscoped, a Layer2 entry could answer
    # for a Layer1 spelling and hide a genuinely missing row.
    na = Counter({t: c for t, c in used.items() if get_range(t, dd, layer) == "NA"})

    if not na:
        rep.add(OK, f"all {len(used)} used type spelling(s) resolve to a range")
        return

    rep.add(WARN, f"{len(na)} type spelling(s) resolve to NA "
                  f"({sum(na.values())} parameter/return/global slot(s) affected)")

    # Bucketed, because "NA" has three different meanings and only one of them is
    # a CSV row waiting to be written. Listing them together sends the author off
    # adding rows for `GG *` and for structs, neither of which can ever help.
    ineffective, aggregate, actionable = [], [], []
    for type_str, count in na.most_common():
        label = f"{type_str} (x{count})"
        base = _base_type(type_str)
        _k = dd_key(dd, base, layer) or dd_key(dd, base.lower(), layer)
        entry = dd.get(_k) or {}
        # Aggregate wins over "named in the CSV": a struct row whose Range is NA is
        # correct, not a row that failed to take effect.
        if _is_derived(type_str) or entry.get("kind") in ("struct", "class", "union"):
            aggregate.append(label)
        elif type_str in top or base in top:
            ineffective.append(label)
        else:
            actionable.append(label)

    if ineffective:
        rep.add(ERROR, f"{len(ineffective)} of them ARE named in the CSV but still NA",
                rep.names(ineffective),
                "Row present but ineffective: empty or 'NA' Range, or the CSV Name does "
                "not match the spelling used in the signature (the lookup tries the "
                "exact name first, then all-lowercase - nothing else).")
    if actionable:
        rep.add(INFO, f"{len(actionable)} unknown scalar type(s) - ADD THESE to the CSV",
                rep.names(actionable),
                "Not in the dictionary at all. Types declared outside the project "
                "(include paths) are never parsed in, so the CSV is the only way to "
                "give them a range. This is the list worth acting on.")
    if aggregate:
        rep.add(INFO, f"{len(aggregate)} aggregate/derived type(s) - NA is correct here",
                rep.names(aggregate),
                "Structs, unions, pointers, references, arrays and function pointers "
                "have no scalar range. A CSV row for these changes nothing; get_range "
                "already resolves a pointer to its pointee, so name the POINTEE if the "
                "underlying scalar is what needs a range.")


# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate a --data-dictionary CSV and explain why ranges come out NA.")
    ap.add_argument("csv_path", help="the CSV handed to --data-dictionary")
    ap.add_argument("--model-dir", default=None,
                    help="a generated model/ directory - enables the applied + NA passes")
    ap.add_argument("--layer", default=None,
                    help="the layer this CSV was merged under (--data-dictionary-layer). "
                         "Its rows are keyed name@<layer> when the bare name belongs to "
                         "the global tier or another layer; without this the model passes "
                         "report an applied CSV as missing. Omit for a project-wide CSV.")
    ap.add_argument("--limit", type=int, default=20, help="names listed per finding (default 20)")
    ap.add_argument("--quiet", action="store_true", help="print only errors and warnings")
    args = ap.parse_args()

    rep = Report(limit=args.limit, quiet=args.quiet)
    print(f"data-dictionary CSV check: {args.csv_path}")

    fieldnames, rows = read_csv(args.csv_path, rep)
    if fieldnames is None:
        return rep.emit()
    top = check_rows(rows, rep)

    if args.model_dir:
        model = load_model(args.model_dir, rep)
        if model.get("dd") is not None:
            check_applied(top, model["dd"], rep, args.layer)
            check_na(top, model, rep, args.layer)
    else:
        rep.section("C. Model cross-check")
        rep.add(INFO, "skipped - pass --model-dir model to check what actually landed")

    return rep.emit()


if __name__ == "__main__":
    sys.exit(main())
