# Incremental generation (version4)

> **Project context — one part of it.** Start at [PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md),
> the index: current state, how to read the context, every file. The sections below moved here
> from the single-file context on 2026-09-28, unchanged except link paths, and keep their numbers —
> "PROJECT_CONTEXT §N" still finds them. Written over time: where a section and a newer dated
> entry in [history/](history/) disagree, the newer entry and the code win.

**Sections:** [23. version4 — Incremental Changes feature (this session, 2026-06-18)](#23-version4--incremental-changes-feature-this-session-2026-06-18)

## 23. version4 — Incremental Changes feature (this session, 2026-06-18)

> `version4` is the **active working branch**. This section is the orientation + **decisions + status**
> for the **incremental document regeneration** feature. Authoritative design lives in
> **[docs/production-redesign/04-incremental-changes-implementation.md](../docs/production-redesign/04-incremental-changes-implementation.md)**
> (approach, v2.1) and **[docs/production-redesign/05-incremental-api-spec.md](../docs/production-redesign/05-incremental-api-spec.md)**
> (UI HTTP API). Read those for depth; this is the map.

### 23.1 What `version4` is
- Created off `origin/main` (`f3946bd`). `main` is the live code line: **`layers`/`component` schema** (§4d —
  `modulesGroups`→`layers`, `module`→`component`, `modules.json`→`components.json`), plus
  `--data-dictionary`/`--macros`/`--include-path`/`--selected-layer`/`--selected-component` CLI, a Streamlit
  `ui/`, and the `SampleCppProject` fixture.
- Brought over from `version3`: `engine/` and `docs/production-redesign/01..03`. This `PROJECT_CONTEXT.md`
  = main's §1–§20 + §21 (backend) + §22 (production redesign) + this §23.

### 23.2 Done this session
1. **Backend adapted to layers/component** ([engine/main.py](../engine/main.py), [engine/models.py](../engine/models.py)):
   config source `modulesGroups`→`get_flat_groups(layers)`; component-keyed `fn_id`s + `functions_<group>.json`
   naming (`safe_filename` spaces→`-`); `_resolve_group_name` vs group names; `POST /config` splice generalized
   to the `layers` key; `UpdateConfigRequest.layers`. Verified (25 routes import + functional probe).
2. **Backend docs corrected** to layers/component ([engine/API_DOC.md](../engine/API_DOC.md),
   [engine/PROJECT_CONTEXT.md](../engine/PROJECT_CONTEXT.md)); `engine/repository_config.json` → `SampleCppProject`.
3. **`engine/git_service.py`** (M0 #1 — **DONE**): `clone_repo` (HTTPS user/token; token reset out of
   `.git/config`, never logged), `fetch`, `checkout`, `current_commit`, `list_branches`, `list_commits`, and the
   baseline primitives `is_ancestor` / `nearest_ancestor` / `merge_base` / `changed_files`. `shell=False`
   deliberately (credential/URL safety). Verified against the repo + a local clone.
4. **Design docs**: `04` (incremental approach, **v2.1**), `05` (UI API spec).

### 23.3 Incremental — key decisions (do NOT re-derive these)
- **Approach 2** (doc 03 §12): git-diff **narrowed parse** + stored-graph impact + selective regen; **full
  parse is the fallback** (first version / no ancestor / `mode:"full"`).
- **Version = one generation run** (`versionId`); records branch/commit/scope/dataDictId/baselineVersionId/
  counts. **All versions kept.** Same commit generated twice (different scope/data-dict) = two versions.
- **Baseline = auto nearest-ancestor** (`git merge-base --is-ancestor` over prior versions' commits; nearest by
  `rev-list --count`); **optional user override** (`baseVersionId`) with ancestor/nearest **warnings**; none →
  full gen. **Correctness is base-independent** — the base only affects *parse speed* (reuse is content-addressed).
- **`edges.json` is SLIM** — only **type/macro usage**. Calls/globals come from `functions.json`
  (`calledByIds`/`callsIds`, `reads`/`writesGlobalIds`); the **recursive/transitive closure is computed by
  reverse-BFS**, not stored. (Don't re-store the call graph — it already exists in `functions.json`.)
- **Reuse = `cache/index.json`**, a `{fingerprint → (versionId, entityKey)}` **POINTER index** — **NOT** a
  duplicate blob store. Output content lives **once** in each version's `model/output`; reuse = look up the
  fingerprint → copy from the pointed-to version. Plus **carry-forward** from the baseline version.
- **`fingerprint`** = `sha256(source_hash + sorted(dependency source-hashes))` — **content-only**; the LLM
  recipe is intentionally NOT folded in (recipe-fingerprint invalidation **dropped by decision** — an approved
  document is reused regardless of model/prompt changes).
- **Data dictionary** is per-version, replaceable; **uploaded by onboarding's separate API**; `generate` only
  references a `dataDictId`. A data-dict-only change → cheap reassembly (interface-table ranges), **no LLM**.
- **Onboarding is OUT of scope** (other engineer): registration, git credentials, the initial clone, the
  project's `layers`, the data-dict upload. Incremental **consumes** `projectId` + `repo/` + `layers` +
  data dict + `branch`+`commit`.
- **version-id assignment**: sequential per project (`v1, v2, …`), assigned at generation start. **Collision-
  free** because generations are **serialized per project** (single shared clone → one `git checkout` at a
  time; a 2nd concurrent `generate` → `409`). Global key = `(projectId, versionId)`. `projectId` uniqueness is
  onboarding's responsibility.
- **Engine flow** (doc 04 §5 — validated 8 steps): copy baseline → new version; `git diff` changed files;
  partial-parse + merge; classify changed/new/deleted; **impact BFS** (all axes; over-approx virtual/fn-ptr;
  move/rename); selective regen (index-check before LLM); reassemble (Phase 3 + 4); record version.
  **Impact analysis is the #1 correctness trap** — must regenerate dependents that live in *unchanged* files,
  else the document goes stale.
- **Regenerated dependents are cached too** (doc 04 §5 steps 6+8): every entity in
  `{changed ∪ new ∪ impacted}` that is LLM-regenerated gets a **new `cache/index.json` pointer entry** (→ the
  new version), so a future version / revert / cross-branch-identical run reuses it. Because the fingerprint
  includes `sorted(dependency source-hashes)`, an impacted dependent correctly **misses** on this version
  (its dep changed) and **hits** later when that dep state recurs. *Carried-forward* (unchanged & unimpacted)
  entities get **no** new entry — their fingerprint already points at the version that first produced them.
- **Storage interface (D9 — doc 04 §3):** all incremental-store access goes through a thin interface
  (`engine/incremental/stores.py`: `VersionStore`, `ReuseIndex`, `HashStore`, `EdgeStore`) — **JSON-file impl now,
  Postgres impl later behind the same methods**. The §5 engine + the APIs call *only* the interface (no
  scattered `open()`/`json.load`), so the §10 Postgres swap is one implementation, not a refactor. **Scope =
  the incremental *metadata* stores only** (versions/hashes/edges/reuse-index/jobs); the analyzer's per-version
  `model/`+`output/` stay file-based until the DB-native pipeline rewrite (§22.3). Git auth is **D8** (POC
  plaintext: token injected into the URL then `origin` reset credential-free; `engine/git_service.py`).

### 23.4 Storage (per project) — examples in doc 04 §4
```
workspaces/<projectId>/
  project.json                 [onboarding]  name, layers, repo ref, current dataDictId
  repo/                        [onboarding]  single clone; incremental does `checkout <commit>`
  datadict/<dataDictId>.csv    [onboarding / separate API]
  cache/index.json             [INCREMENTAL]  {fingerprint -> {versionId, entityKey}}  (pointer index)
  versions/index.json          [INCREMENTAL]
  versions/<versionId>/        manifest.json, hashes.json (full entity->source-hash snapshot),
                               edges.json (SLIM: type/macro only), config.json, model/ output/ documents/
```

### 23.5 Implementation plan + status
- **P0 `git_service` — ✅ done.**
- **P1 onboarding stub fixture — done, then removed** (with the Streamlit UI in #28). `engine/seed_workspace.py` seeded
  `workspaces/<projectId>/` with the **onboarding-owned** parts only (doc 04 §4): `project.json` (name, the
  project's `layers`, repo ref, `currentDataDictId`), `repo/` (a real **full** clone via
  `git_service.clone_repo`, public/no-creds), and `datadict/dd-001.csv` (seeded from
  `engine/config/data_dictionary.csv`). Leaves `cache/`+`versions/` to the incremental engine. Default fixture =
  `projectId=samplecpp`, repo `github.com/vishal9359/SampleCppProject` (branches `main` + `feature1/2/3`,
  topology purpose-built for nearest/far/divergent-ancestor tests — see the repo's `README.md`). `workspaces/`
  is gitignored (data). (Both this seed script and `engine/git_service.py` were later removed.)
- **M1 — version-producing FULL gen + substrate** — *in progress.*
  - **M1.1 `--config`/`ANALYZER_CONFIG` — ✅ done.** `run.py --config <path>` resolves+validates the path and
    exports `ANALYZER_CONFIG` **before** importing `utils` (which loads config at import time), so this process
    and every phase subprocess (env inherited) honor it. `core/config.py load_config()` reads `ANALYZER_CONFIG`
    first: if set it loads that file **as-is** (JSONC) — **no `config.local.json` merge**, for reproducibility —
    and **fails loud** (`FileNotFoundError`) on a set-but-missing path; unset → existing `config.defaults.json`+local
    behavior. Tests: `tests/unit/test_core_config.py::TestLoadConfigAnalyzerConfigOverride` (5).
  - **M1.2a entity hashing — ✅ done.** New `engine/incremental/hashing.py` (token-based full SHA-256;
    formatting-insensitive, comment-inclusive — folds in the preceding doc comment; visibility macros expand
    away and are intentionally excluded since the hash governs *output reuse*, and visibility is caught by the
    changed-file re-parse). `parser.py` stores `_sourceHash` on function/global entries (internal — does **not**
    leak into `functions.json`) and writes `model/hashes.json` `{entityKey→token-sha256}` for all four kinds:
    functions (model key), globals (model key), types (qn), macros (`name@relFile`, line-stable). `model_io`
    gains `HASHES`/`EDGES` (not in `ALL_MODEL_NAMES`). Verified on `SampleCppProject`: 353 entities, all 64-hex,
    **deterministic** across re-parse, and a one-function edit changed **exactly 1** hash while a whitespace-only
    reformat of a sibling changed **none**. Tests: `tests/unit/test_incremental_hashing.py` (12).
  - **M1.2b slim usage index — ✅ done.** `parser.py` adds a `visit_usage` pass (3rd walk on the same TU, no
    extra parse) that threads the enclosing function like `visit_calls`: **type usage** via AST
    (`_project_type_qn` resolves return/param/`TYPE_REF`/`VAR_DECL` types through pointer/ref/array layers to a
    project type's qn) and **macro usage** via per-function identifier-token capture. New pure
    `engine/incremental/edges.py::build_edges` (no libclang — unit-tested) inverts to
    `model/edges.json` `{typeUsers, macroUsers}` keyed by model fid, **filtered to types/macros that have a hash**
    so every key cross-references `hashes.json`; keys+values sorted for byte-stable output. Macro keys
    `name@relFile`, type keys qn — identical to `hashes.json`. Calls/globals are deliberately **not** here
    (functions.json has them). Verified on `SampleCppProject`: 14 types / 1 macro used, **0** key/fid mismatches
    vs `hashes.json`, `Point`/`Status`/`Mode` resolve to the right functions, deterministic. Tests:
    `tests/unit/test_incremental_edges.py` (8). *Known limits (M2/M3): typedef→underlying transitive type edges
    and synthetic-from-VAR_DECL functions are not tracked; macro detection over-approximates (token-name match).*
  - **M1.3a substrate — ✅ done.** **D9 store interface** `engine/incremental/stores.py`
    (`Workspace`/`VersionStore`/`HashStore`/`EdgeStore`/`ReuseIndex`, JSON-file impl, atomic writes) +
    **fingerprints** `engine/incremental/fingerprint.py` (`compute_fingerprints` =
    `sha256(source_hash + sorted(dep source_hashes))` — **content-only**, no recipe component (recipe-fingerprint
    invalidation dropped by decision) — over functions+globals; deps = callees/globals from functions.json +
    types/macros forward-inverted from edges) +
    the **version-producing full-gen orchestrator** `engine/incremental/generate.py` (CLI:
    `python engine/incremental/generate.py --project-id … --branch … --commit … --scope group:G --no-llm`): checkout
    → resolved config (global + project layers) → run `run.py --config` → capture `model/output/documents` +
    `hashes.json`/`edges.json` into `versions/<vN>/` → seed `cache/index.json` → write manifest + index. Verified
    e2e on `samplecpp` (scope group:Support, LLM off): `versions/v2` complete, 127 entities fingerprinted, docx
    captured, reuse index seeded; failed attempts recorded (status=failed) and still consume a versionId. Tests:
    `tests/unit/test_incremental_stores.py` (13) + `test_incremental_fingerprint.py` (7).
  - **M1.3b backend HTTP — ✅ done.** [engine/main.py](../engine/main.py) gains `POST /api/v1/projects/{id}/generate`
    (FULL path only — spawns `engine/incremental/generate.py` as a job via `_spawn_generate`; pre-allocates the
    versionId, serializes per project with **409**, returns `{versionId, jobId, decision:"full", …}`),
    `GET …/versions`, `GET …/versions/{id}` (+ per-doc `downloadUrl`), `…/versions/{id}/download`
    (`.docx`, or `.zip` for multi-doc). generate.py: `--version-id` (pre-allocatable) + early **running** manifest
    (so the version is queryable immediately) + analyzer stdout/stderr **inherited** (so run.py phase markers land
    in the per-job log → existing `/jobs/{id}/status` tracks progress). Verified via TestClient on `samplecpp`:
    versions list/detail/download (real 47 KB docx) + validation (404/400/409). *POST happy-path not exercised
    live (TestClient blocks on the watcher; orchestrator is e2e-tested via the identical CLI path) — test live on a
    running server. `mode:"auto"`/baseline (incremental) is M2.*
- **M2 — incremental engine — ✅ done** (M2.1–M2.4 below; incremental generation works e2e + via the API).
  - **M2.1 baseline selection + preview — ✅ done.** `engine/incremental/git_ops.py` (engine-local git wrapper —
    checkout/current_commit/is_ancestor/merge_base/rev_list_count/changed_files/nearest_ancestor; decoupled from
    `engine/git_service.py`, consolidation deferred to M3) + `engine/incremental/baseline.py::select_baseline`
    (auto nearest-ancestor among *complete* versions → none = full; optional `baseVersionId` override with
    **divergent** [not-ancestor] / **not-nearest** warnings; base only narrows the parse, never staleness) +
    backend `GET …/generate/preview?commit=&baseVersionId=` (read-only, no checkout). `generate.py` now uses
    `git_ops`. Verified: tmp-repo unit tests (`test_incremental_git_ops.py` 12 + `test_incremental_baseline.py` 11)
    + TestClient preview on `samplecpp` (main→incremental/v2/nearest/0-changed, feature1→full, override-v2→divergent
    +warning, unknown→404).
  - **M2.2 classify + impact BFS — ✅ done.** `engine/incremental/impact.py` (pure): `classify(baseline_hashes,
    target_hashes)` → {changed/new/deleted/unchanged}; `impact_set(changed_keys, functions, edges,
    extra_seed_functions=)` → set of function fids to regenerate = changed/new functions + **everything
    transitively depending on any changed entity** (reverse-BFS: callers via `calledByIds`, global users via
    inverted reads/writes, type/macro users via `edges.json`; visited-set handles cycles; `extra_seed_functions`
    injects deleted entities' baseline callers). The #1 staleness trap — covered. Tests:
    `tests/unit/test_incremental_impact.py` (12).
  - **PARSE-STRATEGY DECISION (D10):** the M2 engine uses a **FULL parse** of the checked-out commit (correct
    call graph by construction), and the incremental win comes from **selective LLM regeneration** (classify →
    impact BFS → reuse). **Narrowed/partial parse (doc 03 D2 "Approach 2") is DEFERRED** to a later optimization
    (doc 04 §10's parse cache): correct narrowed parse needs cross-file call/reverse-edge reconciliation that is
    complex and easy to get subtly wrong → staleness, whereas the *primary* benefit (skip the rate-limited LLM for
    unchanged+unimpacted entities = hours→minutes) is parse-strategy-independent and a full parse is **never
    stale** (D7). Parse time becomes the bottleneck to optimize only after LLM time is removed.
  - **M2.3 incremental engine — ✅ done.** `engine/incremental/engine.py::generate_incremental`: baseline-pick →
    checkout → full parse (`run.py`) → `plan_incremental` (classify vs baseline `hashes.json` + impact BFS +
    deleted-caller seeding) → **carry forward** baseline outputs (description/behaviour names) for the reuse set
    (`carry_forward_descriptions`) → reassemble (`run.py --from-phase 4 --use-model`) → capture version + seed
    reuse index + manifest (decision/regenerated/reused/baselineVersionId/carriedForward). Falls back to
    `generate_full` when no baseline. Pure helpers `plan_incremental`/`carry_forward_descriptions` unit-tested
    (`test_incremental_engine.py` 8). **Verified e2e on `samplecpp`**: baseline v1@C3 (125 entities) → incremental
    v2@main-HEAD = decision=incremental, baseline=v1, **3 new** (multiply/clampPositive/coreReset) + impact **6**
    (incl. a deleted function's transitive callers App::main/calculate via MultiplyOperation::apply), **109
    reused/carried-forward**, 14.4s vs 31.7s full. (The `Cross::Dispatch::multiply` "deleted" is a pre-existing
    parser name-resolution fuzziness → safe over-regeneration, never stale.) *Descriptions reuse via the version3
    EntityCache on LLM-on runs; flowchart-level reuse (restrict the engine to the impact set) is M2.4.*
  - **M2.4a mode:auto dispatch — ✅ done.** `POST /api/v1/projects/{id}/generate` now resolves the target +
    runs `select_baseline` and **dispatches**: `mode:"auto"` (default) → incremental (spawn `engine.py`) when a
    baseline ancestor exists, else full (`generate.py`); `mode:"full"` forces full. Response carries the real
    `decision` + `baselineVersionId`/`baselineCommit` + `warnings`; `baseVersionId` override forwarded. `commit not
    in repo` → 409. Verified via TestClient (auto@main→incremental/engine.py/baseline=v2, full→generate.py,
    auto@feature1[no ancestor]→full, 400/409).
  - **M2.4b flowchart-level reuse — ✅ done (file-level; later narrowed by M3.5 and replaced by M3.6 function-level).** `views/flowcharts.py::_apply_incremental_plan`
    (gated on `model/incremental_plan.json`; absent → unchanged full behaviour) **carries forward** the baseline
    version's `output/<scope>/flowcharts/*.json` then **restricts** the flowchart engine's functions file to the
    impacted source files (engine overwrites only those). `engine.py` computes `impactedFiles` BEFORE the run
    from the **baseline model + `git diff`** (over-approx, safe — no Phase-split) and writes/cleans the plan.
    The `engine/flowchart/` engine is unchanged. Verified e2e on `samplecpp` (carried 3 / restricted 16 in 9 files;
    output complete, plan not leaked into the version). *(Superseded by M3.1: the impacted-file seeding is now
    precise/function-level, not file+git-diff.)*
- **M3 — hardening** — *in progress.*
  - **M3.1 precise function-level flowchart reuse — ✅ done.** Added **`run.py --to-phase N`** (stop after a phase;
    additive filter over `plan_runs`' output by script→phase, gated — `None` = unchanged). `generate_incremental`
    now **Phase-splits**: `--to-phase 2` (parse+derive) → compute the **precise** impact from the fresh target
    model (`plan_incremental`) → carry forward descriptions + write the impacted-files plan → `--from-phase 3
    --use-model` (views+export; flowcharts restricted to impacted files, rest carried). One impact computation
    drives both description + flowchart reuse. Verified e2e on `samplecpp`: impacted files 9→**4**, restricted
    16→**14** (exactly the 6 impacted functions' source files); v2 complete, output correct, no plan leak.
  - **M3.2 hierarchy-summary reuse — ✅ done (the real payoff fix).** Diagnosis: descriptions/behaviourNames are
    **off by default**, so M2.3's description carry-forward was a no-op; the dominant default LLM costs are
    **flowchart labeling** (fixed by M3.1) and **hierarchy summarization** (Phase 2) — and the `PkbCache` keys on
    the *whole* `functions.json` hash, so any change re-summarized **everything** (this is why an 8-line diff took
    full time). Fix: the engine now Phase-splits at **Phase 1** (`--to-phase 1` → impact → carry forward baseline
    `description`+`phases` for the reuse set → `--from-phase 2`). The summarizer only summarizes functions with no
    `description` (`project_scanner._summarize_functions`), so carrying it forward makes it **skip the reuse set**
    — function-level summarization (the big cost) is restricted to the impact set with **no `model_deriver`/
    summarizer change**. Verified e2e (C1→C3, scope Support): regenerated 9 / reused 104, flowcharts restricted to
    5 files, output correct. *File/module/project summaries still re-run (~minor, not function-gated) — a later
    refinement.*
  - **M3.3 full Phase-2 enrichment reuse + 4 fixes — ✅ done.** An LLM-on test (744s for an 8-line diff) exposed
    that M3.2 only covered function summaries, while the user's config has `descriptions:True`+`behaviourNames:True`
    and the dominant cost was **behaviour-names (417s) re-run for all 113 functions**, plus globals (46s),
    file/component summaries (117s), and PNG re-render (92s) — none reused; and the captured `documents` list had
    **stale/duplicate docx** from prior runs. Fixes:
    (1) **documents** — `engine`/`generate` clean `output/` before each run so a version captures only its own docs.
    (2) **`model_deriver` incremental mode** — reads `incremental_plan.json` (`impactFids`/`impactedGlobals`) and
    restricts behaviour-names + descriptions + global enrichment to the impact set (the engine carries forward the
    reuse set's `description`/behaviour-names/`phases` into `functions.json` and global descriptions into
    `globalVariables.json` before Phase 2). (3) **file/component summary gating** — `_run_hierarchy_summarizer`
    pre-populates `knowledge.file_summaries`/`component_summaries` from the baseline for unchanged files/components,
    and `project_scanner._summarize_files`/`_summarize_components` skip those already present. (4) **flowchart PNG
    reuse** — `views/flowcharts.py` carries forward baseline PNGs and re-renders only impacted units. Verified e2e
    (LLM-off flow): "enriching 9 functions + 3 globals; reusing the rest", documents=[just the scope's doc], PNGs
    carried. `tests/unit/test_incremental_engine.py` +2 (carry_forward_globals).
  - **M3.4 end-of-run report — ✅ done.** `engine/incremental/report.py` (`build_report` pure + `emit_report`): both
    `generate_incremental` and `generate_full` print a summary at the end — **logged** (to `logs/run_<date>.log` via
    `get_logger`) **and saved** to `versions/<id>/report.txt`. Sections: inputs (project/branch/commit/scope/
    **baseline + changed-file count**/dataDict/LLM recipe/status/**wall-clock**), **change classification** (changed/
    new/deleted/unchanged, broken down by kind), and **reuse accounting** (functions/globals/flowcharts:
    regenerated vs reused + %; summaries note). Tests: `tests/unit/test_incremental_report.py` (6). Example on
    C1→C3: `Functions regenerated 9/113 -> reused 104 (92%)`, `Globals 3/12 -> reused 9 (75%)`, `Flowcharts 5/18
    files -> carried 13 (72%)`.
  - **M3.5 flowchart impact-scoping fix — ✅ done (big speedup).** An LLM-on real-diff (C1→C3) took 1021s with the
    **flowchart engine alone = 497s**, even though only 3 functions changed. Cause: flowcharts were regenerated
    for the **full impact set** (changed + transitive callers), pulling in `App/Main.cpp`'s *large* functions
    because they call the changed `Math`. But **a function's flowchart is its own CFG + call-site labels — it does
    NOT change when a callee's *body* changes**. Fix: the plan now carries a separate **`flowchartFiles`** = files
    of only the *directly* changed/new/deleted functions (descriptions/summaries keep the full-impact
    `impactedFiles`, since those genuinely depend on callees, and are cheap); `views/flowcharts.py` restricts on
    `flowchartFiles`. (Also confirmed: the flowchart `PkbCache` caches the PKB *index* keyed by the whole
    functions.json hash — **not** LLM labels; there is no label cache — so unifying caches wouldn't help; reuse is
    handled by version-level carry-forward.) Verified e2e: C1→C3 flowcharts dropped from **12 functions / 5 files**
    to **3 functions / 1 file** (App no longer re-labeled); report shows `Flowcharts carried 15/18 (83%)`.
  - **M3.6 function-level flowchart granularity — ✅ done (supersedes M2.4b file-level).** Even after M3.5,
    flowcharts regenerated at **file** granularity: a changed file re-labeled *all* its functions (e.g. changing
    `Math::subtract` re-labeled `add`/`computeBoth` too). Now per-**function**: the plan carries **`flowchartFids`**
    (the directly changed/new fids); `views/flowcharts.py` restricts the engine to *only* those functions, carries
    forward all baseline flowchart JSONs+PNGs, then **splices** each fresh per-function flowchart into the baseline
    file JSON via `_merge_incremental_flowcharts` — **join key = entry `name` (== `functions.json` `qualifiedName`,
    verified exact)**. Merge rule: keep unchanged (baseline), replace changed (fresh), **drop deleted** (not in the
    target's current set — handles deletion-only files whose deleted entry still sits in the carried JSON), append
    new; baseline file order preserved. Only changed functions' PNGs re-render (the rest are carried). Unit set for
    the merge = `flowchartFiles` ∩ in-scope (so deletion-only files are rebuilt); engine restriction =
    `flowchartFids` ∩ scope. Safe fallback: if baseline flowcharts are missing → full flowchart regen. Report now
    counts flowcharts at **function** granularity (`flowcharts` stat: regenerated `len(direct_fns)` / total
    functions), split from file-level **summaries** (`files` stat). Other generation types were already
    function/entity-level (descriptions/behaviour-names/globals via skip-if-described + `only_fids`/`only_globals`);
    file/component summaries are per-file/per-component by nature. Verified e2e LLM-off (C1→C3, scope Support):
    flowchart engine restricted to **1 changed function** (was 3 file-level), `Utils.json` correctly retains all 3
    (`add`,`subtract`,`computeBoth`) with `subtract` fresh, **1 PNG** re-rendered; +6 merge unit tests (120 pass).
  - **M4.0 per-TU include-closure capture — ✅ done (foundation for narrowed parse; no behaviour change).**
    New `engine/incremental/parse_includes.py` (pure, libclang-free): `to_repo_relative` + `build_closure` —
    normalize libclang include paths to **repo-relative, forward-slash, case-preserved**, drop out-of-repo
    (system/third-party) headers, dedup/sort, exclude the TU's own source. `parser.py::_capture_tu_includes(tu, path)`
    reads `tu.get_includes()` in the first parse pass (best-effort — never breaks parsing) and `main()` writes
    **`model/tu_includes.json`** `{tuRelPath → [in-repo included rel paths]}` (new `model_io.TU_INCLUDES`, not in
    `ALL_MODEL_NAMES`; captured into each version automatically since `capture_artifacts` copytrees `model/`). This is
    the map the future **M4 narrowed parse** intersects with the `git diff` to find affected TUs — soundly covering
    header/macro/template fan-out (all propagate only through `#include`). Paths are case-**preserved** so they line up
    with `functions.json` `location.file` + `git diff`; case-insensitive *matching* is M4.1's job. Verified e2e LLM-off
    (`SampleCppProject`): 19 TUs / 42 in-repo edges, paths clean (no backslash/drive/`..`/leading `/`), no system
    headers leaked, `Utils.h` fans out into `Main.cpp`'s closure, form matches `functions.json` (18/19). +8 unit tests.
    **Full M4 design + corner-case audit + never-stale full-reparse triggers + `--verify-parse` self-check: doc 04 §11
    (v2.3, D10 + M4 milestone).** M4 plan is M4.0 done → M4.1 affected-TU computation (`affected.py`, pure) → M4.2
    fingerprint hardening (flags+libclang version) → M4.3 parse-merge + reverse-recompute → M4.4 engine wiring → M4.5
    self-check → M4.6 corner-case hardening. **M4 only worth building once Phase-1 parse is the *measured* bottleneck.**
  - **M3.8 branch/commit listing endpoints — ✅ done.** `GET /projects/{id}/branches` (doc 05 G1) +
    `GET /projects/{id}/branches/{branch:path}/commits?limit=&offset=` (G2) in `engine/main.py`, thin
    wrappers over the existing `git_service.list_branches`/`list_commits` on the project's clone (the UI's
    "pick a target commit" path). Verified on `samplecpp` (branches main/feature1/2/3; main 6 commits).
  - **M3.9 version-scoped reads — ✅ done.** `?projectId=&versionId=` on `/components`, `/components/{id}`,
    `/components/{id}/modules`, `/functions/{fn_id}` (GET+PATCH), `/flowcharts/{fn_id}` now serve that
    version's snapshot. Mechanism: a request-scoped **`_ReadRoots`** (contextvar `_roots()`, default = shared
    `model/`+`output/`); `_enter_version_scope(projectId, versionId)` at the top of each endpoint points the
    read helpers (`_load_functions`/`_load_groups`/`_project_base_path`/`_module_file_for_fn`/`_persist_description`/
    `_find_flowchart_entry`) at `versions/<vid>/{model,output}` + that version's `config.json` (reset in `finally`;
    per-task so concurrent requests don't collide). 404 on unknown version. Also hardened
    `_find_flowchart_entry`: walks **all** `flowcharts/` dirs under output (handles scoped `output/<scope>/flowcharts/`)
    and matches `functionKey` (real engine) **or** falls back to `name` == fn_id's qualifiedName (POC fake generator).
    `/config` (canonical *source* config) + `/project/structure` (working tree) left project-level — orthogonal to
    versions. Verified e2e (TestClient) + 10 unit tests (`tests/unit/test_backend_version_scope.py`); backend imported
    lazily there to avoid the `models` name clash with the flowchart tests at collection time.
  - **M3.7 cross-version reuse-index lookup — ✅ done (the D3 reuse payoff).** The engine now *reads*
    `cache/index.json` (it only seeded it before). New pure `engine.carry_forward_from_index(impact_keys,
    target_fps, target_entities, index, current_version_id, src_loader, fields)`: for each IMPACT-set entity
    whose **content fingerprint** already exists in the index (produced by a *prior* version — a revert, or
    code identical to another branch), it copies that version's stored output (`description`/behaviour-names
    for functions; `description` for globals) instead of regenerating. Reused entities drop out of the LLM
    regen sets (`regen_impact`/`regen_globals` → the plan's `impactFids`/`impactedGlobals`), so Phase 2 skips
    them. Fingerprints (content-only) are computed once and reused to seed the index at the end. Report adds an
    **X-version** line + `crossVersion` stat; manifest gets `crossVersionReused`. Verified e2e LLM-off: re-gen
    of C3 with baseline v1 → **functions regenerated 0/113 (100% reused), 9 reused cross-version from v2**
    (which already produced C3). +7 unit tests. **Follow-on (M3.7b):** flowchart cross-version reuse — a reused
    function's *flowchart* still regenerates (flowchartFids unchanged); reusing it needs the splice to pull
    per-fid from arbitrary versions.
  - **Move/rename orphan cleanup — ✅ done.** `views/flowcharts.py::_prune_orphan_flowcharts(out_dir, valid_stems)`
    runs right after the baseline carry-forward (both function- and file-level modes): drops carried flowchart
    JSON (`<stem>.json`) + PNG (`<stem>_<func>.png`) for source-file stems no longer in the current model (a
    deleted or **renamed** file), so a version's output carries no stale units. No-op when `valid_stems` is empty
    (guards against a load glitch nuking the carry-forward); prefix-collision safe (`Foo` won't drop `Foobar`).
    +4 unit tests; e2e confirms zero spurious pruning on the no-rename C1→C3 diff. **Note: also confirmed unit
    diagrams use NO LLM (pure structural) — incremental reuse there would only save PNG-render time; deprioritized.**
  - **git_ops/git_service consolidation — ✅ done (no behavior change).** `engine/incremental/git_ops.py` is now the
    **single** home for every local git primitive (checkout / current_commit / ancestry / diff / `list_branches` /
    `list_commits` — the last two moved over from git_service). `engine/git_service.py` keeps **only** the
    credentialed network ops (`clone_repo`, `fetch`, `_auth_url`, `_clean_url`) and **re-exports** the locals from
    git_ops, so existing `git_service.<fn>` callers and `except git_service.GitError` keep working — `GitError` is
    now one class (`git_service.GitError is git_ops.GitError`). The duplicated baseline primitives
    (`is_ancestor`/`merge_base`/`changed_files`/`nearest_ancestor`/`_run`/`_check`) are gone from git_service. Layer
    direction preserved (backend→src; git_ops has no backend dep). Verified: 20 git_ops+backend tests pass; M3.8
    endpoints flow through the re-export; identity + unified-GitError checks green.
  - **M3.7b flowchart cross-version reuse — ✅ done.** A directly-changed function reused from the index (a
    revert) has the SAME content → SAME flowchart as its source version, so it's no longer regenerated. Engine:
    `xver_flowcharts = {fid → sourceVersionDir}` (= `direct_fns ∩ index_reused`), excluded from `flowchartFids`,
    written to the plan as **`crossVersionFlowcharts`**. View (`views/flowcharts.py`): `_source_unit_flowchart`
    finds the unit's flowchart in the source version's output (walks scoped `output/<scope>/flowcharts/`); the
    splice gains a **third source** (`fresh > x-ver > baseline`) and copies the source PNG; if the source version
    has no flowchart for it, falls back to regenerating (adds the fid back to the engine's set). Report X-version
    line + `crossVersion.flowcharts` count. Verified e2e: re-gen of C3 with baseline v1 → flowcharts **restricted
    to 0 regenerated, 1 cross-version splice** (subtract from v2), `Utils.json` complete; **so a re-gen/revert is
    now 0 LLM end-to-end** (descriptions + behaviour + flowcharts all reused). +2 unit tests (three-source priority,
    x-ver new fn).
  - **Virtual-dispatch over-approximation (D7 audit) — ✅ done.** Audit found: a virtual call `base->m()`
    resolves (libclang) to the static method — or, when the base is pure-virtual, an *arbitrary* override by
    name — so sibling overrides got **no caller** (e.g. `MultiplyOperation::apply` showed `calledByIds: []`):
    changing an override wouldn't impact the dispatcher (**stale**) and the model was inaccurate. Fix: new pure
    `engine/incremental/virtual_dispatch.py::spread_virtual_families` — unions virtual *families* (override→base via
    `clang_getOverriddenCursors`, bound through the **C API by ctypes** since this Python binding lacks the wrapper;
    queried on `cursor.canonical` because out-of-line defs report no overrides) and links every caller of any member
    to **all** members. `parser.py` collects `_override_pairs` in `visit_definitions` and spreads in `build_metadata`
    (before calledByIds/callsIds are derived). Verified: `applyWithOperation.callsIds` now lists both overrides,
    `MultiplyOperation::apply.calledByIds = [applyWithOperation]`. Degrades safely (no spread) if the C API is
    absent. +6 unit tests. **Function-pointer dispatch = documented limitation** (target unknowable statically;
    dispatcher descriptions are generic → low staleness risk; use `mode:"full"` if guaranteed freshness needed).
    Details in doc 04 §5 checklist (Virtual dispatch / Function pointers rows).
  - **M3.10 unit-diagram incremental reuse — ✅ done.** `views/unit_diagrams.py` now gates on
    `incremental_plan.json`: carries forward the baseline version's unit diagrams (`.mmd`+`.png`), prunes orphans
    (renamed/deleted units), and regenerates only **affected units** = units of the impacted functions PLUS their
    1-hop cross-unit neighbours (`_affected_units` — a unit diagram shows the edges incident to the unit, so any
    change to a function in it OR a function it calls / is called by can alter it; over-approximates, never stale).
    No-LLM view, so the win is render time only. Verified e2e: C1→C3 regenerated **1 affected unit of 3**, other 2
    carried forward; +6 unit tests. (No incremental plan → original full wipe+regenerate.)
  - **All doc-05 incremental APIs implemented** ✅ — G1 `/branches`, G2 `/branches/{branch}/commits`, #1
    `/generate/preview`, #2 `/generate`, #3 `/versions`, #4 `/versions/{id}`, #5 `/download`, #6–#10 job
    status/logs/cancel/export (reused), #11–#13 `/components`·`/functions`·`/flowcharts` (version-scoped, M3.9),
    #14 `/config`, #15 `/project/structure`.
  - **M4 narrowed parse — ✅ COMPLETE (M4.0–M4.6)** (for big 10k+-function codebases; full design in doc 04 §11).
    Avoids the whole-project Phase-1 parse: parse only the affected TUs, reuse the baseline model for the rest, merge
    + recompute reverse edges. Opt-in (`--narrowed-parse`) + `--verify-parse` self-check; full parse stays the default
    until the self-check is clean across a diff matrix on a large repo. Validated byte-equal (set-level) on C1→C3.
    - **M4.1 affected-TU set — ✅ done.** `engine/incremental/affected.py` (pure): `affected_tus(changed, tu_includes)`
      = TUs whose closure ∩ git-diff ≠ ∅ (+ new `.cpp` not yet in the map; case-insensitive match on Windows);
      `full_reparse_reason(status_pairs, tu_includes)` = the §11.4 must-full-reparse triggers (no closure map; a
      **header added/deleted** → shadowing risk). `git_ops.changed_files_status` (`git diff --name-status`, renames
      split into D+A). +9 unit tests.
    - **M4.2 parse fingerprint — ✅ done.** `fingerprint.parse_fingerprint(clang_args, std, toolchain)` (order-
      preserving over `-I`/`-D`) — a mismatch vs the baseline version's value forces a full re-parse (flags/
      toolchain changed). +4 unit tests.
    - **M4.3 partial-parse + merge — ✅ done (the core).** `parser.py --only-files <listfile>` parses only the
      affected TUs → a *forward-only* partial model; verified (1 TU → 3 fns). Parser also emits
      **`model/entity_files.json`** `{entityKey → defining file}` (covers all hashed entities — types/hashes have no
      inline location; full parse: 353/353). `engine/incremental/parse_merge.py::merge_model(baseline, fresh, drop_files)`
      (pure): drop baseline entities whose file ∈ drop, overlay fresh, merge edges/dataDictionary/tu_includes by file,
      then **recompute calledByIds** (filter callsIds to merged fns → re-run virtual spread → invert). Verified on REAL
      data: full-parse a baseline, re-parse 1 TU as a partial, `merge_model(...)` == the full parse
      (functions/hashes/globals/edges all match). +7 merge unit tests. *(`override_pairs` emission for cross-affected
      virtual re-spread → done in M4.6; calledByIds **list order** byte-identity remains set-equal, the correctness bar.)*
    - **M4.4 engine wiring — ✅ done + validated (opt-in).** `generate_incremental(narrowed_parse=…)` /
      `engine.py --narrowed-parse`: when on AND the baseline has a parser-level snapshot + no full-reparse trigger,
      it computes `affected_tus`, runs `run.py --to-phase 1 --only-files <list>` (threaded through
      `group_planner`→`run.py`→`parser.py`), and `parse_merge.merge_model(baseline_parse, partial, drop)` → writes
      the merged blank skeleton to `model/`; else a full parse. Each version now snapshots its post-Phase-1 skeleton
      to `versions/<id>/parse/` (`generate_full` phase-split; `snapshot_parse_model`). **Two correctness fixes found
      via real-data validation:** (1) `drop = changed ∪ affected ∪ deleted` (NOT every file the partial transitively
      saw — those were only partially parsed; merge keeps fresh ONLY for dropped files); (2) **cross-TU call
      resolution** — a partial parse can't resolve a call whose callee is defined in an UN-parsed file (the parser
      links edges only to known function definitions), so the parser now emits `model/func_keys.json`
      `{mangled→fid}` and a narrowed parse loads the **baseline's** map (via env `ANALYZER_BASELINE_FUNCKEYS`) so
      `visit_calls` resolves cross-TU edges. **Verified: narrowed model == full-parse model** on C1→C3
      (functions/globals/hashes/dataDictionary/edges/entity_files all match, 0 callsIds/calledByIds diffs). Full
      parse path unchanged (`_baseline_func_keys` empty → no-ops). All these are no-ops unless `--narrowed-parse`.
    - **M4.5 `--verify-parse` self-check — ✅ done.** `parse_merge.diff_models(narrowed, full)` (pure, edge lists
      compared as SETS since order is cosmetic) + `engine.py --verify-parse`: runs the narrowed parse, then a FULL
      parse, diffs the two models, logs every mismatch loudly + records a manifest warning, and **uses the full
      parse as the source of truth** (a verify run is slow but always safe). This is the gate to make narrowed the
      default. **It immediately earned its keep:** on C1→C3 it flagged `hashes[UNIT]` — `typedef int UNIT;` is
      defined in **5 files**, all keyed by the bare name, so the parse-order-dependent winner differed between
      narrowed (an affected TU) and full (the baseline's stable winner). **Fix:** `merge_model` resolves a shared
      entity's file from the BASELINE (its canonical, stable location), so a multiply-defined entity sticks with the
      baseline winner — matching a full parse. Re-verified: **narrowed == full (set-equal), 0 mismatches.** +5 diff
      unit tests.
    - **M4.6 narrowed-parse hardening — ✅ done.** (1) **Virtual re-spread:** the parser emits fid-level
      `model/override_pairs.json` (from `get_overridden_cursors`); a narrowed parse loads the baseline's + the
      partial's and `merge_model._recompute_call_edges` re-runs `spread_virtual_families` (D7) so a re-parsed
      dispatcher links to ALL overrides incl. those in un-parsed files. (2) **Parse-fingerprint gate:** the parser
      writes `metadata.parseFingerprint = parse_fingerprint(CLANG_ARGS, std, libclang lib)`; `_try_narrowed_parse`
      compares the partial's value to the baseline's and falls back to a full parse on any clang-flag/std/toolchain
      change. (3) **Windows path-case:** `parse_merge._norm` case-folds repo paths on `nt` so git-diff paths and
      `entity_files` line up in the drop set. (Header add/delete was already covered by M4.1 `full_reparse_reason`.)
      Re-validated on C1→C3 after all three: **`--verify-parse` → narrowed == full (set-equal), 0 mismatches.**
      *Remaining polish (non-blocking): exact list-ORDER byte-identity (set-equal is the correctness bar — order
      doesn't affect any consumer) and a perf measurement on a large repo (the O(diff) win doesn't show on SampleCpp).*
    - **M4 COMPLETE (M4.0–M4.6).** Narrowed parse is opt-in (`--narrowed-parse`), validated byte-equal (set-level)
      to a full parse via `--verify-parse`. Flip to default once the self-check is clean across a diff matrix on a
      real (large) repo.
      **M4.4 KEY FINDING — narrowed parse must merge against a PARSER-LEVEL snapshot, not the baseline's FINAL
      model.** Reason: the baseline final model has LLM descriptions; if the merge keeps those for unaffected files,
      the impacted *dependents* (unaffected files that call a changed fn) would carry a description → Phase 2 skips
      them → **stale**. So the merge must produce a parser-level model (source-comment descriptions, no LLM fields),
      identical to a full-parse Phase-1 output, so the engine's EXISTING classify→impact→carry_forward→Phase-2 flow
      runs unchanged. **M4.4 steps:** (1) `engine/core/group_planner.py` + `run.py`: thread a new `--only-files <list>`
      through to `parser.py` (Phase-1 parses only those TUs); (2) a `_snapshot_parse_model(model_dir, version_dir)`
      helper that copies the 8 parser artifacts (functions/globalVariables/dataDictionary/hashes/edges/tu_includes/
      entity_files/metadata) to `versions/<id>/parse/` — captured after Phase 1 in BOTH paths (phase-split
      `generate_full` into `--to-phase 1` → snapshot → `--from-phase 2`); (3) `engine.generate_incremental(narrowed_parse=…)`:
      if opt-in AND baseline has `parse/` + `tu_includes.json` AND `affected.full_reparse_reason(...)` is None →
      compute `affected_tus` from the diff ∩ baseline `tu_includes`, run `--only-files`, `parse_merge.merge_model(
      baseline_parse, partial, drop_files=affected ∪ deleted ∪ fresh-entity-files)`, write merged → `model/`,
      snapshot it to `versions/<id>/parse/`; else full parse (today's path). Then the existing flow is untouched.
      Default = full parse (zero risk); flip only after the M4.5 self-check is byte-identical across a diff matrix.
  - *Remaining (after M4):* **M5** Postgres migration, **M6** object storage/dedup — deferred to the production phase.
    (Recipe-fingerprint invalidation **dropped by decision** — fingerprint is content-only; multi-doc zip shipped in M1.3b.)
  - **PERF M-A…M-D — ✅ DONE (Phase 3/4 + Phase 2 caching; full design in doc 04 §12).** LLM-on profiling showed a
    ~85s fixed floor that did NOT scale with change size (a 0-change incremental still cost ~88s): the floor lived
    in Phase 4 (DOCX) + Phase 2 (derive), neither incremental. Narrowed parse only touches Phase 1 (~10%). All caches
    content-addressed, persist across version runs.
    - **M-A content-addressed Mermaid→PNG cache.** `utils.render_mermaid_cached()` (key `sha256(mermaid+scale+puppeteer)`
      at `<root>/.mmdc_cache/`); routes docx component diagrams (Phase 4, the ~46s win) + the Phase-3 flowchart/unit
      renders through it. `mmdc` runs once per unique diagram; graceful fallback on any cache error. +3 tests.
    - **M-B export-time description cache.** `get_struct_description`/`get_unit_description` cached via `EntityCache`
      (`.flowchart_cache/aux_descriptions`, honours `cacheVersion`). With M-A, an unchanged component's Phase 4 =
      0 renders + 0 LLM calls — no baseline-`.docx` editing (re-assembly is cheap). +3 tests.
    - **M-C Phase-2 derive scoping.** (1) behaviour-name LLM calls (~23s, scoped but uncached) now cached (keyed by
      prompt); (2) `enrich_functions_rich` computes the work set FIRST and returns BEFORE building the O(model) RepoMap
      infra (~20s) when nothing needs a description. +2 tests.
    - **M-D true `--no-llm`.** `generate.apply_no_llm(cfg)` sets `llm.descriptions=False`+`behaviourNames=False`; DOCX
      unit summary gated on descriptions; `flowcharts.py` passes `--no-llm` → flowchart engine `_NullLlmClient` (empty
      response → fallback labels). Fully LLM-free deterministic run; verified e2e on a no-gateway host (0 LLM calls,
      full gen in ~14s). +2 tests. *(Keeps `--no-llm-summarize` as the granular knob.)*
    - **Net:** a re-run / unchanged-component / fully-cached incremental drops Phase 2 + Phase 4 from ~93s toward
      near-0; the first run of a NEW diff still pays the real cost for CHANGED entities only (correct). Caches at
      `<project_root>/.mmdc_cache` + `.flowchart_cache/aux_descriptions`.
- **Next concrete step:** **M4 + PERF M-A…M-D complete.** The incremental feature (engine, stores, cross-version
  reuse, narrowed parse + `--verify-parse`, and Phase 2/3/4 caching) is implemented. Remaining are *validation /
  graduation*, not new milestones: (1) **LLM-on timing validation on the office machine** — confirm Phase 2 + Phase 4
  collapse on a re-run (the M-A…M-D payoff) and that `--no-llm` gives 0 LLM calls; (2) run `--verify-parse` across a
  diff matrix on a real (large) repo, then flip narrowed parse opt-in → default; (3) a perf measurement on that repo.
  Optional: scope the RepoMap build to the impact neighbourhood (cut the ~20s even for a few changed); exact list-ORDER
  byte-identity (set-equal is the correctness bar today). After that: **M5** Postgres, **M6** object storage/dedup.
- **Testing convention:** `_probe_*.py` (run once, delete) + end-to-end on `SampleCppProject`; run **LLM off**
  to validate the logic (hashing / diff / impact / reuse counts), LLM on only for the time-savings payoff.

### 23.6 Analyzer changes M1/M2 will make
`run.py` (`--config`/`ANALYZER_CONFIG`, `--incremental`); `core/config.py` (honor `ANALYZER_CONFIG`);
`parser.py` (partial-parse; entity hashing; slim type/macro index); `model_deriver.py` (incremental mode;
extend `EntityCache`); `views/flowcharts.py` (restrict the engine's functions file to the impact set; the
`engine/flowchart/` engine itself is unchanged); new `engine/incremental/` — incl. `stores.py` (D9 interface:
`VersionStore`/`ReuseIndex`/`HashStore`/`EdgeStore`, JSON-file impl now, Postgres later) that all version /
hash / edge / reuse-index access goes through.

### 23.7 Key `version4` commits (this session)
`a2edee1` bring-over backend+docs · `3498153` PROJECT_CONTEXT merge · `1cf4eb5` backend→layers/component ·
`082ec8b` backend doc corrections · `a74a560` **git_service** · `4651fe9` + `d1ee2bd` + `98b2ce1` doc 04
(incremental approach → slim edges + pointer index) · `8ea45a2` doc 05 (UI API spec). Branch is pushed to
`origin/version4`.

---

