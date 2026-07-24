# API Plan — Real Pipeline-Backed Server

> Forward work + design record for `api/`. Goal (**largely met**): `api/` implements the full 70-route
> surface, backed by both the in-memory and JSON databases, where analysis/document operations **invoke the
> real analyzer pipeline (`run.py`)** and read real artifacts (`model/`, `output/`, `versions/`) instead of a
> simulation. Companion: [README.md](README.md) (how to run + route reference), [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

## Status

| Milestone | State |
|---|---|
| **M0 — static surface** (schemas.py, `routes/users.py` + `repositories.py`, `git_cli`/`repo_git`, domain fields, token-stripped `build_config`, real commit backfill, 70 routes) | ✅ Done — see `api/README.md` route table + architecture tree |
| **M1 — real analysis worker** (`pipeline_runner.py`: clone → per-project config → `run.py` subprocess → real SSE → Version + Documents) | ✅ Done |
| **M2 — real functions / render / assets / download / export-all** (live `output/`, fixtures now only a no-run fallback) | ✅ Done |
| **M3 — real compare** (incremental engine over two real version snapshots) | ✅ Done |
| **M4 — persistence, config, docs, tests** | ◐ Partial — remaining below |

## Remaining (M4)

- [ ] **Tests** — `TestClient` smoke tests; mock `git_cli`/subprocess for units; one e2e against a tiny fixture repo (`samplecpp`).
- [ ] **Docs refresh** — `api/PROJECT_CONTEXT.md` still reads `Updated: 2026-06-27` and predates the real-pipeline swap; bring it to current state (real worker, 70 routes, simulation→real).
- [ ] **Config/paths hardening** — confirm central settings cover per-project workspace roots so concurrent projects never collide on shared repo-root `model/`/`output/` (see design decision 1).
- [ ] **Verify `.gitignore`** covers `workspaces/`, `api/db/data/`, generated `output/`.

---

## Reference — the real commands & artifacts the API drives

The analyzer is a subprocess pipeline driven by `run.py` (repo root); the API is a thin orchestrator over it.

```bash
python run.py [flags] <project_path>
```

| API concept | run.py flag |
|---|---|
| `StartJobRequest.layer_filter` | `--selected-layer <L>` (or `--selected-group`) |
| `StartJobRequest.pause_after_phase1` | phases 1–2 only, then hold (`--from-phase` boundary) |
| per-project config (layers/clang/llm) | `--config <path>` (also honours `ANALYZER_CONFIG` env) |
| project display name | `--project-name <name>` |
| re-export only (reexport endpoint) | `--use-model --from-phase 4` |
| clean rebuild | `--clean` |
| uploaded data dictionary / macros | `--data-dictionary <csv>` / `--macros <csv>` |

**Incremental / versions:** full version-producing generation = `src/incremental/generate.py` (writes
`versions/<id>/` + `cache/index.json`); incremental = `src/incremental/engine.py::generate_incremental`
(baseline → classify → impact BFS → selective LLM regen → reuse report). Version-scoped reads use
`?projectId=&versionId=` (root `PROJECT_CONTEXT.md` §23).

**Artifacts the API reads back:**

```
model/{metadata,functions,globalVariables,units,components,dataDictionary,knowledge_base,summaries}.json
output/<group>/interface_tables.json
output/<group>/{unit_diagrams,behaviour_diagrams}/*.{mmd,png}
output/<group>/flowcharts/*.{json,png}
output/<group>/software_detailed_design_<group>.docx
versions/<id>/...            (per-version snapshot)   versions/<id>/report.txt (reuse accounting)
logs/run_<YYYYMMDD>.log      (live progress source for SSE)
```

**Git:** `api/services/git_cli.py` (self-contained, `shell=False`, credential scrubbing,
`GIT_TERMINAL_PROMPT=0`) checks out `commit_sha` into `workspaces/<project_id>/<sha16>/` (gitignored); that
checkout is the `<project_path>` passed to `run.py`.

## Design decisions (owner-confirmed)

1. **Per-project workspace isolation.** Each project runs in `workspaces/<project_id>/` with its own
   `model/`/`output/`/`versions/`, so concurrent jobs and demo data don't clobber the shared repo-root dirs.
2. **Execution host is co-located.** `LLVM/libclang`, `git`, and the analyzer Python env live on the API host,
   so `pipeline_runner` shells out to `run.py` in-process on a daemon thread (`POST /jobs` returns 202). A real
   broker (Celery/RQ) is out of scope for the POC but the `pipeline_runner` boundary keeps it swappable.
3. **Fixtures are a fallback, not the source.** `doc_render`/assets read live output first; the committed
   `fixtures/` + synthesized payload remain only as the graceful "no run yet" fallback.
4. **Both DBs stay first-class.** Nothing outside `db/` + `session.py` knows the backend; the runner persists
   through the repository interfaces so JSON-mode runs survive restarts.
5. **LLM-on by default** for API-triggered runs; the incremental path (`reference_version_id`) is the re-run
   mitigation. A per-run LLM-off toggle can come later.
