# Live-database tests

Read a REAL project's rows and assert what must be true of them. Nothing writes: every
connection is opened with `connect()`, never `begin()`.

```
python -m pytest tests/live --project-id <your-project> -v
python -m pytest tests/live --project-id P --live-versions v5,v7 -v
python -m pytest tests/live --project-id P -v -k hash        # one area while chasing it
```

Without `--project-id` every test skips, so a normal `pytest tests/unit tests/live` run is
unaffected.

Each test that takes `vid` runs once per version, so a failure names the version in its id:

```
FAILED test_change_detection.py::TestHashesExist::test_every_real_function_has_a_source_hash[v1]
```

## What each module asserts

| module | question |
|---|---|
| `test_change_detection.py` | can an edit be detected at all — hashes present, able to move, and surviving from Phase 1's own snapshot into the rows |
| `test_storage_integrity.py` | is the database self-consistent — every blob hashes to its content_hash, no dangling pointers, no NULs, no entity leaking in from another project |
| `test_model_shape.py` | does every function with a payload carry what the document reads — file, line range, component, unit, visibility, unique interface id |
| `test_incremental.py` | the cross-version invariants — baseline is a real ancestor, a changed hash produced a changed flowchart, the graph and the picture came from one version |

Hash-only rows (a `source_hash` and no payload) are excluded from the model-shape checks:
`persist_bare_entities` writes them deliberately for a hashed entity outside the model, and
auditing them for a file or a component produced 2818 spurious failures once already.

## Reporting a failure

Paste the failure block. It carries names, paths, hashes and counts — no source code, no
doc comments and no LLM-generated text, so a client codebase can be tested and the result
shared.

## Verified against fixtures, not just run

A `broken` project carrying one instance of each real defect fails 15 of these; a `clean`
one passes. A test that cannot fail proves nothing.
