# Post-Migration Consolidation Plan

> The ordered work that follows the completed PostgreSQL migration (doc 07, PG-7b).
> Covers: **process consolidation** (removing Python→Python subprocesses), **concurrency
> correctness**, **migration close-out** (items doc 07 specified but that were never landed), and
> the **performance** work that actually serves large codebases.
> Companion: [07-postgresql-migration-plan.md](07-postgresql-migration-plan.md) ·
> [08-storage-seam-version-identity.md](08-storage-seam-version-identity.md)

## 0. Where we are

The storage migration is **done**: model, view outputs, reuse index, run metadata, resolved config
and all app data live in Postgres; `JsonDatabase` is deleted; the commit dir holds only the git
checkout + manifest/report/parse snapshot. Validated end-to-end on the office box (two commits,
`reused=9 / regenerated=5`, compare shows the change, `verify_pg_readers` all green).

What remains falls into four groups, below. Work order is **B → D → C**, with **A deferred**
(§A): it is a code-quality improvement that serves neither of the two live goals — concurrent jobs
and large-codebase speed — so it is not worth its risk ahead of them. The one exception is **A0**
(capture subprocess `stderr`), which is an hour of work, carries no risk, and is worth doing now
regardless of whether the rest of A is ever done.

## 1. Principles that govern the ordering

1. **A process boundary must earn its keep.** Keep it for crash containment (libclang), for the
   long-running worker (API must never run a pipeline in-process), and for genuinely external
   tools (`mmdc`, Graphviz, git). Remove it where it only exists because a module was written as
   a CLI script.
2. **Persistent or cross-phase data → Postgres, keyed by `version_id`.** Process-local scratch →
   a **per-run** temp dir, never a shared one. Binary artifacts (PNG/DOCX) → files (D-14).
3. **Never delete a writer before its readers are repointed.** (The cutover proved this: deleting
   the commit-dir dual-write first would have silently broken flowchart reuse.)
4. **Every step ends green on both gates**: `pytest tests/unit tests/api` and
   `python tools/verify_incremental.py`.

---

## A. Process consolidation — **DEFERRED** (except A0)

Today one flowchart passes through **five nested process levels** (API → incremental → `run.py` →
phase script → flowchart engine → `mmdc`), each wrapped in a shell on Windows (`shell=True`).

**Why it is deferred.** Measured: ~8 Python→Python spawns per run at roughly 0.5–2s each ⇒
**~5–20s per run**, against runs measured in minutes. It does **not** help concurrency (the shared
data root does — see B) and it does **not** help large-codebase speed (parse + LLM dominate — see
D). The win is debuggability, error visibility and simplicity: real, but a code-quality
improvement, not a capability. Revisit after B, D and C — or sooner if measurement (D2) shows
process overhead actually matters.

**A0 is the exception and is scheduled now** (see §2): it delivers the *practical* benefit of this
whole group — error visibility — for about an hour and no risk, without touching the architecture.

| Step | What | Effort | Risk |
|---|---|---|---|
| **A0** ⭐ **now** | **Capture `stderr` from every spawn and log it on failure.** Independently removes the "exited with code 1, no reason" bug class that once hid a libclang failure for a whole debugging session. Valuable whether or not the rest of A ever happens. | ~1h | none |
| **A1** | **Flowchart engine in-process (D-11).** It already exposes `run()` and reads **zero** `sys.argv` — the blocker is package layout, not code. Fix the layout, call the function. | ~½ day | low |
| **A2** | **`run_views.py` / `model_deriver.py` / `docx_exporter.py` → callable.** Each already has `main()` and reads `sys.argv` exactly once. Change to `main(argv=None)` and call directly. | ~½ day | low |
| **A3** | **`orchestration.PhaseRunner` → in-process dispatch**, keeping the subprocess path behind a flag until each phase is proven. | ~½ day | low–med |
| **A4** | **`incremental/{generate,engine}.py` import `run.py`** instead of spawning it (removes 2 spawns/run). | ~½ day | low |
| **A5** | **`parser.py` de-tangle.** Lines 28–62 parse `sys.argv` **at module import** into module globals, so importing it *executes* argument parsing and a second in-process call leaks state. Move into a function; pass a config object. **Only required if parser runs in-process.** | 1–2 days | **high** |
| **A6** | **Decide + document the libclang boundary.** Doc 07 R5 keeps one process boundary around libclang so a segfault cannot kill the run. Recommendation: **keep it deliberately** (making A5 optional). | ~1h | — |

**Target topology (when this group is picked up):** `API → worker process → in-process phases →
external tools` (plus one optional libclang boundary) — two of our own boundaries instead of five.

**Dependencies:** A5 is a prerequisite for running `parser.py` in-process, and *only* for that. If
A6 keeps the libclang boundary, A5 can be dropped — ~80% of the benefit lands after A1–A4.
Nothing in B, C or D depends on A, so deferring it blocks nothing.

---

## B. Concurrency correctness ⚠ live bug

**`JOB_MAX_CONCURRENCY` defaults to 2** ([settings.py:47](api/services/settings.py#L47)) and jobs
are rejected only **per project**, but every run writes the **same shared** `<repo>/model` and
`<repo>/output`, and a full generation calls `_rmtree_force(output_dir)`
([generate.py:209](engine/incremental/generate.py#L209)) — so one job can delete another's output
mid-run. This is doc 07 defect 26; its prescribed interim (`JOB_MAX_CONCURRENCY=1`) was never
applied.

| Step | What | Effort | Risk |
|---|---|---|---|
| **B0** | **Set `JOB_MAX_CONCURRENCY=1` on the deployment now.** One env var; removes the corruption risk until B1 lands. | minutes | none |
| **B1** | **Per-job data root.** `pipeline_runner` sets `ANALYZER_DATA_ROOT` to a per-job dir (the mechanism exists in `core/paths.py`, is subprocess-inherited, and is already exercised by `verify_incremental`). Removes the shared `model/`+`output/` entirely. | ~½ day | low–med |
| **B2** | **Per-run temp path for the clang-args response file** (currently in the shared `model/` dir — doc 07 defect 31). | ~1h | low |
| **B3** | **Atomic writes (temp+rename) for `.mmdc_cache` / `.flowchart_cache`** — two jobs may legitimately write the same content-addressed key. | ~2h | low |
| **B4** | **Raise `JOB_MAX_CONCURRENCY` deliberately** and add a concurrent-jobs test (two projects at once, assert both outputs intact). | ~½ day | med |

**Note:** B1 is required whether or not A is ever done — and if A is picked up later, per-job
isolation matters *more*, not less, because in-process phases share one working directory.

---

## C. Migration close-out — specified in doc 07, never landed

Verified still outstanding:

| Step | What | Why it matters | Effort |
|---|---|---|---|
| **C0** | **Finish the view-output reads (PG-5b).** `version_output_files` holds every view file, and the `OutputReader` seam exists — but **only `compare_engine`'s summary path uses it**. `doc_render` still reads `group_dir/interface_tables.json`, `group_dir/flowcharts/*.json` and `group_dir/behaviour_diagrams/_behaviour_pngs.json` **from disk**, and `compare_render._version_render` still renders from `snap_dir`. So the document render — the main product surface — is still disk-backed even though the data is in Postgres. Wiring only; no new infrastructure. | the rendered document stops depending on local disk | S–M |
| **C1** | **`manifest.json` → DB + `pipeline_status` lifecycle (D-17).** Every manifest field already has a column (`decision`, `baseline_version_id`, `regenerated`, `reused`). **`versions.pipeline_status` exists but is NEVER written** — landing this gives the real `parsing → deriving → viewing → exporting → complete` progress the UI could show instead of log-scraping. | removes engine→API file; enables progress | S–M |
| **C2** | **`<commit>/parse/` snapshot → DB.** Needs storage for `entity_files`, `func_keys`, `override_pairs` (`tu_includes` is already in the schema) **and** a way to hold the *blank skeleton* distinctly from the enriched model (the snapshot is taken post-Phase-1; the DB currently holds the post-Phase-2 model). Natural byproduct of persisting at each phase boundary (C6). | narrowed parse works **across machines**, survives a workspace wipe | M |
| **C3** | **Delete `clang_include_paths.json`** (PG-5 says deleted outright; still written/read by `parser.py`, `run.py`, `views/flowcharts.py`). It holds machine-specific absolute paths — derive it, never store it. | removes machine-specific state | S |
| **C4** | **Remove `knowledge_base.json` (D-12 "no knowledge base").** Still referenced in `core/model_io.py`, `flowchart/pkb/builder.py`, `model_deriver.py`. Replace with the context service. | D-12 | M |
| **C5** | **D-18 `is_visible` carry-forward + test.** The column exists and `ModelReader` maps `isVisible → hidden`, but carry-forward for reused entities is unproven — hiding a function in v1 must keep it hidden in v2. | user intent survives a re-run | S |
| **C6** | **Phase atomicity (D-17).** One transaction per phase, idempotent upserts. Test: kill Phase 2 mid-run → state equals post-Phase-1 exactly; `--from-phase 2` completes cleanly. | crash safety | M |
| **C7** | **`fetch_context` context service (D-12)** — replaces whole-project KB objects with a per-target working set. | pairs with C4 | M |
| **C8** | **Prune `_wizard/` clones.** The wizard's clone cache is never cleaned; grows unbounded (GBs on large repos). Add a TTL/size cap. | disk hygiene | S |
| **C9** | **UTF-8 end-to-end test** (doc 07 G5) — round-trip a Korean comment + Unicode description. This codebase has documented cp1252 failures. | correctness | S |
| **C10** | **Retention / delete-version action** (doc 07 G6) — `ON DELETE CASCADE` exists; the user-facing action does not. | ops | S |
| **C11** ⭐ | **`ModelStore` — phases persist/read the model at each boundary (PG-5 core).** This is the answer to *"why write everything to `model/*.json` and only then to the DB?"*. Today the phases hand the model to each other through files and the store writes to Postgres **once, at the end**; the DB is the destination, not the channel. Target: each phase reads its input from Postgres by `version_id` and writes its output back, so there is one copy, no shared scratch, and `--from-phase N` resumes from real state. **C2 (skeleton) and C6 (atomicity) fall out of this naturally**, and it removes the last reason the shared `model/` dir exists. Doc 07 calls this the largest and riskiest step; land it "persist-after-phase" first, then "read-from-DB". | one source of truth; kills files-as-channel | **L** |

---

## D. Performance — what actually helps large codebases

| Step | What | Effort |
|---|---|---|
| **D1** | **Validate narrowed parse** — re-parse only affected TUs instead of the whole codebase. **This is the real large-codebase lever** (minutes saved, vs ~10s of process overhead in A). It has **zero automated coverage**, is off by default, is not UI-reachable, and its fingerprint gate was re-sourced to the DB during the cutover. Natural test: same commit narrowed vs full ⇒ assert identical model — exactly what `--verify-parse` does at runtime. | M |
| **D2** | **Measure where run time actually goes** (parse vs LLM vs render) before optimising further. Every optimisation after this should cite a measurement. | S |

---

## 2. Recommended order

```
B0   (minutes, do today — removes a live corruption risk)
 └─ A0                                   capture stderr (1h; the useful part of A)
     └─ B1 → B2 → B3 → B4                concurrency correctness  → concurrent jobs
          └─ D1 → D2                     narrowed parse + measurement → large-codebase speed
               └─ C0 → C1 → C8 → C3 → C5 → C9    small close-outs
                    └─ C11 ⭐ → C2 → C6 → C4 → C7 → C10   larger close-outs
                         └─ A1 → A2 → A3 → A4 → A6 → [A5]   process consolidation (deferred)
```

**Why this order.** B0 is free and removes a live risk. A0 buys the practical benefit of group A
in an hour and makes everything after it debuggable. **B** then serves the first live goal —
concurrent jobs — and B1 must precede any concurrency increase. **D1** serves the second — real
large-codebase speed — and must come *before* C2, which changes how narrowed-parse data is stored:
validate the feature before moving its ground. **C0** is first inside C because the seams already
exist (it is wiring, and it takes the *rendered document* off local disk). C1/C8/C3/C5/C9 are small
and independent. **C11 leads the larger group** because C2 and C6 fall out of it — doing them
first would mean building skeleton storage and per-phase transactions twice. **A** last, as a
quality improvement once the capability work is done.

## 3. Gates

Every step: `pytest tests/unit tests/api` **and** `python tools/verify_incremental.py` green.
Steps touching storage also: `python tools/verify_pg_readers.py` green on a fresh run.
Steps touching the API (sections, re-export, render) need a **real two-commit run** — the gate
does not exercise those paths.

## 4. Open decisions

1. **B4 — target concurrency.** How many simultaneous jobs must the office deployment support?
   Needed before B4; everything earlier in B is required regardless of the answer.
2. **C2 — skeleton storage.** Persist the model twice (post-Phase-1 + final), or derive the
   skeleton by stripping LLM fields? Decide when C6 lands.
3. *(deferred with A)* **A6 — keep the libclang process boundary?** Recommendation: **yes**,
   which makes A5 — the only high-risk step in this plan — unnecessary.

## 5. Sequencing history

An earlier revision of this plan scheduled **A first**. That was reversed: A is a code-quality
improvement whose measured benefit is ~5–20s per multi-minute run, it does not address either live
goal, and it carries the only high-risk step in the plan (A5, `parser.py`). The order is now
**B → D → C**, with A deferred and **A0 pulled out** because error visibility — the one benefit of
A with a track record of costing real debugging time — is available for an hour and no risk.

Recorded so the reasoning is not re-litigated: **A is deferred, not rejected.** Pick it up after C,
or sooner if D2's measurement shows process overhead actually matters. **B0 applies today either
way** — the concurrency bug is live regardless of what is worked on next.
