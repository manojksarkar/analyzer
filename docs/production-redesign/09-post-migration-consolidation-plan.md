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
| **A0** ✅ | **Done.** New `core/subprocess_util.py`: stderr is **streamed through** (the API tails it for job progress, so buffering would freeze the UI's progress bar) while a bounded 50-line tail is retained and logged on failure. Applied to `PhaseRunner`, the flowchart-engine spawn (the exact site that hid a `LibclangError`), and both renderers in `utils.py` — which were capturing stderr and **discarding** it. On the API side the non-zero-exit path already did this; the real gaps were the **timeout path**, which dropped the tail entirely, and `_mark_failed`, which wrote only to the DB with no module logger. | ~1h | none |
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
| **B0** ✅ | **Done** — the `job_max_concurrency` **default is now 1** ([settings.py](../../api/services/settings.py)), not just an env var on one deployment: the old default of 2 corrupted output on any machine that had not read this doc. ⚠ **Multi-node caveat:** the semaphore is per API **process**, so N replicas give N × the limit. A global cap needs a DB-backed lease (**B0c**, unfiled). | minutes | none |
| **B1 (output)** ✅ | **Done** — a run renders straight into `versions/<ver…>/output` via `run.py --output-root`, so `<repo>/output` no longer exists and the capture copy is gone. Deliberately **not** done with `ANALYZER_DATA_ROOT`: that also moves `logs_dir` and `cache_dir`, giving every run a private `.flowchart_cache` — a 0% hit rate that would silently undo M-A/M-B. A **flag, not an env var**: the run's own command line then records where its output went. | ~½ day | low–med |
| **B1 (model)** | The `model/` half — **superseded by C11**: the model moves to Postgres rather than to a private folder. `<repo>/model` is the last shared directory, and the only remaining reason concurrency must stay at 1. | — | — |
| **B2** | **Per-run temp path for the clang-args response file** (currently in the shared `model/` dir — doc 07 defect 31). | ~1h | low |
| **B3** | **Atomic writes (temp+rename) for `.mmdc_cache` / `.flowchart_cache`** — two jobs may legitimately write the same content-addressed key. | ~2h | low |
| **B4** | **Raise `JOB_MAX_CONCURRENCY` to the target (5–6)** and add a concurrent-jobs test (several projects at once, assert every output intact and every version row correct). | ~½ day | med |
| **B5a** ✅ | **Done — batch the reuse-index reads.** `PgReuseIndex.get_many` / `put_many` (one `WHERE fingerprint = ANY(…)`, chunked), threaded through `ArtifactStore` / `FileStore` / `PgStore` / `StoreReuseIndex` and both hot loops. `carry_forward_from_index` stays pure — the prefetch happens at the call site. **Prerequisite for B5b**, see the sequencing note below. | ~3h | low |
| **B5b** | **Size the DB connection budget.** *(solution designed — see below; safe now that B5a has landed)* | ~1–2h | **med — will bite at 5–6** |
| **B6** | **LLM behaviour at N concurrent jobs.** The client rate-limits *per process*; six jobs multiply the request rate against the provider. Confirm provider limits, and decide whether throttling belongs per-process or shared. | ~½ day | med |

**Two things that are already safe** (verified): the `reuse_index` upsert uses `ON CONFLICT DO
NOTHING`, so concurrent writers cannot collide; and jobs are rejected **per project**, so
concurrency is across *different* projects — keep that guard, since two jobs on one project would
collide on the shared per-commit checkout dir.

**Capacity note (not code):** 5–6 concurrent runs means 5–6 simultaneous libclang parses. Size CPU
and RAM for the peak, not the average — measure with D2 before committing to the number.

### B5 — the connection-budget fix (designed, ready to implement)

**Root cause is a profile mismatch**: one `get_engine()` ([core/db.py:120](engine/core/db.py#L120))
serves two opposite workloads, and both take SQLAlchemy's default pool (5 + 10 overflow = 15).

| | API server | Engine subprocess |
|---|---|---|
| Threading | concurrent (FastAPI threadpool) | **single-threaded** |
| DB calls | many, short | **~10 across the whole run** |
| Idle time | low | **minutes** between calls (parse/LLM) |

So an engine subprocess pins up to 15 connections while spending ten minutes parsing. × 6 jobs ⇒
exhaustion.

**Fix — two profiles:**

1. **Engine subprocesses → `NullPool`.** Single-threaded with a handful of statements: connect per
   operation, hold **zero** idle connections during the long phases. ~10 extra connects per run is
   irrelevant against a multi-minute run. (It also makes `pool_pre_ping` moot there — every
   connection is fresh, which is what that flag was working around.)
2. **API server → a sized pool**: `pool_size=5, max_overflow=5`.

In `core/db.py` where the kwargs are built:

```python
# Engine subprocesses are single-threaded and mostly idle (parse/LLM); a pool would pin idle
# connections for minutes. NullPool holds none. The API is concurrent and pools.
if os.environ.get("ANALYZER_DB_POOL", "").lower() == "none":
    kwargs["poolclass"] = NullPool
else:
    kwargs["pool_size"] = int(os.environ.get("DB_POOL_SIZE", 5))
    kwargs["max_overflow"] = int(os.environ.get("DB_MAX_OVERFLOW", 5))
```

Set `ANALYZER_DB_POOL=none` in `pipeline_runner._engine_db_env()` — the same place that already
injects `DATABASE_URL` into the subprocess. One env var, one place.

**Budget after the fix:** API `5+5=10` + (6 jobs × ~1–2 transient) ≈ **~22 of 100**.
**Formula:** `(API pool + overflow) + (max_jobs × per-job peak) ≤ max_connections × 0.8`.

**Verify** during concurrent runs: `SELECT count(*) FROM pg_stat_activity WHERE datname='analyzer';`
should stay in the low tens. Adding `application_name` to `connect_args` makes that query show
which process holds what.

**Not needed:** PgBouncer — that is for tens of replicas / hundreds of connections, not 6 jobs.

**Note:** B1 is required whether or not A is ever done — and if A is picked up later, per-job
isolation matters *more*, not less, because in-process phases share one working directory.

---

## C. Migration close-out — specified in doc 07, never landed

Verified still outstanding:

| Step | What | Why it matters | Effort |
|---|---|---|---|
| **C0** | **Finish the view-output reads (PG-5b).** `version_output_files` holds every view file, and the `OutputReader` seam exists — but **only `compare_engine`'s summary path uses it**. `doc_render` still reads `group_dir/interface_tables.json`, `group_dir/flowcharts/*.json` and `group_dir/behaviour_diagrams/_behaviour_pngs.json` **from disk**, and `compare_render._version_render` still renders from `snap_dir`. So the document render — the main product surface — is still disk-backed even though the data is in Postgres. Wiring only; no new infrastructure. | the rendered document stops depending on local disk | S–M |
| **C1** ✅ | **Done.** `persist_run_outcome` / `load_run_outcome` put decision / baseline / regenerated / reused on the `versions` row (mirroring `write_run_metadata`); `PgStore.write_manifest` writes both and the API reads **DB-first with a file fallback** — additive, because the cutover's own rule is *never delete a writer before its readers are repointed*. `PhaseRunner` now writes `versions.pipeline_status` (`parsing → deriving → viewing → exporting`) at each phase boundary, keyed by `phase.script` rather than the display name. Best-effort: a CLI run has no version id, and the DB-less gate has no database. Deleting the file is a follow-up, once the API has run DB-first in the office. | removes engine→API file; enables progress | S–M |
| **C2** | **`<commit>/parse/` snapshot → DB.** Needs storage for `entity_files`, `func_keys`, `override_pairs` (`tu_includes` is already in the schema) **and** a way to hold the *blank skeleton* distinctly from the enriched model (the snapshot is taken post-Phase-1; the DB currently holds the post-Phase-2 model). Natural byproduct of persisting at each phase boundary (C6). | narrowed parse works **across machines**, survives a workspace wipe | M |
| **C3** | **Delete `clang_include_paths.json`** (PG-5 says deleted outright; still written/read by `parser.py`, `run.py`, `views/flowcharts.py`). It holds machine-specific absolute paths — derive it, never store it. | removes machine-specific state | S |
| **C4** | **Remove `knowledge_base.json` (D-12 "no knowledge base").** Still referenced in `core/model_io.py`, `flowchart/pkb/builder.py`, `model_deriver.py`. Replace with the context service. | D-12 | M |
| **C5** | **D-18 `is_visible` carry-forward + test.** The column exists and `ModelReader` maps `isVisible → hidden`, but carry-forward for reused entities is unproven — hiding a function in v1 must keep it hidden in v2. | user intent survives a re-run | S |
| **C6** | **Phase atomicity (D-17).** One transaction per phase, idempotent upserts. Test: kill Phase 2 mid-run → state equals post-Phase-1 exactly; `--from-phase 2` completes cleanly. | crash safety | M |
| **C7** | **`fetch_context` context service (D-12)** — replaces whole-project KB objects with a per-target working set. | pairs with C4 | M |
| **C8** | **Prune `_wizard/` clones.** The wizard's clone cache is never cleaned; grows unbounded (GBs on large repos). Add a TTL/size cap. | disk hygiene | S |
| **C9** | **UTF-8 end-to-end test** (doc 07 G5) — round-trip a Korean comment + Unicode description. This codebase has documented cp1252 failures. | correctness | S |
| **C10** | **Retention / delete-version action** (doc 07 G6) — `ON DELETE CASCADE` exists; the user-facing action does not. | ops | S |
| **C12** | **Consolidate the disk caches** (`.flowchart_cache`, `.mmdc_cache`, `.dot_cache`). On a multi-node container deployment these are ephemeral and per-node, so they largely stop paying for themselves. More importantly the LLM cache and the DB **reuse index already answer the same question with near-identical keys** — this removes a duplicate mechanism, not just a directory. PNG caches go to shared artifact storage (same decision as serving DOCX/PNG across nodes); `pkb_*.json` disappears with C11. **Design: [04 §13](04-incremental-changes-implementation.md#13-caches-in-the-database-post-migration-doc-09-c12).** Must follow C11 — the keys derive from model content. | one reuse mechanism; works across nodes | M |
| **C11** ⭐ | **`ModelStore` — phases persist/read the model at each boundary (PG-5 core).** This is the answer to *"why write everything to `model/*.json` and only then to the DB?"*. Today the phases hand the model to each other through files and the store writes to Postgres **once, at the end**; the DB is the destination, not the channel. Target: each phase reads its input from Postgres by `version_id` and writes its output back, so there is one copy, no shared scratch, and `--from-phase N` resumes from real state. **C2 (skeleton) and C6 (atomicity) fall out of this naturally**, and it removes the last reason the shared `model/` dir exists. Doc 07 calls this the largest and riskiest step; land it "persist-after-phase" first, then "read-from-DB". | one source of truth; kills files-as-channel | **L** |

---

## D. Performance — what actually helps large codebases

| Step | What | Effort |
|---|---|---|
| **D1** | **Validate narrowed parse** — re-parse only affected TUs instead of the whole codebase. **This is the real large-codebase lever** (minutes saved, vs ~10s of process overhead in A). It has **zero automated coverage**, is off by default, is not UI-reachable, and its fingerprint gate was re-sourced to the DB during the cutover. Natural test: same commit narrowed vs full ⇒ assert identical model — exactly what `--verify-parse` does at runtime. | M |
| **D2a** ✅ | **Instrumentation done.** `core/run_metrics.py` appends one JSON line per phase to `logs/metrics_<date>.jsonl` with elapsed time and **peak RSS of the process tree** (sampled via psutil; the tree, because on Windows the child is a shell and a phase spawns the flowchart engine and Chromium beneath it). LLM **call counts already existed** in `llm_core/tokens.py` and are now written to the same file. JSON Lines so concurrent jobs append without coordination. Records are tagged with the job/version id. | S |
| **D2b** | **Measure on the office large repo** — peak RSS per job, LLM calls per run (full vs incremental), real phase split. This, plus the provider's actual limit (B6), is what **sets the concurrency target**; it cannot be chosen without them. Sample-project numbers (~72 MB peak, 125 functions) do not extrapolate. | S |
| **M1** | **Bound the flowchart TU cache.** `TranslationUnitParser._tu_cache` is unbounded, holds **full-body** ASTs (`get_tu_full` deliberately skips `PARSE_SKIP_FUNCTION_BODIES`) and is never cleared, so peak memory grows with **file count, not change size** — even on an incremental run. It is per job, so it multiplies by concurrency, and it is the first thing that will exhaust a container on a large codebase. LRU with a size cap, or clear per file-group once its functions are processed. | S–M |
| **M2** | Audit `parser.py`'s `oc._tu = c._tu  # keep the TU alive` (virtual-dispatch pass) for the same retention shape. | S |

---

## 2. Recommended order

```
B0   ✅ default is now 1 (settings.py) — removed the live corruption risk
 └─ A0  ✅  stderr captured at every spawn + D2a instrumentation (phase timings, peak RSS)
     └─ B1(output) ✅  runs render into versions/<ver…>/output; <repo>/output is GONE
         └─ B5a ✅ → B1(model) → B2 → B3 → B5b → B6 → B4   concurrency → 5–6 jobs
              └─ D2b → D1                  measure FIRST, then narrowed parse
                   └─ C1 ✅ → C0 → C8 → C3 → C5 → C9    small close-outs
                        └─ C11 ⭐ → C2 → C6 → C4 → C7 → C10 → C12   larger close-outs
                             └─ A1 → A2 → A3 → A4 → A6 → [A5]   process consolidation (deferred)
```

**Changes to the original order, with reasons:**

- **B5 split into B5a → B5b.** B5a (batch the reuse-index reads) is a **prerequisite**, not a nicety:
  `PgReuseIndex.get` opened a connection per entity, and the end-of-run seeding loop ran it for *every*
  fingerprinted entity. Applying B5b's `NullPool` first would have turned ~20k pooled lookups into ~20k
  real connects — **minutes added to every large run**, on exactly the codebases D exists to speed up.
  Measured after the fix: 50 acquisitions → 1.
- **D2 promoted above B4 and split (D2a instrument / D2b measure).** The concurrency target cannot be
  chosen without peak-RSS and LLM-call numbers; D2a is done, D2b needs the office box.
- **B1 split.** The `output/` half is done (runs render straight into the version dir — no shared dir,
  and the copy step is gone). The `model/` half is superseded by **C11**: the model goes to Postgres
  rather than to a private folder.
- **B4 is per-job-class, not one global number.** Full LLM-on generations, incremental runs, and
  LLM-off runs have different binding constraints; a single limit sizes for the worst and wastes the rest.
- **New: M1/M2 (bound the flowchart TU cache).** `TranslationUnitParser._tu_cache` is unbounded, holds
  **full-body** ASTs, and is never cleared — peak memory grows with file count, not change size. It is
  per job, so it multiplies by concurrency, and it is the first thing that will exhaust a container on a
  large codebase. Not in the original plan; belongs beside D.
- **New: C12** (above) — consolidate the disk caches.
- **B6 is a gate, not a tuning task.** The LLM client throttles **per process**, so N jobs multiply the
  request rate. If the provider limit is global, the LLM-on answer is 1 and no amount of B1–B5 changes it.

**Why this order.** B0 is free and removes a live risk. A0 buys the practical benefit of group A
in an hour and makes everything after it debuggable. **B** then serves the first live goal —
concurrent jobs — and B1/B2/B3/B5/B6 must all precede B4, the actual increase to 5–6. **D1**
serves the second — real
large-codebase speed — and must come *before* C2, which changes how narrowed-parse data is stored:
validate the feature before moving its ground. **C0** is first inside C because the seams already
exist (it is wiring, and it takes the *rendered document* off local disk). C1/C8/C3/C5/C9 are small
and independent. **C11 leads the larger group** because C2 and C6 fall out of it — doing them
first would mean building skeleton storage and per-phase transactions twice. **A** last, as a
quality improvement once the capability work is done.

## 3. Gates

Every step: `pytest tests/unit tests/api` **and** `python tools/verify_incremental.py` green.
Steps touching storage also: `python tools/verify_pg_readers.py` green on a fresh run.
**C11 specifically:** `python tools/verify_model_parity.py <version_id>` — compares the version's
model in Postgres against the same model on disk. This is the gate that decides whether phases may
*read* from the DB (C11b); it must be clean after every phase before that lands. Expected, non-failing
differences: DB-only fields (`isVisible`), and edge-list ORDER (rebuilt from rows — compared as sets,
the same bar `parse_merge.diff_models` settled on). What it hunts is fields the payload allow-lists
silently drop.
Steps touching the API (sections, re-export, render) need a **real two-commit run** — the gate
does not exercise those paths.

## 4. Open decisions

1. ~~**B4 — target concurrency.**~~ **DECIDED: 5–6 simultaneous jobs.** This raises B's priority —
   at 5–6 the shared-scratch corruption is routine rather than theoretical — and adds **B5**
   (connection budget) and **B6** (LLM rate limits), neither of which mattered at 1–2.
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
