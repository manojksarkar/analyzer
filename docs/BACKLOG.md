# Backlog

> Deferred / known items — the Phase-2 improvement list (implement broad first, fix from here).
> Leadership view: [planning/ROADMAP.md](planning/ROADMAP.md) "Remaining work". Detail: repo `PROJECT_CONTEXT.md`.
> **Type** `issue` (wrong today) · `enhance` (better later) · `input` (needs client/Polarion) · `debt` — **Status** `open` · `blocked` · `deferred`.

## Shared
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| SH-1 | Requirements / Linked Work Items source (Polarion / SWE.1) | input | blocked | SWE2 + SWE4 |
| SH-2 | Same group/component name reused across layers collides (needs layer-qualified identity) | issue | open | — |
| SH-3 | Per-layer data dictionary: layer-scoped entries + layer-aware `get_range` | issue | done 2026-08-18 | §17 |
| SH-4 | Array data range: an `int[6]` global reports `NA` (an array's range is not one interval — needs a rule, e.g. element range + length) | enhance | open | engine/utils.py |
| SH-5 | `entity_hashes` / `_type_keys` stay bare-qn while the dictionary is layer-keyed: two layers defining one type share a hash (last definition wins), so a narrowed parse can miss a change in the loser. Needs `typeUsers` keyed by layer too — `impact_set` joins hash keys to it directly. | issue | open | engine/parser.py, incremental/impact.py |

| SH-6 | ~~A full `pytest` run died at e2e setup~~ — **fixed 2026-09-21.** `_scratch_repo()` rebuilds the sample's git repo from nothing every run, so its commit is new every time and no earlier version's commit still exists to be an ancestor; `select_baseline` threw on `merge-base --is-ancestor` and every e2e test errored on setup. conftest's `generate` now passes `--full`, which dispatches to `generate_full` and never selects a baseline. There is no incremental path to exercise on a brand-new repo anyway. The orphan `e2ev2` row (DB only, no directory) is now harmless and was left alone | issue | **done 2026-09-21** | tests/conftest.py |
| SH-7 | Nothing writes `versions.commit_sha` after a successful generate (`--create-version` is the only writer), so it is NULL for most versions and stale for some. `generate` therefore demands `--commit` every run and `reexport` had to learn to resolve the checkout without it. Filling it in `persist_run_outcome` from the manifest would remove the workaround | issue | open | engine/core/model_store.py |
| SH-8 | PIL **raises** above 179M px, and `_maybe_slice_tall_png` catches that as "cannot open" and skips slicing silently — a flowchart too big to slice is exactly the one that needs it. The real 165M case sat just under the threshold | issue | open | engine/views/flowcharts.py:661 |

## Incremental reuse
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| IN-1 | ~~Globals never reused~~ — **investigated: not a defect.** A global's LLM description embeds the *descriptions* of its readers/writers (`enrich_globals_rich` pulls `fk.description` for up to 5 of each), so regenerating a using function genuinely changes the global's input and it must be regenerated. Confirmed against the sample project: each global is touched by only 1–2 functions, so a small change invalidates all of them. Untouched globals *are* reused. The report now explains the figure | issue | **closed — by design** | office run 2026-08-15 |
| IN-4 | Globals with **>5** readers/writers are over-invalidated: the prompt only includes the top 5, so a change to the 6th cannot alter the description yet still triggers regeneration. Harmless today (max 2 users in the sample) and coupling the invalidation rule to a prompt's slice size would be fragile — revisit only if a real project shows widely-shared globals | perf | open | IN-1 analysis |
| IN-2 | ~~Flowchart counts don't add up~~ — **not a defect.** `carried` is computed as `total - regenerated`, so the three can never disagree. The reported figures are consistent with a total of **15**, not 12: functions `3+12=15` (80%), flowcharts `2+13=15` (13/15 = 86% with floor division). The "12" was a transcription slip | issue | **closed — no defect** | `incremental/report.py` |
| IN-6 | An incremental run misses a new function's callers in UNCHANGED files. Sample, project B: `3ee7fe0` → `9d4dd0f` adds `multiply` to Math/Utils.cpp; App/Main.cpp (unchanged) calls it. Incremental v1.1 publishes no Math function; a full run at the same commit publishes `multiply` (Math SWE.3 + SWE.4 differ). Suspect the narrowed parse: only changed TUs re-parsed, so Main.cpp's call is not re-resolved. Repro: web runs `v1.1` vs `v1.1-full` in `analyzer_ui` project `p9d1d0c4f` | issue | open | 2026-09-30, PROJECT_CONTEXT.md |
| IN-5 | Resuming at **Phase 3** on a machine that did not run Phase 2 loses `knowledge_base.json` (Phase 2 -> Phase 3 hand-off, not restored by `hydrate_model`). The flowchart engine degrades to less context for its node labels rather than failing. Low priority — only affects a cross-machine `--from-phase 3` | issue | open | C4 analysis |

## SWE.3 — detailed design
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| S3-1 | Per-layer macros + JSON macro input | issue | done 2026-08-07 | §16 |
| S3-2 | Flowchart: if/else depiction | issue | open | 3.8 (repro) |
| S3-3 | Flowchart: bending / overlapping edges | issue | open | 3.9 |
| S3-4 | Dynamic-behaviour issue | issue | blocked | 3.10 (repro) |
| S3-5 | Header inline fn (sibling `.cpp` exists) shows in interface table but gets no flowchart | issue | open | PROJECT_CONTEXT.md |
| S3-7 | ~~A global earns its interface row by MARKING only~~ — **done 2026-09-24.** A global now needs a function in ANOTHER unit that reads or writes it, as a function needs a caller there (`_glb_used_outside`). A use through an `extern` declaration counts for the definition of that qualified name, since the model keys the read to the declaring unit. On the sample model 19 → 5 published globals; in My Sample `g_result` and `g_utilBuf` lose their rows, `g_sharedTick` (Lib reads it) and `g_utilBase` (Core reads it) keep theirs. The trap stays and is written down: "no user outside" and "no user this run could see" are one fact to the tool | issue | **done 2026-09-24** | engine/model_deriver.py, SWE3_WIKI Public vs. private |
| S3-8 | ~~A file-scope `static` or `const` global publishes as an interface~~ — **done 2026-09-24, by S3-7.** Nothing outside its file can name it, so it never has a user in another unit and never earns a row. No storage-class clause needed (`s_fileLocal` in Access/NestedTypes is now private) | issue | **done 2026-09-24** | engine/model_deriver.py, Risk 8 |
| S3-9 | ~~`union U {...};` and `using T = int;` reach the data dictionary NEVER~~ — **done 2026-09-23.** UNION_DECL joins the struct/class branch (a union’s members are FIELD_DECLs too, only `kind` differs); TYPE_ALIAS_DECL records as a typedef, since the two declare the same thing. The view’s snippet guard also had to accept `using` and `class`/`union`, or the row was dropped after being recorded | issue | **done 2026-09-23** | engine/parser.py, views/unit_headers.py |
| S3-10 | Unit header rows: a symbol declared in a unit's own files is listed whether or not the unit uses it (the usage test applies only to symbols lent from an orphan header). Client said "of the unit AND used by the unit", which may mean both conditions | input | open | SWE3_WIKI N.1.4 |
| S3-11 | Dynamic Behaviour row labelled with the wrong caller: `views/behaviour_diagram.py` pairs `generate_all_diagrams`' diagrams with the function's DIRECT external callers by position, but the selector (`selector.get_external_callers_with_component`) also counts callers of callers. Seen on the sample with `all_callers`: row `coreAdd <- Cross|Hub|hubCompute` carries runNestedFolderTests's diagram and bullets ("runNestedFolderTests calls coreAdd"), and the hubCompute diagram is left without a row. A reviewer's R6 correction lands on that mislabelled row. Fix: return the caller each diagram was drawn for, and key the row on it | issue | open | views/behaviour_diagram.py, behaviour_diagram/selector.py |
| S3-6 | Flowchart Layer-2 test stale: `_count_mermaid_shapes` counts Mermaid syntax but output is DOT; dormant (opt-in `--out-dir`) → port to count DOT `shape=` | debt | open | tests/unit/test_cfg_topo.py |

## SWE.3 — firmware-team review, round 1 (received 2026-09-23)
> Work branch `fix/swe3-review-v1`, not yet merged to `develop`. **Status** `done` = on the branch and checked on SampleCppProject, waiting for office verification · `fixed` = verified in the office; set only after that check, never by an agent · `partial` · `open` · `decide` = works to an agreed rule the review disputes.

| ID | Review item | Status | Where it stands | Ref |
|---|---|---|---|---|
| RV-1 | Writes to a class static member not detected (direction wrong); static members missing from unit headers | done | Direction: a static data member is now a global (`a532cf6`), `x++` counts as a write (`17ae2dc`), a write through a field `s.f++` is covered (`cc1827b`) → a writing function reads `In`. Unit headers: the member is listed inside its class's row; the out-of-line definition gets no row of its own (`147c4cd`, answer Q9). `In` confirmed as expected (2026-09-23) | engine/parser.py, Diag/ClassStatics |
| RV-2 | Class access specifier not captured | fixed | Methods read `cursor.access_specifier` (`7153617`), static members too (`a532cf6`); `protected` counts as private. Class rows in the unit header keep the labels as written (Q5) | parser.py `_function_visibility`, Access/AccessMatrix |
| RV-3 | Static design container diagram overscaled: it ran off the page, and the review asked for slicing | done | Fitted to the page instead (`3514698`): it scales to the text area, never above its natural size, and all unit boxes are the same width. Slicing was rejected because an edgeless diagram has no meaningful cut points. The header-dependency and unit diagrams keep a fixed 6 in width; they are not part of this item | docx_exporter.py `_fit_picture_width` |
| RV-4 | An orphan-header enum appears in every unit that uses the header | done | Confirmed (2026-09-23): it was listed in every unit that really used it, and it should be listed once, in a unit header table. Now each orphan header has ONE owner unit: the first unit by name in the header's own component that uses it, or the first using unit anywhere if none does (the ★ answer, taken as agreed). The owner lists every symbol of the header that any unit uses; the others list none. Same rule for every kind: `#define`, enum, typedef, struct/class/union and globals. The owner is chosen over the whole model, so a shared enum can sit in another group's document. A unit left with no rows reads `NA` (Lib in the sample) | views/unit_headers.py, SWE3_SPEC REQ-UH-02, SWE3_WIKI "Orphan-header symbols" |
| RV-5 | An orphan-header function counts as another unit's function in the visibility rule | done | Marked done by the user (2026-09-23). Background, from code reading: an orphan header gets a unit key of its own in `_unit_of`, so a call to or from it counts as external. `ed16832` made the same-name companion header part of its unit | model_deriver.py `_unit_of`, `_has_external_caller` |
| RV-6 | Unit diagram: show the unit's In/Out globals inside the unit, no edges | done | Every global's direction is `In/Out`, so no arrow can be drawn; each one is now a box. Decided (2026-09-23): the unit's globals that have an interface-table row, one white/grey box each, labelled with the variable name (with its class for a class static member), inside the component box, stacked above the unit in interface-ID order, no edges (after the ExceptionManager photo). The globals share an untitled inner panel with the unit, because otherwise the layout engine puts them in the left column whenever the component has other units. Incremental runs re-render a reused diagram whose text changed. REQ-UD-09 | views/unit_diagrams.py, SWE3_SPEC REQ-UD-09, SWE3_WIKI N.1.3 |
| RV-7 | Struct / class missing from unit headers | done | struct, class and union are listed (`147c4cd`), with methods as declarations and nested types inside their parent; `union` and `using` are now recorded (S3-9) | views/unit_headers.py, Access/NestedTypes |

## SWE.4 — unit test spec
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| S4-1 | Table B metadata (Alias Test ID · Risk · Test Method · Test Environment · Linked Work Items) | input | blocked | SWE4_PLAN |
| S4-2 | §3 Code Metric / Coding Rule / Test Coverage | input | open | SWE4_PLAN |

## Views — each view belongs to one document (agreed 2026-09-25, parked)
> Rules agreed: a run **ignores** the views of a document it is not writing (not checked, not generated, config left as it is; `all` = both). `flowcharts: true` = control flow + labels + images. A view that is on pulls in only the part it needs from a view that is off or ignored (`functionSteps` on + `flowcharts` off → control flow, no images). Switches stay in the config — the web app needs fast development runs too.

| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| VW-1 | A view belongs to one document; a run ignores the other document's views. Replaces the doc-type forcing, which overrides the config for `flowcharts` / `testSpecs` / `utExport`. Open: group the config as `views.swe3` / `views.swe4`, or keep it flat | enhance | open | views/registry.py `DOC_TYPE_VIEWS` |
| VW-2 | Views declare what they need; the runner builds only the needed part of an off or ignored view. Today the link is files on disk plus import order: unit specs read `flowcharts/*.json`, and a missing control flow prints "Not available" with no warning | debt | open | views/__init__.py, views/test_steps.py |
| VW-3 | Split `testSpecs`: it keeps the instant columns (no switch); new `functionSteps` / `dynamicSteps` fill Test Steps + Expected Results — the only slow part of SWE.4 (control flow + LLM labels). Off → the cells say `Not generated (views.<x> is off)`. Open: the names | enhance | open | views/test_specs.py |
| VW-4 | Remove `functionTestSpecs` / `dynamicBehaviourSpecs`: off drops the whole per-function spec (Table A + B), not one column — no use case | debt | open | config.defaults.json |
| VW-5 | An SWE.4 switch narrows the SWE.3 flowcharts: `functionTestSpecs: false` → most functions lose their flowchart; both spec switches off → no flowcharts at all, with no warning. Found by reading the code, not confirmed by a run. Goes away with VW-4 | issue | open | views/flowcharts.py `_spec_scope_function_ids` |
| VW-6 | `"utExport": false` is ignored under `--doc-type swe4` / `all`; make it a real off switch | issue | open | views/ut_export.py |
| VW-7 | `generate` defaults to `--doc-type all`, in analyzer.py only. The web app stays `swe3` until it lists SWE.4 documents — the API registers only `software_detailed_design_<group>.docx` | enhance | open | analyzer.py `--doc-type` |
| VW-8 | Pre-parse summary: the views on/off for the doc type, and what is built only because another view needs it | enhance | open | incremental/report.py |
| VW-9 | `config.defaults.json` ships the development profile (`flowcharts`, `behaviourDiagram` off) and every project inherits it. Open: complete or fast as the shipped default | enhance | open | config.defaults.json |

## Review & update — waiting on the develop owner
> Points the feature's work met in develop's area and did not settle alone. None blocked the merge (PR #70); where it had to pick, the pick is reversible. **Status** `decide` = waits on the develop owner's answer. Detail and what to do either way: [REVIEW_UPDATE_HANDOVER §8](design/REVIEW_UPDATE_HANDOVER.md#8-waiting-on-the-develop-owner).

| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| RU-1 | Units whose interface ids start the same (`Map`, `Map2` in one group) share one count so no id is printed twice (`15df7c5`) — SWE3_WIKI says `<NN>` counts within the unit, SWE3_SPEC REQ-IT-04 says the id is unique. Keep → add a `Map`/`Map2` fixture; revert → accept duplicate ids. No id changes on the sample (229/229) | issue | decide | model_deriver.py `_iface_scope_key`, SWE3_WIKI Interface ID |
| RU-2 | In a group or layer run a function called only from another layer reads as private (470d15c; S3-7's trap), so most description corrections save and print nowhere — 25 of 229 printed on the sample. R11 `shownIn` says where each text is printed. Confirm the rule is meant | issue | decide | SWE3_WIKI Public vs. private, review/catalog.py |
| RU-3 | With `views.behaviourDiagram` on, the default `views.sequenceDiagrams.filterMode` (`skip_within_unit`, absent from config.defaults.json) draws a row only for a function called from another component that calls into another unit of its own; on the sample that is the 2 `CoreGateway` rows in Sample Core (fixture added 2026-10-03), `all_callers` draws one per external caller. Related: VW-9 | enhance | decide | behaviour_diagram/generator.py, api_*.sample_behaviour.example.json |
| RU-4 | mmdc hung once for 61 min on the unit diagram of `Layer1.Diag\|ArmIntrinsics`; drew normally next run. A timeout now stops the whole process tree (`3e52f41`; `5cfc286` on v2), so a hang costs 60 s and one picture. Cause unknown | issue | open | utils.py `_run_mmdc`, core/subprocess_util.py |
| RU-5 | Unit and struct/class/union descriptions are generated in Phase 2 and stored (REQ-PRE-01), not in the exporter / unit header view; same prompts and fallbacks; one text per record (a typedef row reads its record's). Confirm | debt | decide | model_deriver.py `_enrich_unit_and_struct_descriptions`, views/unit_headers.py |
| RU-6 | doccheck v2's pair check (`66f7f97`) finds a SWE.3 call by the words "A calls B" in a Behaviour Description bullet, which the LLM writes and R6 lets a reviewer rewrite freely — a reworded bullet gives a false P1 "the specification calls X, which the design draws no arrow for". Keep the call at the front (R6 checks it) / leave it / change doccheck | issue | decide | tools/doccheck/pairing.py `_ARROW_RE`, review/override_service.py `apply_behaviour_override` |

## Review & update — follow-ups from the PR #70 review
> Found reviewing PR #70 at `9b1f3c9` and left out of it on purpose; each becomes its own ticket. `RF-n` is the review's `Fn`. Line numbers are at `9b1f3c9`: where the code has moved, find it by the symbol.

| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| RF-1 | A failure to load the corrections is swallowed, but the derivation record is still written: the LLM text is exported while R9 says up to date | issue | done 2026-10-05 -- Phase 3 leaves the views unstamped (stale) when it cannot load the corrections (2026-10-04), or when the model lacks a correction in force -- a Phase 2 `_reapply_corrections` failure (`carry_forward.corrections_missing`) | engine/run_views.py:196-220, engine/model_deriver.py:708-741 |
| RF-2 | Flowchart pictures with `views.flowcharts` on: at most 50 renders per capture; an incremental Phase 3 copies the baseline PNG for unchanged functions; `_draw_pending_pictures` runs after the DOCX is built and the job is marked done; `render_jobs` are not carried to the next version | issue | open | review/render_queue.py:115, incremental/store.py:107, views/flowcharts.py:1488-1531 |
| RF-3 | Cross-version reuse copies human text as if it were LLM text (v1 corrected, v2 orphaned, v3 reverted) -- breaks HANDOVER §4.8 | issue | open | incremental/engine.py:77, 137-175 |
| RF-4 | `setup` does not stamp `alembic_version`, so a later `alembic upgrade head` fails with DuplicateColumn; the "blocked" hint points at that same failing command | issue | done 2026-10-04 -- setup stamps the head (proved on PostgreSQL: `alembic upgrade head` then a no-op), only over no stamp or a known revision from 0006 on (2026-10-04b); alembic/env.py no longer prints the password | tools/db_setup.py:167-200 |
| RF-5 | A save uses two pooled connections, so the lock holder can time out when the pool is full; it loads all four model artifacts for one field; `patch_interface_tables` parses every file | perf | open | review/override_service.py:236, 241, 349, review/rerender.py:165 |
| RF-6 | Re-exporting a version made before the merge loses its LLM unit and struct descriptions: nothing backfills them | issue | done 2026-10-01 — `analyzer.py setup` stores them from the version's own earlier output (`review/backfill.py`) | docx_exporter.py:819, views/unit_headers.py:75-89 |
| RF-7 | Phase 2 generates unit and struct descriptions for SWE.4-only runs, for `unitHeaders: false`, and for header-only units | perf | open | model_deriver.py:1223-1290 |
| RF-8 | Upgrade-order release note: without 0009 every generate fails; an API started before 0014 answers 500 on sign-in | debt | open | core/model_store.py:507, 584, api/middleware/auth.py |
| RF-9 | Internal error text leaks: R5, R7, R9 and R10 are not wrapped in `_as_http`; `_version()` / `_connection()` sit outside the `try`; `_connection()` puts `str(exc)` in its 503 | issue | done 2026-10-04; a connection refused at `.connect()` too, through the 500 handler (2026-10-04b) | api/routes/text_overrides.py:113, 440-452, 639-641, 663-667, 693-698; api/main.py |
| RF-10 | No size limit on correction text: a 5 MB `text` was accepted | issue | done 2026-10-04; a behaviour row's bullets together (2026-10-04b) | api/routes/text_overrides.py:65-90 |
| RF-11 | Docs volume and duplication: drop `docs/REVIEW_UPDATE_REQUIREMENTS.md`, fold HANDOVER into the PR description and BACKLOG, trim DESIGN and API_SPEC | debt | open | docs/ |
| RF-12 | `with TestClient(app)` runs the app's startup on the configured database, and the test accepts 401 as a pass | issue | open | tests/unit/test_review_api_contract.py:436 |
| RF-13 | `test_render_timeout_stops_the_tree.py` is racy under load; `test_runner_never_hangs.py` needs the `slow` marker | issue | open | tests/unit/test_render_timeout_stops_the_tree.py:48, tests/unit/test_runner_never_hangs.py |
| RF-14 | About 80 source-text grep checks break on renames elsewhere -- AST or behaviour tests would hold up better; `test_project_context_fits.py` belongs in a docs-lint step, not the unit suite | debt | open | tests/ |
| RF-15 | Nits: `render_queue` uses no `begin_nested()` per job on PG; `set_entity_field` has no `project_id` filter; `schema.py` server defaults differ from 0010 for `is_orphaned` and `group_name`; 2 redundant indexes; `DB_SCHEMA.md` ER diagram errors; `clone.py` lacks `--end-of-options` and a hex check on `commit_sha`; `grant_access --all` defaults to admin and has an undefined `reviewer` role; `cascade._drop_overridden` counts orphans; `rerender` patches only the first copy; `carry_forward` keeps a stale `llm_text`; wrong docstring in `incremental/engine.py`; `_stamp_derivation` shares the capture transaction; `onboard --owner <unknown>` exits 2; `--sqlite` setup skips the column repair | debt | open | review/render_queue.py, api/db/postgres/schema.py, clone.py:199, review/carry_forward.py:324, incremental/engine.py:550-557, tools/grant_access.py |

## Staged generation — long runs (2026-10-02)
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| SG-1 | Web **Resume** button on the Components panel. The route (`POST …/versions/{vid}/resume`) and `resume_action` exist; until then `analyzer.py resume --detach` on the server, which also finishes the web job | enhance | deferred (user) | web-app ComponentsPanel, api/routes/version_components.py |
| SG-2 | A run's 7 components get documents only after Phase 2 has described every function of its layers — order the descriptions by the requested components, or describe the rest at `export` | enhance | parked (user) | engine/model_deriver.py |
| SG-3 | Frozen code copies under `runs/` are never deleted (~10 MB per web run); a cleanup must not follow the copy's `node_modules` junction | debt | open | engine/core/frozen_run.py |
| SG-4 | A web re-export still runs as the API's child and dies with it | issue | open | api/services/pipeline_runner.py `_run_reexport` |
| SG-5 | `--detach` not proved on Linux; an API under systemd (default `KillMode=control-group`) or in a restarted container takes its background runs down | risk | open | docs/CLI_COMMANDS.md "A run that lasts days" |

## SWE.2 — architecture
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| S2-1 | Feature-list derivation (§2.2.1) | enhance | open | SWE2_PLAN |
| S2-2 | Resource / Config / Calibration data | input | blocked | SWE2_PLAN |
