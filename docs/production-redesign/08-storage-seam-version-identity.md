# 08 — Storage seam + version identity (PG-3 → PG-5 runbook)

> Updated: 2026-08-05 · Branch: `db-with-increment-changes`
>
> **What this is.** The concrete, correct-architecture approach for the PG-3 → PG-5 cluster of
> [07-postgresql-migration-plan.md](07-postgresql-migration-plan.md): make the engine speak the
> real `ver…` id and store artifacts in Postgres, by **honouring the storage seam
> [engine/incremental/stores.py](../../engine/incremental/stores.py) already declares.** Replaces
> the discarded "identity-only band-aid" for PG-3.
>
> **Already landed:** the real `ver…` id is reserved at job start and the completion row is created
> under it ([api/routes/jobs.py](../../api/routes/jobs.py), [pipeline_runner.py `_make_version`](../../api/services/pipeline_runner.py)).

## 1. The defect — one string, three jobs

`commit[:16]` is overloaded as **(a)** the git checkout dir, **(b)** the artifact dir, and **(c)**
the version identity. Every symptom traces to this:

- **Correctness.** Two versions of the *same* commit — a different version name, or a re-run with a
  new data dictionary/config — collide on one dir/id; the second silently overwrites the first.
- **Integration.** The DB, UI, compare, and documents all key on the real `ver…` id. The engine is
  the only part on `commit[:16]`, forcing a constant translation — the "wall".
- **Storage.** The Postgres artifact tables key on `versions.id` (some FK-strict, e.g. `tu_includes`).
  Engine output keyed by `commit[:16]` cannot land there.

## 2. The target — three handles

| Concern | Handle | Lives | Lifetime |
|---|---|---|---|
| Source checkout | **commit** | `workspaces/<pid>/checkouts/<commit>/` | transient scratch (GC-able) |
| Version identity | **`ver…`** (reserved at job start) | `versions` row | permanent |
| Artifacts (model, hashes, edges, reuse, output) | keyed by **`ver…`** | **Postgres** (`FileStore` for DB-less dev/test) | with the version (`ON DELETE CASCADE`) |

The commit does exactly one thing — locate source for libclang. Everything durable is keyed by the
real version id.

## 3. Honour the seam that already exists

[stores.py](../../engine/incremental/stores.py)'s own docstring: *"the method signatures ARE the
interface … Postgres is a drop-in implementation of the same methods."* The bug is a single line:

```python
version_dir(version_id) → commit_dir(version_id[:16])   # welds identity to the checkout folder
```

So this is **not** "invent a seam" — it is *break that weld and add the Postgres implementation the
seam was designed for.*

**Interface surface** — every storage call the engine makes (from
[engine.py](../../engine/incremental/engine.py) + [generate.py](../../engine/incremental/generate.py),
the only two callers):

| Group | Methods | Purpose |
|---|---|---|
| version dir | `create_dir(v)`, `version_dir(v)` | artifact location for `v` |
| hashes | `HashStore.read(v)` / `write(v, …)` | classify input |
| edges | `EdgeStore.read(v)` / `write(v, …)` | type/macro usage |
| model reads | functions/globals from `version_dir(v)/model` | baseline + cross-version reuse source |
| reuse index | `ReuseIndex.get(fp)` / `put(fp, v, key)` / `save()` | `{fingerprint → {versionId, entityKey}}` |
| capture | `capture_artifacts(v, model_dir, output_dir)` | copy model/output in, collect docs |
| config/manifest | `write_config(v, …)`, `write_manifest(v, …)` | |
| checkout *(separate)* | `Workspace.commit_dir(commit)` | **commit-keyed — stays** |

## 4. Two implementations of that interface

- **`FileStore`** (dev / test / standalone, no DB) — the refactored `stores.py`, artifacts under
  `versions/<ver…>/`, a tree **separate** from the checkout. The permanent test seam.
- **`PgStore`** (production) — mostly built already in
  [model_store.py](../../engine/incremental/model_store.py) (`persist_model`, `load_model`,
  `load_hashes`, `persist_edges`, `load_edges`, …) plus `PgReuseIndex` in
  [pg_stores.py](../../engine/incremental/pg_stores.py). Structured model/hashes/edges/reuse → DB
  rows keyed by `ver…`.

**Hybrid boundary (deliberate).** Structured data → DB. Two things stay on disk: the **git checkout**
(libclang needs real files) and the **rendered output** (DOCX/PNG served by compare/doc_render). Moving
rendered output to content-blobs is a later follow-up, not part of this cluster.

## 5. Increments — each behind a test

**1 — Lock current behaviour with a DB-less two-version e2e (the gate). ✅ built.**
`tools/verify_incremental.py`: a throwaway C++ git fixture (two functions), baseline → change
`add` → second run, all DB-less/LLM-off. It asserts the version-identity-critical behaviour —
`decision == "incremental"` (baseline identity resolved via `list_versions` + selection) and
`reused >= 1` (the baseline model was **read back** and carried forward) — the exact store paths
the wiring changes. `run_incremental`'s dir/identity path had **no** unit coverage; this is the
safety net every later step runs behind. *(Regeneration count is LLM-gated, so `--no-llm` leaves
it 0 — not what this gate guards.)*

Enabler discovered building it: `core.paths` conflated code and data roots, and the pipeline
runs as a **subprocess** that re-detects the root — so a run couldn't be isolated and would
overwrite the repo's own `model/output`. Fixed with an **`ANALYZER_DATA_ROOT`** override (env, so
the subprocess inherits it) that relocates `model/output/logs/cache/api-db-data` independently of
the code root; unset (production) it equals the project root, so nothing changes. This is itself a
down-payment on the decoupling this milestone is about.

**2 — Break the weld; thread the real id (`FileStore`).**
- `Workspace.version_dir(ver…) → versions/<ver…>/`; keep `commit_dir(commit)` for the checkout.
- Engine takes `(commit, version_id)`: `commit` → checkout, `version_id` → every artifact call.
  Baseline reads use `chosenBaseVersionId`; `select_baseline` already returns `chosenBaseCommit` for
  any checkout need.
- `project_db.list_versions` → real `ver…` ids (keep `commit` for reference). *(Flips the two
  `test_pg_stores` assertions that pin `commit[:16]`.)*
- Gate: the step-1 e2e still passes, now under real `ver…` ids.

**3 — Resolve readers by version id.** `compare_engine`, `compare_render`, `doc_render`,
`documents.py` resolve a version's artifacts through the store (by `ver…`), not
`workspaces/<pid>/<commit[:16]>`. The commit-sha-prefix fallbacks retire.

**4 — `PgStore`.** Wrap `model_store.py` + `PgReuseIndex` behind the store interface; the engine
selects `PgStore` when `DATABASE_URL` is set, else `FileStore`. Structured artifacts now live in
Postgres keyed by `ver…`. Gate: run the step-1 e2e against remote Postgres (the pending "Phase 5").

**5 — Cutover.** Drop the commit-dir artifact layout; `FileStore` becomes dev/test only, Postgres the
prod source of truth. Folds into 07's PG-7.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Version-identity ripple (07 R6) — routes, runner, CLI, paths, compare | one concern per increment, behind the step-1 e2e gate |
| `run_incremental` dir/identity logic uncovered by current tests | step 1 builds that coverage **before** any surgery |
| Rendered-output paths still commit-shaped | step 3 routes them through the store; blob move deferred |
| PG-5 breadth (four phases + flowchart) | `FileStore`/`PgStore` behind one interface; two-step land (persist → read); L2 prompt parity to merge |
