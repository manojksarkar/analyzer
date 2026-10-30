# Backlog

> **Every open item, one table per area** — the one list of open work (the forward plans that lived in
> `engine/`, `api/` and `web-app/` `PLAN.md` are folded in here, 2026-10-30). A done item leaves its
> table; the project-context history keeps it. Leadership view: [planning/ROADMAP.md](planning/ROADMAP.md).
> Longer text: [Details](#details), by id.
>
> **Type** `issue` wrong today · `enhance` better later · `input` needs outside input · `debt` · `perf` ·
> `risk` — **Pri** P1–P3, `—` not set — **Effort** S ≤ 1 day · M 2–4 days · L a week or more, `—` not
> estimated — **Status** `open` · `blocked` · `decide` (waits on an answer) · `deferred` · `parked` ·
> `to verify` (done; waits on the review's check — only the review marks an item fixed).

## Next work (listed 2026-10-29, priorities 2026-10-30)

Order: NW-2 → NW-6 → NW-5 → NW-8 → NW-7 → NW-1 → NW-3 (priority, then dependency, then the smaller one). NW-4 done 2026-10-31.

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| NW-1 | Pause and resume a run within a phase; then pause by itself after N LLM failures in a row | enhance | P2 | L | — | open | `pipeline_runner.py`, `core/progress.py`, `llm_core/client.py` |
| NW-2 | Approve a document only when its base document is reviewed | enhance | P1 | S–M | what "base" means | decide | `review_workflow.py` `approve()` |
| NW-3 | Fresh run (no baseline) for any commit, from the web | enhance | P3 | S | — | open | `RunAnalysisModal.tsx`, `routes/jobs.py` `mode` |
| NW-5 | Configurable output path and workspace root (a movable installation) | enhance | P1 | M–L | — | open | `core/paths.py`, `api/services/settings.py` |
| NW-6 | Edit a document's text from the compare view | enhance | P1 | M | — | open | `pages/ComparePage/`, `routes/compare.py` |
| NW-7 | The function's source beside its flowchart, for review | enhance | P2 | M | — | open | `pages/DocumentInspectorPage/`, a new API route |
| NW-8 | Parse workers and several LLM calls at once as the default | enhance | P2 | S | a review-site run with them on; LG-2 | open | `core/config.py` `speedup_settings` |

## Logs and LLM

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| LG-1 | Full logs: every request, parsed file, LLM call and command in the log files, with thread, time and outcome; one run's log as text (`analyzer.py logs`); UI unchanged | enhance | — | S–M | — | open | `logging_setup.py`, `request_log.py`, `tu_prefetch.py`, `client.py` |
| LG-2 | The struct-description prompt has no cap (name + whole field list) | issue | — | S | — | open | `llm_enrichment.py` `get_struct_description` |

## Shared

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| SH-1 | Requirements / linked work items source (Polarion / SWE.1) | input | — | — | the source | blocked | SWE.2, SWE.4 |
| SH-4 | An array global (`int[6]`) reports range `NA` | enhance | — | — | a rule | open | `utils.py` |
| SH-5 | Type hashes are bare names while the dictionary is keyed by layer | issue | — | — | — | open | `parser.py`, `incremental/impact.py` |
| SH-7 | Nothing writes `versions.commit_sha` after a generate | issue | — | — | — | open | `core/model_store.py` |
| SH-8 | A flowchart over PIL's 179M px is left unsliced, silently | issue | — | — | — | open | `views/flowcharts.py` `_maybe_slice_tall_png` |

## Incremental reuse

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| IN-4 | A global with more than 5 readers / writers is regenerated more than needed | perf | — | — | a real project with such globals | open | `llm_enrichment.py` `enrich_globals_rich` |
| IN-5 | A Phase 3 resume on another machine has no `knowledge_base.json` | issue | — | — | — | open | `hydrate_model` |
| IN-6 | An incremental run misses a new function's callers in unchanged files | issue | — | — | — | open | narrowed parse |

## SWE.3

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| S3-2 | Flowchart: if / else drawing | issue | — | — | a repro (3.8) | open | `engine/flowchart/` |
| S3-3 | Flowchart: bending, overlapping edges (3.9) | issue | — | — | — | open | `engine/flowchart/` |
| S3-4 | Dynamic-behaviour issue | issue | — | — | a repro (3.10) | blocked | `behaviour_diagram/` |
| S3-5 | A header inline function with a sibling `.cpp` has a row but no flowchart | issue | — | — | — | open | — |
| S3-6 | The flowchart Layer-2 test counts Mermaid shapes; the output is DOT | debt | — | S | — | open | `tests/unit/test_cfg_topo.py` |
| S3-10 | Unit header rows: listed whether or not the unit uses the symbol | input | — | — | the review's answer | decide | SWE3_WIKI N.1.4 |
| S3-11 | A Dynamic Behaviour row carries the wrong caller | issue | — | — | — | open | `views/behaviour_diagram.py`, `behaviour_diagram/selector.py` |

## SWE.3 — review round 1 (received 2026-09-23; in develop)

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| RV-1 | Writes to a class static member: direction, and the member in unit headers | issue | — | — | the review's check | to verify | `parser.py` |
| RV-3 | Static design container diagram too big for the page | issue | — | — | the review's check | to verify | `docx_exporter.py` `_fit_picture_width` |
| RV-4 | An orphan-header enum listed in every unit that uses the header | issue | — | — | the review's check | to verify | `views/unit_headers.py` |
| RV-5 | An orphan-header function counted as another unit's | issue | — | — | the review's check | to verify | `model_deriver.py` `_unit_of` |
| RV-6 | Unit diagram: the unit's In/Out globals inside the unit, no edges | issue | — | — | the review's check | to verify | `views/unit_diagrams.py` |
| RV-7 | Struct / class missing from unit headers | issue | — | — | the review's check | to verify | `views/unit_headers.py` |

## SWE.4 and UT export

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| S4-1 | Table B metadata: Alias Test ID · Risk · Test Method · Test Environment · Linked Work Items | input | — | — | SH-1 | blocked | SWE4_WIKI Table B |
| S4-2 | §3 Code Metric / Coding Rule / Test Coverage | input | — | — | a metrics / coverage source | open | SWE4_WIKI |
| S4-3 | Equivalence Class and Boundary Value analysis (today: Analysis of Requirements only) | enhance | — | — | — | deferred | `views/test_specs.py` |
| S4-4 | `tools/swe4_audit.py` reads `model/*.json`, which no longer exists | debt | — | S | — | open | `tools/swe4_audit.py` |
| UE-1 | Precise test cases: one case per path, input values, structural path conditions | enhance | — | — | `feat/ut-export` (partly there) | open | UT_EXPORT_SPEC REQ-UE-04 |
| UE-2 | Format questions: `CoreType`, the `Macros` split, `format_version`, one file or two, the id scheme, a dynamic spec's steps | input | — | — | the target format's owner | decide | UT_EXPORT_SPEC |
| UE-3 | Global linkage (`static` vs `extern`) for the UT export | enhance | — | — | — | open | `parser.py` |

## Views — each view belongs to one document (agreed 2026-09-25, parked)

> A run ignores the views of a document it is not writing; a view that is on builds only the part it needs
> of a view that is off; the switches stay in the config.

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| VW-1 | A view belongs to one document; a run ignores the other document's views | enhance | — | — | config shape: `views.swe3` / `views.swe4` or flat | parked | `views/registry.py` `DOC_TYPE_VIEWS` |
| VW-2 | Views declare what they need; the runner builds only that part | debt | — | — | — | parked | `views/__init__.py`, `views/test_steps.py` |
| VW-3 | Split `testSpecs`: `functionSteps` / `dynamicSteps` fill the slow columns | enhance | — | — | the names | parked | `views/test_specs.py` |
| VW-4 | Remove `functionTestSpecs` / `dynamicBehaviourSpecs` | debt | — | — | — | parked | `config.defaults.json` |
| VW-5 | An SWE.4 switch narrows the SWE.3 flowcharts, without a warning | issue | — | — | VW-4 | parked | `views/flowcharts.py` `_spec_scope_function_ids` |
| VW-6 | `"utExport": false` is ignored under `--doc-type swe4` / `all` | issue | — | S | — | parked | `views/ut_export.py` |
| VW-7 | `generate` defaults to `--doc-type all` (CLI only) | enhance | — | — | — | parked | `analyzer.py` |
| VW-8 | Pre-parse summary: the views on or off, and what is built only because another view needs it | enhance | — | — | — | parked | `incremental/report.py` |
| VW-9 | `config.defaults.json` ships the development profile | enhance | — | — | complete or fast as the default | parked | `config.defaults.json` |

## Review & update

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| RU-1 | `Map` and `Map2` share one interface-id count | issue | — | — | the develop owner | decide | `model_deriver.py` `_iface_scope_key` |
| RU-2 | A function called only from another layer reads as private in a group run | issue | — | — | the develop owner | decide | SWE3_WIKI, `review/catalog.py` |
| RU-3 | The default `filterMode` draws few behaviour rows | enhance | — | — | the develop owner | decide | `behaviour_diagram/generator.py` |
| RU-4 | mmdc hung once for 61 min on one unit diagram | issue | — | — | — | open | `utils.py` `_run_mmdc` |
| RU-5 | Unit and struct descriptions generated in Phase 2 and stored | debt | — | — | the develop owner | decide | `model_deriver.py` |
| RU-6 | doccheck's pair check reads calls from reviewer-editable bullets | issue | — | — | the develop owner | decide | `tools/doccheck/pairing.py` |
| RU-7 | Edit mode gaps: an orphaned correction cannot be deleted, no bulk write, SWE.4 read-only | enhance | — | — | — | open | REVIEW_UPDATE_API_SPEC §17 |
| RU-8 | Small web gaps: `shownIn` unused, R8 `dot` fallback unused, no history for label corrections, `outline.ts` splits keys by prefix | debt | — | — | — | open | `pages/DocumentInspectorPage/` |
| RU-9 | A huge document's render payload carries every flowchart's DOT | perf | — | — | a measure on a review-site document | open | `api/services/doc_render.py` |
| RF-2 | Flowchart pictures: 50 renders per capture, copied baseline PNGs, renders after the job is done, not carried | issue | — | — | — | open | `review/render_queue.py`, `views/flowcharts.py` |
| RF-3 | Cross-version reuse copies human text as LLM text | issue | — | — | — | open | `incremental/engine.py` |
| RF-5 | A save takes two pooled connections and loads the whole model | perf | — | — | — | open | `review/override_service.py` |
| RF-7 | Unit and struct descriptions made when nothing prints them | perf | — | — | — | open | `model_deriver.py` |
| RF-8 | Upgrade-order release note (0009, 0014) | debt | — | S | — | open | `core/model_store.py` |
| RF-11 | Review docs volume and duplication | debt | — | — | — | open | `docs/` |
| RF-12 | `with TestClient(app)` runs startup on the configured database; 401 passes | issue | — | — | — | open | `tests/unit/test_review_api_contract.py` |
| RF-13 | Two racy or slow tests | issue | — | S | — | open | `tests/unit/` |
| RF-14 | About 80 source-grep checks break on renames | debt | — | — | — | open | `tests/` |
| RF-15 | Nits from the PR #70 review | debt | — | — | — | open | see details |

## Review and approval, Word files

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| RA-1 | Empty documents in the review queue | enhance | — | — | what "empty" means; hide, label or auto-approve | decide | `api/services/review_workflow.py` |
| RA-2 | Design open questions 1–4 | input | — | — | answers | decide | REVIEW_APPROVE_DESIGN |
| RA-3 | "My reviews" shows only the version on screen (`GET /reviews/mine` unused) | issue | — | S | — | open | web app |
| RA-4 | In-process re-export quirks; `/runs` answers 403 where its neighbours answer 404 | debt | — | — | — | open | `pipeline_runner.py` |
| WF-1 | `GET /jobs/{id}` has no `componentsFailed` | issue | — | S | — | open | `routes/jobs.py` |
| WF-2 | Some Word-file messages are not in the mockup | input | — | — | wording | decide | `web-app/` |
| WF-3 | A generation, resume's close or an unscoped re-export still store the whole version | issue | — | — | — | open | `engine/review/word_files.py` |
| WF-4 | While one update runs, the banner shows only that row | enhance | — | — | a design answer | decide | `ReviewBars.tsx` |
| WF-5 | Update time after each correction kind at review-site scale | perf | — | — | a measure | open | `engine/review/rewrite.py` |

## Staged generation

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| SG-1 | Web Resume button on the Components panel | enhance | — | S | — | deferred | `ComponentsPanel`, `routes/version_components.py` |
| SG-2 | The requested components' documents wait for Phase 2 on every layer | enhance | — | — | — | parked | `model_deriver.py` |
| SG-3 | Frozen code copies under `runs/` stay while their project lives (deleted with it since NW-4) | debt | — | S | — | open | `core/frozen_run.py` |
| SG-4 | A web re-export runs as the API's child and dies with it | issue | — | — | — | open | `pipeline_runner.py` `_run_reexport` |
| SG-5 | `--detach` not proved on Linux (systemd, containers) | risk | — | — | — | open | CLI_COMMANDS "A run that lasts days" |
| SG-6 | Adding a layer re-parses every layer; `--llm-summarize` re-summarises the old ones | perf | — | — | — | open | `parser.py`, `tu_includes` |

## Repositories

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| BB-1 | Bitbucket check T0 at the review site | input | — | — | the review site | blocked | BITBUCKET_SUPPORT |
| BB-2 | Bitbucket later: replace a token (T7), a CA bundle (T8), a CLI token from the environment (T9) | enhance | — | — | BB-1 | open | BITBUCKET_SUPPORT |
| BB-3 | A GitHub / GitLab token sits on git's command line (seen in the process list); Bitbucket already uses a header | issue | — | S–M | a test on a real repository | open | `git_cli._auth_url`, `incremental/clone.py` |

## Web app

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| WA-1 | Function visibility end to end: three stores, none feeding the next; "Manage" disabled | issue | — | — | where hiding lives | decide | `job_functions`, `entity_versions.is_visible`, exporter `hidden` |
| WA-2 | No user creation in the web app (CLI `analyzer.py user` only); a pending invite never becomes active | enhance | — | — | — | open | `api/routes/users.py` |
| WA-3 | Project discovery, Archive, Profile, Help, SSO, forgot password | enhance | — | — | — | open | shell |
| WA-4 | A project Settings page: architecture, build config and data dictionary cannot change after creation | enhance | — | L | — | open | `pages/` |
| WA-5 | Config import keeps the first core's files only; no `compileCommands` field | enhance | — | — | — | open | wizard |
| WA-6 | Overview: no activity log | enhance | — | — | — | open | Overview |
| WA-7 | A scoped run's version: Compare shows every other component as removed | enhance | — | — | carry the rest, or compare the scope only | decide | `routes/compare.py` |
| WA-8 | Tagging a commit makes an empty draft version | issue | — | — | should a run adopt the tag | decide | versions |
| WA-9 | Excel data dictionaries accepted, the engine reads CSV only | issue | — | S | convert on upload, or CSV only | decide | upload |
| WA-10 | Run options: `no_llm` and a data dictionary in the run dialog (`mode`: NW-3) | enhance | — | S | — | open | `RunAnalysisModal.tsx` |
| WA-11 | Duplicate project names allowed; a rename is not recorded | enhance | — | — | refuse duplicates? | decide | `routes/projects.py` |
| WA-12 | `swagger.json` behind the code | debt | — | S | — | open | `api/` |
| WA-13 | "Run analysis" banner on a model-first version; Phase 3 progress drops back per component | issue | — | — | — | open | Documents, run card |
| WA-14 | The Subbar chip does not follow an older version's document | issue | — | S | — | open | `components/shell/Subbar` |
| WA-15 | Lint debt (8 errors) | debt | — | S | — | open | `NewProjectPage`, `ProjectDetailPage`, `ui/` |
| WA-16 | UI review 2026-09-30 leftovers: #6, #20, #22–24, #34–35, #42, #43, #48–50 | debt | — | — | a check against the review list | open | `web-app/` |
| WA-17 | Mockups: only `projects-empty.html` carries the product name | debt | — | S | — | open | `docs/ui-mockups/` |
| WA-18 | Feature folders (`src/features/<domain>/`) | debt | — | — | the global vs local split settles | deferred | `ui-dev` skill |

## SWE.2

| Id | Item | Type | Pri | Effort | Waits on | Status | Where |
|---|---|---|---|---|---|---|---|
| S2-1 | Feature-list derivation (§2.2.1) | enhance | — | — | — | open | SWE2_PLAN |
| S2-2 | Resource / Config / Calibration data | input | — | — | the source | blocked | SWE2_PLAN |

---

## Details

**NW-1** Today: Cancel only; the job's `paused` status serves only `pause_after_phase1` (the run
dialog's "Pause after Phase 1" is disabled: the runner ignores it); `analyzer.py resume` carries on
Phases 3–4; Phase 2's LLM answers are cached. Doubts: survive an API restart? who may pause? release the
writer lock? auto-pause after N failures — what N? Approach: a flag checked at each item and LLM call →
a clean stop that records where; resume = the same command, the cache answers the finished items; not an
OS-level suspend.

**NW-2** Today `approve()` checks the state and the Word file only; bulk approval goes through it.
Doubts: base = the previous version's document, SWE.3 before its SWE.4, or both? "reviewed" = approved?
admin override? bulk: skip or refuse? a run with no baseline? Approach: one check in `approve()`, 409
`BASE_NOT_REVIEWED` naming the base; the web disables Approve with the reason.

**NW-3** The API takes `mode: "full"` (CLI `generate --full`), but the run dialog never sends it, and
"Compare against: None" means auto — the server picks the nearest earlier version as the baseline. So the
web cannot force a fresh run. Doubts: a typed SHA beyond the list? a commit that already has a version?
carry corrections? Approach: a "Fresh run" switch that sends `mode: "full"` and ticks every component.

**NW-5** `ANALYZER_DATA_ROOT` and `ANALYZER_WORKSPACES_DIR` move the folders (environment only), but the
database stores absolute paths (`versions.base_path`, read in about 20 places; `approved_docx_path`).
Doubts: same server or another one? Windows to Linux? Approach: two keys in `config.local.json`; paths
stored relative to their root, with a migration; `doctor` checks every stored path.

**NW-6** The compare page carries texts, not slots. Its section Edit still writes `document_sections`,
which only the fallback page reads — move it onto corrections. Doubts: the newer side only? flowchart
labels too? recompute the diff after a save? Approach: the newer side's slots in each compare row, from
the reader's payload builder; reuse `SlotText` behind Edit.

**NW-7** Each function stores its file and `startLine` / `endLine`; the workspace is a git clone; the web
view reads the model only. Doubts: old commits in a shallow clone? who may see the source? a line per box
(the stored graph has none)? Approach: an API route answering `git show <commit>:<file>`'s lines,
size-capped; a Source panel on the flowchart card.

**NW-8** Each speed-up is proved to give the same output (PIPELINE_SPEED_PLAN). Doubts: lanes stable at
the review site now the prompts are capped? `parseWorkers` against memory? several calls on one lane
against `rateLimitSeconds`? an off switch once they are the defaults (today an empty block is the old
path). Approach: after one review-site run with them on and the same output, make them the defaults.

**LG-1** Today the files take DEBUG already (`logs/run_<date>.log`, the live log), but a web run's text
copy sits inside its frozen code copy, a successful GET leaves no line, the parse has no line per file and
no line names its thread. Plan: thread, date and ms on every file line; `analyzer.py logs --version-id X
[--job J] [--out file]` from the live log; a DEBUG line per request, parsed file, LLM call (stage, lane,
thread, prompt chars, seconds, outcome) and command started (exit code). Never logged: keys, tokens,
prompt text, source code. Doubts: log polling GETs? keep a run's log past `logs.keepDays`?

**LG-2** Unit descriptions, input / output names and flowchart labels are fitted to
`llmServer.maxContextTokens`; the struct prompt is not. Approach: the fields up to the limit, then "… and
N more". Note: at 127,488 tokens (≈ 500k characters) no cap cuts anything; if the 502 lines show big
prompts, lower it to about the smallest failing size ÷ 4 × 0.8.

**SH-5** `entity_hashes` / `_type_keys` stay bare qualified names while the dictionary is layer-keyed: two
layers defining one type share a hash (the last wins), so a narrowed parse can miss a change in the
other. Needs `typeUsers` keyed by layer too — `impact_set` joins hash keys to it.

**SH-7** `--create-version` is the only writer, so `commit_sha` is NULL for most versions; `generate`
demands `--commit` and `reexport` resolves the checkout without it. Fill it in `persist_run_outcome`.

**SH-8** PIL raises above 179M px; `_maybe_slice_tall_png` catches that as "cannot open" and skips — the
picture too big to slice is the one that needs it.

**IN-4** The prompt includes the top 5 users only, so a change to the 6th still regenerates. Harmless
with 1–2 users per global; tying invalidation to the prompt's slice would be fragile.

**IN-6** Sample, project B: `3ee7fe0` → `9d4dd0f` adds `multiply` (Math/Utils.cpp); the unchanged
App/Main.cpp calls it. The incremental v1.1 publishes no Math function, a full run does. Suspect the
narrowed parse: Main.cpp's call is not re-resolved. Repro: `v1.1` vs `v1.1-full`, `analyzer_ui` project
`p9d1d0c4f`.

**S3-10** A symbol declared in a unit's own files is listed whether or not the unit uses it; the usage
test applies only to orphan-header symbols. The review said "of the unit AND used by the unit".

**S3-11** `views/behaviour_diagram.py` pairs the diagrams with the DIRECT external callers by position,
but the selector also counts callers of callers: row `coreAdd <- Cross|Hub|hubCompute` carries
runNestedFolderTests's diagram. Fix: return the caller each diagram was drawn for and key the row on it.

**RV-1 … RV-7** RV-1: a static data member is a global, `x++` and `s.f++` count as writes; the member is
listed inside its class's row. RV-3: the container diagram fits the text area. RV-4: each orphan header
has ONE owner unit that lists every used symbol. RV-5: the companion header belongs to its unit. RV-6:
the unit's published globals as boxes inside the component, no edges (REQ-UD-09). RV-7: struct, class and
union listed, nested types inside their parent.

**S4-3** Table B's Generation Method today is `Analysis of Requirements` only; Equivalence Class and
Boundary Value analysis, and input sizing for branch coverage, are the deferred pass.

**UE-1** The target's `cases` array is one object per test case; v1 emits one per function. Needs the
per-path split (`expected.returns[].step` is the bridge), input values rather than ranges, and
structural path conditions.

**RU-1 … RU-6** What to do either way: [REVIEW_UPDATE_HANDOVER §8](design/REVIEW_UPDATE_HANDOVER.md#8-waiting-on-the-develop-owner).

**RF-n** The PR #70 review's `Fn`, at `9b1f3c9`. RF-2: at most 50 renders per capture; an incremental
Phase 3 copies the baseline PNG; `_draw_pending_pictures` runs after the job is done; `render_jobs` are
not carried. RF-3: v1 corrected, v2 orphaned, v3 reverted — breaks HANDOVER §4.8. RF-5: the lock holder
can time out on a full pool; `patch_interface_tables` parses every file. RF-11: drop
`REVIEW_UPDATE_REQUIREMENTS.md`, fold the HANDOVER, trim DESIGN and API_SPEC. RF-13:
`test_render_timeout_stops_the_tree.py` racy, `test_runner_never_hangs.py` needs `slow`. RF-15:
`render_queue` without `begin_nested()` on PG; `set_entity_field` without a `project_id` filter;
`schema.py` defaults differ from 0010; 2 redundant indexes; `DB_SCHEMA.md` ER errors; `clone.py` without
`--end-of-options` and a hex check; `grant_access --all` defaults to admin; `cascade._drop_overridden`
counts orphans; `rerender` patches the first copy only; `carry_forward` keeps a stale `llm_text`;
`onboard --owner <unknown>` exits 2; `--sqlite` setup skips the column repair.

**WF-2** "Open <doc> to try again.", "Open X to update it.", "Can't tell if this Word file is up to
date.", "Checking its Word file…", "2 pictures being drawn", "Update after the run on v1.2.0 ends.", the
rename's "…keep their name until their Word files are rebuilt."
