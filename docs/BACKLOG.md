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
| SH-4 | Array data range: an `int[6]` global reports `NA` (an array's range is not one interval — needs a rule, e.g. element range + length) | enhance | open | engine/utils.py |

## SWE.3 — detailed design
| ID | Item | Type | Status | Ref |
|---|---|---|---|---|
| S3-1 | Per-layer macros + JSON macro input | issue | done 2026-08-07 | §16 |
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
