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
| IN-5 | Resuming at **Phase 3** on a machine that did not run Phase 2 loses `knowledge_base.json` (Phase 2 -> Phase 3 hand-off, not restored by `hydrate_model`). The flowchart engine degrades to less context for its node labels rather than failing. Low priority — only affects a cross-machine `--from-phase 3` | issue | open | C4 analysis |

## SWE.3 — detailed design
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| S3-1 | Per-layer macros + JSON macro input | issue | done 2026-08-07 | §16 |
| S3-2 | Flowchart: if/else depiction | issue | open | 3.8 (repro) |
| S3-3 | Flowchart: bending / overlapping edges | issue | open | 3.9 |
| S3-4 | Dynamic-behaviour issue | issue | blocked | 3.10 (repro) |
| S3-5 | Header inline fn (sibling `.cpp` exists) shows in interface table but gets no flowchart | issue | open | PROJECT_CONTEXT.md |
| S3-7 | A global earns its interface row by MARKING only; a function has to be called from another unit. Same rule for globals = a global needs a reader/writer outside its own unit. Measured on the sample: **0 of 16** published globals qualify (11 touched only by their own unit, 5 by nothing), so it would empty the global rows from every table. Same trap as the function rule -- "no user outside this unit" and "no user this run could see" are one thing to the tool and opposite things in fact (ISR, pointer, assembly, unparsed layer). Needs measuring on the client project, where globals genuinely are shared, before it is safe | enhance | open | SWE3_WIKI N.1.5, PROJECT_CONTEXT Risk 8 |
| S3-8 | A file-scope `static` or `const` global publishes as an interface though internal linkage means no other unit CAN reach it. Unlike S3-7 this needs no analysis to be sure -- one clause in `_global_visibility` (`storage_class == STATIC` -> private). `static` FUNCTIONS are already excluded, but by accident: every caller is necessarily in their own unit | issue | open | engine/parser.py, Risk 8 |
| S3-9 | ~~`union U {...};` and `using T = int;` reach the data dictionary NEVER~~ — **done 2026-09-23.** UNION_DECL joins the struct/class branch (a union’s members are FIELD_DECLs too, only `kind` differs); TYPE_ALIAS_DECL records as a typedef, since the two declare the same thing. The view’s snippet guard also had to accept `using` and `class`/`union`, or the row was dropped after being recorded | issue | **done 2026-09-23** | engine/parser.py, views/unit_headers.py |
| S3-10 | Unit header rows: a symbol declared in a unit's own files is listed whether or not the unit uses it (the usage test applies only to symbols lent from an orphan header). Client said "of the unit AND used by the unit", which may mean both conditions | input | open | SWE3_WIKI N.1.4 |
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

## SWE.2 — architecture
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| S2-1 | Feature-list derivation (§2.2.1) | enhance | open | SWE2_PLAN |
| S2-2 | Resource / Config / Calibration data | input | blocked | SWE2_PLAN |
