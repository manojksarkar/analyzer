# Document render fixtures

A **curated, committed snapshot** of real analyzer output (`output/<group>/`), used by
`GET /projects/{id}/documents/{doc_id}/render` and the diagram asset route.

Why this exists: the live `output/` directory is **gitignored**, machine-specific, tied to one
manual `SampleCppProject` run, and is **not** produced by the (mock) API. Reading it at request
time is unreliable, so we snapshot a small representative slice here instead — deterministic,
portable, version-controlled.

Each `<Group>/` mirrors the analyzer layout:

```
<Group>/
  interface_tables.json                 # real interface data (Interfaces tables)
  unit_diagrams/<Comp>_<Unit>.png|.mmd
  flowcharts/<Unit>_<fn>.png            # per-function CFGs (png only — no .mmd upstream)
  component_container_diagrams/<Comp>.png|.mmd
  component_header_dependency_diagrams/<Comp>.png|.mmd
```

Snapshot: `Access` + `Diag` (complete), `Full` (interface tables + unit/component diagrams +
first 8 flowcharts). `behaviour_diagrams/` is intentionally omitted (long, special-char names).

To refresh: re-run the analyzer, then re-copy the desired groups here. The render endpoint
falls back to a synthesized payload for any document whose `group` has no fixture folder.
