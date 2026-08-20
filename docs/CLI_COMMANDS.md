# Running the analyzer from the command line

Every command below was run against this branch before being written down. Each is on ONE line
so it can be copied directly. Start at the repo root (`analyzer/`).

The database is the **default** — you do not pass a flag to get it.

---

## 1. Setup (once per machine)

```
python tools\db_setup.py
```

Creates or upgrades the schema from the `db` section of `engine/config/config.local.json`.
**Re-run it after every `git pull`** — a pull can bring a new migration, and a missing one shows
up as a feature that quietly does nothing rather than as an error.

Optional health checks:

```
python tools\verify_db_sync.py
```
```
python tools\doctor.py
```
```
python tools\check_llm.py
```

---

## 2. Setup (once per project)

Generating needs four things the engine does not create for itself: the `projects` row, the
workspace directory, that project's `config.json`, and a `versions` row (the API reserves that
at job start). One command does all of it:

**Preferred — bring your own config:**

```
python tools\new_project.py --project-id myproj --repo-url https://git.example.com/x.git --config path\to\my-config.json
```

`--config` copies a complete config in. This is the right option for a real project: layers are
only one part of it, and clang args, views and LLM settings do not belong on a command line.
Start from `engine/config/config.defaults.json`, edit it, point at it. (It is read as strict
JSON, so the comments and trailing commas that `config.defaults.json` tolerates must be removed.)

**Quick start — layers only:**

```
python tools\new_project.py --project-id myproj --repo-url https://git.example.com/x.git --layers "App=src/app,Lib=src/lib"
```

Edits only the `layers` of the default config; everything else keeps its default. Paths are
**relative to the repo root**. The two options are alternatives, not combinable.

### Using a local C++ checkout instead of a remote

`--repo-url` accepts a **local path**, because `git clone` does:

```
python tools\new_project.py --project-id myproj --repo-url D:\code\my-cpp-project --layers "App=src"
```

The one requirement is that it must be a **git repository** — the whole incremental model is
built on commits (`--commit <sha>`, baseline selection, diffs between versions). A plain
directory with no git history cannot be used.

Already have the exact commit checked out? Put it at
`workspaces/myproj/<first-16-chars-of-sha>/` and omit `--repo-url` — an existing `.git` there
is reused rather than re-cloned.

### Reserve a version for the commit you want

```
python tools\new_project.py --project-id myproj --version-id v1 --commit <full-40-char-sha>
```

`git rev-parse HEAD` gives the full sha. The command is idempotent — run it again for `v2`,
`v3`, and it prints the exact generate command to run next.

---

## 3. Generate

### First run — full generation

```
cd engine
```
```
python -m incremental.generate --project-id myproj --branch main --commit <full-sha> --version-id v1 --scope project
```

Add ` --repo-url https://git.example.com/x.git` if the checkout is not there yet.
Add ` --no-llm` for a fast, deterministic run with no LLM calls.

### Second run — incremental

Reserve `v2` first (§2), then:

```
python -m incremental.engine --project-id myproj --branch main --commit <second-sha> --version-id v2 --scope project
```

It selects the nearest ancestor version as its baseline. Add ` --base-version-id v1` to force one.

**Narrowed parse is ON by default** — only changed translation units are re-parsed.

---

## 4. Scoping

```
--scope project
```
```
--scope layer:App
```
```
--scope group:Support
```
```
--scope component:Uart,Spi
```

---

## 5. Flags worth knowing

| Flag | Effect |
|---|---|
| `--no-llm` | No LLM at all. Structure is produced; prose and labels are mechanical. |
| `--model-store files` | Revert to `model/*.json`. The escape hatch. |
| `--no-narrowed-parse` | Force a full re-parse (incremental only). |
| `--verify-parse` | Run narrowed AND full, diff them, use the full one. Slow; for validation. |
| `--data-dict-id <id>` | Merge `workspaces/<pid>/datadict/<id>.csv` into the data dictionary. |
| `--config <path>` | Use a specific config instead of the per-project one. |

---

## 6. Checking the result

```
python tools\check_db.py
```

Reports **only what looks wrong** — a healthy database gives a few lines saying so, and each
finding explains what it means and how to fix it. This is the one to reach for first.

```
python tools\check_db.py --version v2
```
```
python tools\dump_db.py --counts
```
```
python tools\dump_db.py --version v2
```

The run's own report lives on the version row:

```
SELECT report FROM versions WHERE id = 'v2';
```

It ends with an **LLM CALLS** block — how many calls the run made and how many produced nothing.
A non-zero "Failed" count means the document contains fallback text rather than real prose.

---

## 7. Running a single phase

`run.py` drives the four phases. It needs the run identity, because in database mode a phase
cannot infer which version it belongs to:

```
python run.py <checkout-path> --config ..\workspaces\myproj\config.json --version-id v2 --project-id myproj --output-root ..\workspaces\myproj\versions\v2\output --model-root ..\workspaces\myproj\versions\v2\model --from-phase 3
```

`--from-phase N` — 1 parse, 2 derive, 3 views, 4 export.
`--use-model` skips phases 1–2 and reuses the stored model (what re-export does).

The model is persisted at each phase boundary, so resuming at 3 or 4 reads the database instead
of re-parsing.

---

## 8. The gates

Run after any engine change. Each builds its own throwaway fixture and SQLite database — none
touch your real data.

```
pytest tests/unit tests/api
```
```
python tools\verify_incremental.py
```
```
python tools\verify_flowchart_reuse.py
```
```
python tools\verify_narrowed_parse.py
```
```
python tools\verify_incremental_parity.py --fast
```
```
python tools\verify_model_parity.py
```

Every one of these exists because something passed the unit tests and was still broken.

---

## 9. When a run stops

| Message | What to do |
|---|---|
| `WorkspaceNotFound: no workspace for project 'x'` | Run `tools\new_project.py` (§2) — the directory, config and rows all come from there. |
| `this run needs the database but there is no versions row for 'vX'` | Reserve it: `new_project.py --project-id … --version-id vX --commit <sha>`. |
| `no database is configured` | Add the `db` section to `config.local.json`, then `tools\db_setup.py`. |
| `per-project config not found` | `new_project.py` writes it; check `workspaces/<pid>/config.json`. |
| `clone --depth failed` | `--repo-url` is wrong or unreachable, or the sha is not on that branch. |
| `narrowed parse unavailable: baseline has no parser-level snapshot` | The baseline predates the feature. It falls back to a full parse; the next run narrows. |
| `LLM CALLS : accounting unavailable` | Run `tools\db_setup.py` — a migration is missing. |
| `run metadata is empty` | Phase 1 stored nothing; the flowchart engine will not resolve source files. |

Full log: `logs/run_<date>.log` — one file per **day**, so it accumulates across runs.
