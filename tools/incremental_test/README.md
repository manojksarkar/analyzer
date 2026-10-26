# incremental_test — incremental generation, end to end through the REST API

An incremental generation builds a new version on an earlier one and regenerates only what a
change reaches. It must give **the same Word files as a full generation** of the same commit: the
earlier version saves time, it never changes a document
([doc 04](../../docs/production-redesign/04-incremental-changes-implementation.md) §6, §11.1).

This script checks exactly that. It makes a project of its own on a git copy of SampleCppProject and
generates its first commit in full (the base version). Then each scenario changes the C++ code as a
developer would, on a branch of its own, and generates that commit twice — incrementally and in full —
and compares the two versions' Word files:

- **what they say** — [doccheck](../doccheck/README.md) reads both into units, interface rows, behaviour
  diagrams and test cases: no difference at P1 or P2;
- **word for word** — the whole text, version names and dates aside.

It also checks which version each was built on, and what it regenerated and reused. Everything goes
through the REST API.

> **Never against the review site's database or API.** Use a test API on a test database.

## Run it

```bash
# 1. your config -- config.json is git-ignored: it holds a password
cp tools/incremental_test/config.example.json tools/incremental_test/config.json
#    fill in: server.base_url, email, password (an admin)
#    sample.source_dir: your SampleCppProject copy (or leave empty for the repository's)
#    sample.repo_dir: where the test's git copies go -- inside repositories.localRoots when the
#    server sets them (the script checks, and prints the line to add)

# 2. the API running, on the test database
python -m uvicorn api.main:app --port 8000

# 3. run
python tools/incremental_test/incremental_test.py --mode normal
python tools/incremental_test/incremental_test.py --mode complex
```

Run it from the repository, on the API's machine. Options as in the job scheduling test: `--list`,
`--only I02,X01`, `--skip X11`, `--yes`, `--keep`, `--log-dir DIR` (where the Word files are kept).

| `--mode` | The changes | Time, without the LLM |
|---|---|---|
| `normal` | I01–I10 — no real change, a body, a new function, a deleted one, a type, globals, a shared header's type and macro, another group's callers, a chain of versions | about an hour |
| `complex` | X01–X13 — the narrowed parse on and off, a header added and deleted, a file deleted and renamed, a function moved, a revert, a baseline that is not an ancestor, no ancestor at all, a reviewer's correction carried and orphaned, the LLM (needs an LLM server), several changes at once, a smaller scope | about an hour, plus the LLM's runs |
| `all` | both | |

## The report

On the terminal, as it goes: each scenario, its steps, the jobs as they run, and every check — `PASS`,
`FAIL`, `WARN` or `SKIP`. When two versions' Word files differ it prints, per document, the doccheck
findings and the first words that differ, and keeps both versions' Word files in the log folder
(`documents/<version id>/`) to open side by side. At the end: each scenario, and each requirement
(`INC-01`…`INC-18`) with the scenarios that showed it. Each run also writes
`incremental_test_report_<mode>_<date-time>.md` and `.json`.

A `WARN` on "regenerated / reused" means the counts look wrong while the documents are still right —
worth a look, not a broken document. A `FAIL` on "the same Word files" is the bug this tool hunts:
the incremental version says something a full generation does not.

## What it leaves

The test project and its versions (unless `cleanup.delete_projects`), the sample's git copy, and the
Word files it compared. It shares its machinery with `tools/job_scheduling_test/`.
