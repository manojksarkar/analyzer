# Running the analyzer from the command line

Every command below was run against this branch before being written down. Paths assume you
start at the repo root (`analyzer/`), on Windows with PowerShell or Git Bash.

The database is the **default**. You do not pass a flag to get it.

---

## 0. One-time setup

```bash
python tools\db_setup.py          # create/upgrade the schema (safe to re-run)
python tools\verify_db_sync.py    # confirms the model round-trips
python tools\doctor.py            # libclang, node, mmdc, Graphviz
python tools\check_llm.py         # is the LLM gateway answering?
```

`db_setup.py` reads the `db` section of `engine/config/config.local.json`. Run it after every
`git pull` — a pull can bring a new migration, and a missing one shows up as a feature that
quietly does nothing.

---

## 1. The thing you probably want: generate from a C++ checkout

The engine is built around **projects and versions**, not loose directories, because reuse
between runs is the whole point. Two things must exist before a CLI run:

1. a **project record**, and
2. a **`versions` row** — the API reserves this at job start, and `PgStore` never creates one.

Without the row the run stops with a clear message rather than writing a version that is not
there. Create both once:

```sql
-- psql, or any client pointed at the same database
INSERT INTO projects (id, name, repo_url, default_branch, created_at)
VALUES ('myproj', 'My Project', '', 'main', now());

INSERT INTO versions (id, project_id, version, commit_sha, branch, status, created_at)
VALUES ('v1', 'myproj', 'v1', '<full-40-char-sha>', 'main', 'in_review', now());
```

Then put the project's config where the engine looks for it:

```
workspaces/myproj/config.json          # layers, views, llm — copied from engine/config/config.defaults.json and edited
workspaces/myproj/<sha[:16]>/          # the checkout (or let --repo-url clone it)
```

### First run — full generation

```bash
cd engine
python -m incremental.generate ^
    --project-id myproj ^
    --branch main ^
    --commit <full-40-char-sha> ^
    --version-id v1 ^
    --scope project
```

Add `--repo-url <clone-url>` if the checkout is not already there.
Add `--no-llm` for a fast, deterministic, LLM-free run.

### Second run — incremental

Reserve `v2` first (same INSERT, new commit), then:

```bash
python -m incremental.engine ^
    --project-id myproj ^
    --branch main ^
    --commit <second-sha> ^
    --version-id v2 ^
    --scope project
```

It picks the nearest ancestor version as its baseline by itself. `--base-version-id v1` forces
a specific one.

**Narrowed parse is ON by default** — only changed translation units are re-parsed.
`--no-narrowed-parse` forces a full re-parse; `--verify-parse` runs both and diffs them.

---

## 2. Narrowing what gets generated

```bash
--scope project                    # everything (default)
--scope layer:App                  # one layer
--scope group:Support              # one group
--scope component:Uart,Spi         # named components
```

---

## 3. Useful flags

| Flag | Effect |
|---|---|
| `--no-llm` | No LLM at all. Structure is produced, prose and labels are mechanical. |
| `--model-store files` | Revert to `model/*.json`. The escape hatch; the run still works. |
| `--no-narrowed-parse` | Force a full re-parse (incremental only). |
| `--verify-parse` | Run narrowed AND full, diff them, use the full one. Slow, for validation. |
| `--data-dict-id <id>` | Merge `workspaces/<pid>/datadict/<id>.csv` into the data dictionary. |
| `--config <path>` | Use a specific config file instead of the per-project one. |

---

## 4. Checking the result

```bash
python tools\check_db.py                 # reports ONLY what looks wrong
python tools\check_db.py --version v2    # one version
python tools\dump_db.py --counts         # row counts per table
python tools\dump_db.py --version v2     # every row for one version
```

`check_db.py` is the one to reach for first — a healthy database produces a few lines saying
so, and each finding explains what it means and how to fix it.

The run's own report is on the version row:

```sql
SELECT report FROM versions WHERE id = 'v2';
```

It ends with an **LLM CALLS** block — how many calls the run made and how many produced
nothing. A non-zero "Failed" count means the document contains fallback text.

---

## 5. Running a single phase

`run.py` is the four-phase driver. It needs the run identity, because in database mode a phase
cannot infer which version it is working on:

```bash
cd engine
python run.py <checkout-path> ^
    --config ..\workspaces\myproj\config.json ^
    --version-id v2 --project-id myproj ^
    --output-root ..\workspaces\myproj\versions\v2\output ^
    --model-root  ..\workspaces\myproj\versions\v2\model ^
    --from-phase 3
```

`--from-phase N` — 1 parse, 2 derive, 3 views, 4 export.
`--use-model` skips phases 1–2 and reuses the stored model (this is what re-export does).

Phase boundaries are where the model is persisted, so resuming at 3 or 4 reads the database
rather than re-parsing.

---

## 6. The gates

Run these after any engine change. Each takes minutes and builds its own throwaway fixture and
SQLite database — none of them touch your real data.

```bash
pytest tests/unit tests/api                  # ~929 unit tests
python tools\verify_incremental.py           # baseline resolution + reuse
python tools\verify_flowchart_reuse.py       # an incremental run must not rebuild every flowchart
python tools\verify_narrowed_parse.py        # narrowed parse == full parse
python tools\verify_incremental_parity.py --fast   # incremental document == full document
python tools\verify_model_parity.py          # the database copy carries everything the files do
```

These have repeatedly caught what the unit suite could not — every one of them exists because
something passed the tests and was still broken.

---

## 7. When a run stops

| Message | Meaning |
|---|---|
| `this run needs the database but there is no versions row for 'vX'` | Reserve the row (§1). The API owns it. |
| `no database is configured` | Add the `db` section to `config.local.json`, run `db_setup.py`. |
| `narrowed parse unavailable: baseline has no parser-level snapshot` | The baseline predates the feature. It falls back to a full parse; the next run narrows. |
| `LLM CALLS : accounting unavailable` | Run `db_setup.py` — a migration is missing. |
| `run metadata is empty` | Phase 1 stored nothing. The flowchart engine will not resolve source files. |

Full log: `logs/run_<date>.log` — one file per day, so it accumulates across runs.
