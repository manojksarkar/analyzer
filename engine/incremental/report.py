"""End-of-run generation report (M3.4).

A human-readable summary of what a generation did — inputs (baseline/scope/commit),
change classification, and reuse accounting (regenerated vs reused per entity kind)
— so it's easy to see how incremental reuse is performing. `build_report` is pure
(takes a stats dict) so it's unit-testable; `emit_report` logs it + saves report.txt.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

_W = 64
_RULE = "=" * _W
_THIN = "-" * _W

_DOCUMENTS = {"swe3": ["SWE.3 Software Detailed Design"],
              "swe4": ["SWE.4 Software Unit Test Specification"]}
_DOCUMENTS["all"] = _DOCUMENTS["swe3"] + _DOCUMENTS["swe4"]


def _pct(part: int, whole: int) -> str:
    return f"{(100 * part // whole) if whole else 0}%"


def _line(label: str, value: Any) -> str:
    return f"  {label:<16}: {value}"


def _llm_lines(counts: Dict[str, Any]) -> List[str]:
    """The LLM section: how many calls a run made, and how many produced nothing.

    Token counts already say what was SPENT. They do not say whether the spending bought
    anything, and that gap hid a real failure: a run took 2062 seconds and produced mechanical
    flowchart labels while the gateway answered every request correctly — the replies were being
    destroyed after arrival. Tokens looked healthy throughout. "1 call in 3 returned nothing" is
    the line that would have pointed straight at it.

    `counts` is {(kind, outcome): n} flattened to {"kind|outcome": n} by the caller, summed
    across every phase subprocess.
    """
    if not counts:
        return []
    if "__unavailable__" in counts:
        return [_THIN,
                "  LLM CALLS : accounting unavailable "
                f"({counts['__unavailable__']})",
                "              Run `python analyzer.py setup` to apply the migration. Until "
                "then the",
                "              report cannot say how many LLM calls failed."]
    timing = {str(k).split("|", 1)[1]: v for k, v in counts.items()
              if str(k).startswith("__timing__|")}
    by_kind: Dict[str, Dict[str, int]] = {}
    for key, n in counts.items():
        if str(key).startswith("__timing__|"):
            continue
        kind, _, outcome = str(key).partition("|")
        by_kind.setdefault(kind, {}).setdefault(outcome, 0)
        by_kind[kind][outcome] += int(n or 0)

    tot = {"ok": 0, "empty": 0, "error": 0}
    for oc in by_kind.values():
        for k in tot:
            tot[k] += oc.get(k, 0)
    calls = sum(tot.values())
    if not calls:
        return []

    failed = tot["empty"] + tot["error"]
    L = [_THIN, "  LLM CALLS (a failed call means the caller fell back to a mechanical result)"]
    L.append(f"    Total     : {calls:<5}  answered {tot['ok']} ({_pct(tot['ok'], calls)})")
    if failed:
        L.append(f"    Failed    : {failed:<5}  empty {tot['empty']}, error {tot['error']}"
                 f"  -> {_pct(failed, calls)} of calls produced NOTHING")
    for kind in sorted(by_kind):
        oc = by_kind[kind]
        k_ok, k_empty, k_err = oc.get("ok", 0), oc.get("empty", 0), oc.get("error", 0)
        k_tot = k_ok + k_empty + k_err
        detail = f"ok {k_ok}"
        if k_empty:
            detail += f", empty {k_empty}"
        if k_err:
            detail += f", error {k_err}"
        L.append(f"      {kind:<22} {k_tot:<5}  ({detail})")
    if timing:
        _lat, _thr = timing.get("latency_seconds", 0.0), timing.get("throttle_seconds", 0.0)
        _wall = _lat + _thr
        if _wall > 0:
            L.append(f"    Time      : {_wall:.0f}s total  "
                     f"({_lat:.0f}s waiting on the model, {_thr:.0f}s in the rate-limit pause)")
            if _thr > _lat:
                L.append("                Most of it was the THROTTLE, not the model — "
                         "llm.rateLimitSeconds")
                L.append("                is the lever, and 0 disables it on an endpoint "
                         "with no limit.")
        _pt, _ct = timing.get("prompt_tokens", 0), timing.get("completion_tokens", 0)
        if _pt or _ct:
            L.append(f"    Tokens    : {_pt + _ct:<5}  ({_pt} prompt, {_ct} completion)")
    if failed:
        L.append("    A non-zero failed count means the document contains fallback text or")
        L.append("    mechanical labels. Check the log for 'empty response' / 'HTTP'.")
    return L


def build_report(stats: Dict[str, Any]) -> List[str]:
    """Build the report lines from a stats dict (see generate_incremental/full)."""
    decision = stats.get("decision", "full")
    L: List[str] = [_RULE, f"  GENERATION REPORT  -  version {stats.get('versionId')}  ({decision})", _RULE]

    L.append(_line("Project", stats.get("projectId")))
    L.append(_line("Branch / commit", f"{stats.get('branch')} / {str(stats.get('commit'))[:10]}"))
    L.append(_line("Scope", stats.get("scope")))
    if decision == "incremental":
        L.append(_line("Baseline", f"{stats.get('baselineVersionId')} @ "
                                   f"{str(stats.get('baselineCommit'))[:10]}  "
                                   f"({stats.get('changedFiles')} changed file(s) in the diff)"))
    else:
        L.append(_line("Baseline", "(none - full generation; becomes the baseline for future runs)"))
    doc_type = stats.get("docType") or "swe3"
    L.append(_line("Doc type", ", ".join(_DOCUMENTS.get(doc_type) or [doc_type])))
    L += _block("Data dictionary",
                [f"{layer} <- {path}" for layer, path in (stats.get("dataDictionaries") or {}).items()]
                + [f"project-wide: {stats.get('dataDictId') or 'none'}"])
    L.append(_line("LLM model", stats.get("llmModel")))
    L.append(_line("Status", stats.get("status")))
    if stats.get("elapsedSeconds") is not None:
        L.append(_line("Wall clock", f"{stats['elapsedSeconds']:.1f}s"))

    if decision == "incremental":
        cls = stats.get("classification") or {}
        L.append(_THIN)
        L.append("  CHANGE CLASSIFICATION (this commit vs the baseline)")
        for bucket in ("changed", "new", "deleted", "unchanged"):
            by_kind = cls.get(bucket) or {}
            total = sum(by_kind.values())
            detail = ", ".join(f"{v} {k}" for k, v in sorted(by_kind.items())) or "-"
            L.append(f"    {bucket:<10}: {total:<4} ({detail})")

    L.append(_THIN)
    L.append("  REUSE ACCOUNTING (regenerated by the LLM  vs  reused/carried)")
    fn = stats.get("functions") or {}
    gl = stats.get("globals") or {}
    # Flowcharts reuse per-FUNCTION (M3.6). Fall back to the old file-based "files"
    # block for reports produced before the split existed.
    fc = stats.get("flowcharts") or stats.get("files") or {}
    sm = stats.get("files") or {}   # file-level summaries
    L.append(f"    Functions : regenerated {fn.get('regenerated', 0):<4} / {fn.get('total', 0):<4} "
             f"-> reused {fn.get('reused', 0)} ({_pct(fn.get('reused', 0), fn.get('total', 0))})")
    L.append(f"    Globals   : regenerated {gl.get('regenerated', 0):<4} / {gl.get('total', 0):<4} "
             f"-> reused {gl.get('reused', 0)} ({_pct(gl.get('reused', 0), gl.get('total', 0))})")
    # Globals reuse legitimately runs much lower than functions, and a bare 0% reads like a
    # broken feature. A global's LLM description embeds the DESCRIPTIONS of the functions that
    # read and write it, so regenerating any of those genuinely changes the global's input —
    # it must be regenerated too. With few globals and each touched by only one or two
    # functions, a small change can invalidate all of them. Say so rather than leave the
    # number to be misread.
    #
    # This note used to describe an intention the code did not implement: a global's fingerprint
    # was its own source hash with NO dependencies, so a changed reader left it untouched and the
    # reuse index handed back a description written against the reader's old behaviour. Globals
    # now fold their accessors' hashes in, which is what makes the sentence below true.
    if gl.get("total") and not gl.get("reused"):
        L.append("                (0% is expected here: a global's description embeds its "
                 "readers'/writers' descriptions,")
        L.append("                 so every global touched by a regenerated function is "
                 "regenerated too)")
    L.append(f"    Flowcharts: regenerated {fc.get('regenerated', 0):<4} / {fc.get('total', 0):<4} function(s) "
             f"-> carried {fc.get('carried', 0)} ({_pct(fc.get('carried', 0), fc.get('total', 0))})")
    if decision == "incremental":
        L.append(f"    Summaries : {sm.get('regenerated', 0)} impacted file(s) re-summarized; the rest reused")
        # M3.7 — entities reused from the cross-version index (reverts / cross-branch),
        # i.e. copied from a non-baseline version instead of regenerated.
        xv = stats.get("crossVersion") or {}
        xv_fn, xv_gl, xv_fc = xv.get("functions", 0), xv.get("globals", 0), xv.get("flowcharts", 0)
        if xv_fn or xv_gl or xv_fc:
            L.append(f"    X-version : {xv_fn} function(s) + {xv_gl} global(s) + {xv_fc} flowchart(s) reused "
                     f"from a prior version via the content index (revert / cross-branch)")

    L.extend(_llm_lines(stats.get("llmCalls") or {}))

    L.append(_THIN)
    docs = stats.get("documents") or []
    L.append(_line("Documents", ", ".join(docs) if docs else "(none)"))
    warns = stats.get("warnings") or []
    if warns:
        L.append("  Warnings:")
        L.extend(f"    - {w}" for w in warns)
    L.append(_RULE)
    return L


def emit_report(lines: List[str], version_dir: str = None, logger_name: str = "incremental",
                *, write_file: bool = True) -> None:
    """Log each line (-> logs/run_<date>.log + stderr) and, when asked, write report.txt.

    `write_file=False` in database mode: the report is stored verbatim in `versions.report`,
    and nothing reads the file — it was write-only. Every line still goes to the log, so the
    run is no less inspectable on the machine that produced it, and now it is inspectable from
    any other node too.
    """
    try:
        from core.logging_setup import get_logger
        log = get_logger(logger_name)
        for ln in lines:
            log.info(ln)
    except Exception:
        for ln in lines:
            print(ln)
    if version_dir and write_file:
        try:
            with open(os.path.join(version_dir, "report.txt"), "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Run summary - printed BEFORE the parse
# ---------------------------------------------------------------------------

def scope_label(scope: Optional[Dict[str, Any]]) -> str:
    """`project`, or `<type>:<name>,<name>` - the form `--scope` takes."""
    stype = (scope or {}).get("type", "project")
    names = (scope or {}).get("names") or []
    return stype if (stype == "project" or not names) else f"{stype}:{','.join(names)}"


def _block(label: str, values: List[str]) -> List[str]:
    """A labelled line whose further values continue underneath it, aligned."""
    values = values or ["(none)"]
    pad = " " * len(_line(label, ""))
    return [_line(label, values[0])] + [pad + v for v in values[1:]]


def _wrap(words: List[str], width: int = _W - 20) -> List[str]:
    """Comma-joined words, broken into lines no wider than `width`."""
    lines: List[str] = []
    cur = ""
    for w in words:
        nxt = f"{cur}, {w}" if cur else w
        if cur and len(nxt) > width:
            lines.append(cur + ",")
            cur = w
        else:
            cur = nxt
    return lines + ([cur] if cur else [])


def _layer_inputs(rows) -> List[str]:
    """[(layer, path, origin, exists)] as `Layer1 <- path  (Core1)`. A layer with none says so:
    a line that is simply absent is exactly how a skipped dictionary went unnoticed."""
    out = []
    for layer, path, origin, exists in rows:
        if not path:
            out.append(f"{layer}: none")
        else:
            out.append(f"{layer} <- {path}  ({origin})" + ("" if exists else "  NOT FOUND"))
    return out


def build_run_summary(s: Dict[str, Any]) -> List[str]:
    """What a generation is about to do, from its resolved inputs. Pure - see emit_run_summary.

    Printed BEFORE the parse, which can run for hours, so a wrong scope, document type, view
    switch or dictionary is caught while stopping is still cheap. The parser's own banner shows
    only the project-wide dictionary, so a run using per-layer ones read "data dictionary :
    (none)" and the scope and document type appeared nowhere until the end.
    """
    vid, name = s.get("versionId"), s.get("versionName")
    title = f"  GENERATE  {s.get('projectId')} / {name or vid}"
    if name and name != vid:
        title += f"   (id {vid})"
    L: List[str] = [_RULE, title, _RULE]
    L.append(_line("Commit / branch", f"{str(s.get('commit'))[:10]} / {s.get('branch')}"))
    L.append(_line("Scope", s.get("scope")))
    doc_type = s.get("docType") or "swe3"
    docs = list(_DOCUMENTS.get(doc_type) or [doc_type])
    docs[0] += f"   (--doc-type {doc_type})"
    L += _block("Documents", docs)
    L += _block("Views on", _wrap(s.get("viewsOn") or []))
    L += _block("Views off", _wrap(s.get("viewsOff") or []))
    dd = _layer_inputs(s.get("dataDictionaries") or [])
    proj = s.get("projectDataDict")                    # (id, path, exists) or None
    dd.append(f"project-wide: {proj[0]} <- {proj[1]}" + ("" if proj[2] else "  NOT FOUND")
              if proj else "project-wide: none   (--data-dict)")
    L += _block("Data dictionary", dd)
    L += _block("Macros", _layer_inputs(s.get("macros") or []))
    L.append(_line("LLM", s.get("llm")))
    L.append(_line("Baseline", s.get("baseline")))
    L.append(_line("Config", s.get("config")))
    warns, errors = s.get("warnings") or [], s.get("errors") or []
    if warns:
        L += [_THIN, "  WARNINGS"] + [f"    - {w}" for w in warns]
    if errors:
        L += [_THIN, "  STOPPING BEFORE THE PARSE - fix these first:"] + [f"    - {e}" for e in errors]
    L.append(_RULE)
    return L


def config_views(cfg: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(on, off) view switches, by run_views' rule for the config-driven doc types: a view with
    no key is off, except interfaceTables and unitHeaders; any value but False is on.

    Mirrored rather than imported - importing engine.views would load every view module into
    the orchestrator. tests/unit/test_incremental_report.py holds the two to the same answer.
    """
    views = cfg.get("views") or {}
    names = list(dict.fromkeys(["interfaceTables", "unitHeaders", *views]))
    on = [n for n in names if views.get(n, n in ("interfaceTables", "unitHeaders")) is not False]
    return on, [n for n in names if n not in on]


def _version_name(version_id: str) -> Optional[str]:
    """The version's NAME (`versions.version`) - what the caller typed. Best-effort."""
    try:
        import sqlalchemy as sa
        from api.db.postgres import schema as s
        from core.db import get_engine
        with get_engine().connect() as cx:
            return cx.execute(sa.select(s.versions.c.version)
                              .where(s.versions.c.id == version_id)).scalar()
    except Exception:
        return None


def emit_run_summary(*, project_id: str, version_id: str, branch: str, commit: str,
                     scope: Optional[Dict[str, Any]], doc_type: str, cfg: Dict[str, Any],
                     no_llm: bool, data_dict_id: Optional[str], data_dict_path: Optional[str],
                     baseline: str, config_path: Optional[str], project_root: str,
                     warnings: Optional[List[str]] = None,
                     logger_name: str = "incremental") -> List[str]:
    """Log the run summary. Returns the problems that must stop the run before it parses.

    A configured dictionary that does not exist is one: the parser merges dictionaries at the
    END of Phase 1 and aborts there, so the run failed only after the whole parse.
    """
    from core.config import (core_config_warnings, layer_source_origin, load_llm_config,
                             missing_layer_inputs)

    def _exists(p):
        return bool(p) and os.path.isfile(p if os.path.isabs(p) else os.path.join(project_root, p))

    def _inputs(key):
        rows = []
        for layer in (cfg.get("layers") or {}):
            path, origin = layer_source_origin(cfg, layer, key)
            rows.append((layer, path, origin, _exists(path)))
        return rows

    views_on, views_off = config_views(cfg)

    if no_llm:
        llm = "OFF (--no-llm)"
    else:
        try:
            lc = load_llm_config(cfg)
            uses = [label for label, on in (("descriptions", lc.get("descriptions")),
                                            ("behaviour names", lc.get("behaviourNames")),
                                            ("flowchart labels", "flowcharts" in views_on)) if on]
            llm = (f"{lc.get('provider')} {lc.get('defaultModel')} - "
                   + (", ".join(uses) if uses else "nothing enabled uses it"))
        except Exception as exc:
            llm = f"config error: {exc}"

    proj = (data_dict_id, data_dict_path or "?", _exists(data_dict_path)) if data_dict_id else None
    warns = list(warnings or []) + core_config_warnings(cfg)
    if proj and not proj[2]:
        warns.append(f"--data-dict {data_dict_id}: no file at {proj[1]} - "
                     "the run continues WITHOUT the project-wide dictionary")
    errors = missing_layer_inputs(cfg, project_root, "dataDictionary")

    lines = build_run_summary({
        "projectId": project_id, "versionId": version_id, "versionName": _version_name(version_id),
        "branch": branch, "commit": commit, "scope": scope_label(scope), "docType": doc_type,
        "viewsOn": views_on, "viewsOff": views_off,
        "dataDictionaries": _inputs("dataDictionary"), "projectDataDict": proj,
        "macros": _inputs("macros"), "llm": llm, "baseline": baseline, "config": config_path,
        "warnings": warns, "errors": errors,
    })
    emit_report(lines, write_file=False, logger_name=logger_name)
    return errors
