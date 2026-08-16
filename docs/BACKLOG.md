# Backlog

> Deferred / known items — the Phase-2 improvement list (implement broad first, fix from here).
> Leadership view: [planning/ROADMAP.md](planning/ROADMAP.md) "Remaining work". Detail: repo `PROJECT_CONTEXT.md`.
> **Type** `issue` (wrong today) · `enhance` (better later) · `input` (needs client/Polarion) · `debt` — **Status** `open` · `blocked` · `deferred`.

## Shared
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| SH-1 | Requirements / Linked Work Items source (Polarion / SWE.1) | input | blocked | SWE2 + SWE4 |
| SH-2 | Same group/component name reused across layers collides (needs layer-qualified identity) | issue | open | — |
| SH-3 | Gate updated data dictionary + integrate for correctness | enhance | open | engine/config/data_dictionary.csv |

## Incremental reuse
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| IN-1 | ~~Globals never reused~~ — **investigated: not a defect.** A global's LLM description embeds the *descriptions* of its readers/writers (`enrich_globals_rich` pulls `fk.description` for up to 5 of each), so regenerating a using function genuinely changes the global's input and it must be regenerated. Confirmed against the sample project: each global is touched by only 1–2 functions, so a small change invalidates all of them. Untouched globals *are* reused. The report now explains the figure | issue | **closed — by design** | office run 2026-08-15 |
| IN-4 | Globals with **>5** readers/writers are over-invalidated: the prompt only includes the top 5, so a change to the 6th cannot alter the description yet still triggers regeneration. Harmless today (max 2 users in the sample) and coupling the invalidation rule to a prompt's slice size would be fragile — revisit only if a real project shows widely-shared globals | perf | open | IN-1 analysis |
| IN-2 | Flowchart counts don't add up in the report: `regenerated 2 / 12 function(s) -> carried 13` (2+13 > 12) — the regenerated/total/carried figures appear to count different sets (functions vs files) | issue | open | `incremental/report.py` |

## SWE.3 — detailed design
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| S3-1 | Per-layer macros (`--macros` is one global CSV) | issue | open | §16 |
| S3-2 | Flowchart: if/else depiction | issue | open | 3.8 (repro) |
| S3-3 | Flowchart: bending / overlapping edges | issue | open | 3.9 |
| S3-4 | Dynamic-behaviour issue | issue | blocked | 3.10 (repro) |
| S3-5 | Header inline fn (sibling `.cpp` exists) shows in interface table but gets no flowchart | issue | open | PROJECT_CONTEXT.md |
| S3-6 | Flowchart Layer-2 test stale: `_count_mermaid_shapes` counts Mermaid syntax but output is DOT; dormant (opt-in `--out-dir`) → port to count DOT `shape=` | debt | open | tests/unit/test_cfg_topo.py |

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
