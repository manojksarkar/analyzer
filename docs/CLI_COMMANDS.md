# Running the analyzer

There is one command. Everything below goes through it:

```
python analyzer.py <command>
```

```
python analyzer.py --help
```

```
python analyzer.py <command> --help
```

Start at the repo root (`analyzer/`). Every command on this page was run against this branch
before being written down.

There used to be four entry points — `tools/new_project.py`, `python -m incremental.generate`,
`python -m incremental.engine`, `engine/run.py` — and knowing which one a job wanted was
folklore. They are gone. The old ones now print a pointer here rather than quietly working, so
there is no second way to do anything.

---

## The whole thing, start to finish

Six commands take you from an empty database to documents, and then to an incremental second
version. Verified end to end on a local-path C++ repo.

**1. Schema.** Once per machine, and again after any `git pull` that brings a migration — a
missing migration shows up as a feature that silently does nothing.

```
python analyzer.py setup
```

**2. Write `my-config.json`.** Only `layers` is yours; `clang`, `views` and `llm` are merged in
from `engine/config/config.defaults.json`.

```json
{
  "layers": {
    "Layer1": { "path": "Layer1", "groups": { "Support": { "Math": "Math", "App": "App" } } }
  }
}
```

Paths are relative to the repo root, and a group's components map to directories under the
layer's `path` — above, `Layer1/Math` and `Layer1/App`. Comments and trailing commas are fine.

**3. Register the project** and reserve its first version. `--source` takes a git URL **or** a
local path; `<sha>` is the full 40-character sha from `git -C <your-cpp> rev-parse HEAD`.

```
python analyzer.py onboard --project-id myproj --source D:\code\my-cpp --config my-config.json --version-id v1 --commit <sha>
```

Read the line it prints back before going on — it is the fastest way to catch a wrong config:

```
config   : ...\workspaces\myproj\config.json WRITTEN (from my-config.json + defaults)
           Layer1 / Support: Math, App
version  : v1 RESERVED for 1d04bb15d8
```

**4. Generate.**

```
python analyzer.py generate --project-id myproj --version-id v1
```

That is the whole command. **`--branch` and `--commit` are not needed** — `onboard` recorded
both, so `generate` reads the branch off the project and the commit off the version you
reserved. Pass them only to override:

```
python analyzer.py generate --project-id myproj --version-id v1 --branch br_trunk --commit <sha>
```

`--scope` defaults to `project`.

```
version v1 (complete): commit 1d04bb15d8, decision=full, regenerated=18, reused=0,
documents=['software_detailed_design_App.docx', 'software_detailed_design_Math.docx']
```

**5. Change some C++ and commit it.** The engine works off commits, so an uncommitted edit is
invisible to it.

```
git -C D:\code\my-cpp commit -am "change add()"
```

**6. Generate again — this is the incremental run.** The same command with a new version id.
`generate` finds v1 as the baseline and takes the incremental path itself; there is no separate
incremental command to remember.

```
python analyzer.py generate --project-id myproj --version-id v2 --commit <sha2> --create-version
```

`--commit` IS needed here, because v2 is a new version id with no commit recorded against it
yet. `--create-version` reserves the row so you do not have to run `onboard` again.

Two ways to do the same thing, if you prefer reserving first:

```
python analyzer.py onboard --project-id myproj --version-id v2 --commit <sha2>
```
```
python analyzer.py generate --project-id myproj --version-id v2
```

```
version v2 (complete): commit 8b767ac90e, decision=incremental, regenerated=4, reused=12
```

Then look at what happened:

```
python analyzer.py report
```

Documents land in `workspaces/<pid>/versions/<version-id>/documents/`, with per-component copies
under `.../output/<Component>/`.

---

## The incremental command

It is `generate`. There is no second command:

```
python analyzer.py generate --project-id myproj --version-id v2 --commit <sha2> --create-version
```

Run that against a later commit of a project that already has a finished version, and you get an
incremental run — only the changed translation units re-parsed, everything else reused.

## Incremental runs: you get them, you do not ask for them

Incremental generation is very much alive — it is the normal path. What went away is the
*command* for it. There used to be two (`incremental.generate` for the first version,
`incremental.engine` for the rest) and picking wrong either wasted an hour re-parsing or failed
outright.

`generate` resolves the baseline and decides:

| Situation | What it does |
|---|---|
| no earlier version, or none usable | full run — parses everything |
| a usable ancestor version exists | incremental — re-parses only the changed translation units, reuses the rest |

`--full` forces the long way round when you want to rule the baseline out of a comparison.

**How to confirm you got an incremental run.** The last line of the run says so, and `report`
shows what it saved:

```
version v2 (complete): commit 8b767ac90e, decision=incremental, regenerated=4, reused=12
```

```
python analyzer.py report
```

```
CHANGE CLASSIFICATION (this commit vs the baseline)
  changed   : 1    (1 function)
  unchanged : 17   (15 function, 2 global)
REUSE ACCOUNTING (regenerated by the LLM  vs  reused/carried)
  Functions : regenerated 4    / 16   -> reused 12 (75%)
  Flowcharts: regenerated 1    / 16   function(s) -> carried 15 (93%)
```

`decision=full` on a later commit means no usable baseline was found — usually the previous
version did not reach a terminal state, or `--force`/`--full` was passed.

Narrowed parse (re-parsing only the changed translation units) is part of this and is **on by
default**. The run log says so: `narrowed parse: 1 affected TU(s)`.

---

## Commands

| Command | For |
|---|---|
| `setup` | create or upgrade the database schema |
| `onboard` | register a project: row, workspace, config, first version |
| `generate` | produce a version from a commit |
| `reexport` | rebuild a version's documents from its stored model |
| `status` | what the database holds |
| `check` | check the database, reporting only what is wrong |
| `report` | a version's generation report |
| `doctor` | check prerequisites (clang, node, graphviz, browser) |
| `check-llm` | ask the LLM gateway directly whether it answers |
| `check-datadict` | validate a data-dictionary CSV before a run |
| `llm-stats` | compare the LLM cost of two runs |
| `verify` | run the correctness gates |

### `setup`

```
python analyzer.py setup
```
```
python analyzer.py setup --demo
```

`--demo` also seeds demo users and projects, for a fresh database you want to click around in.

### `onboard`

Every flag it takes, in one line:

```
python analyzer.py onboard --project-id myproj --name "My Project" --source D:\code\my-cpp --branch main --config my-config.json --version-id v1 --commit <full-40-char-sha> --force-config
```

| Flag | Effect |
|---|---|
| `--project-id` | required |
| `--name` | display name (default: the id) |
| `--source` | git URL **or** local path. Omit when the commit is already checked out in the workspace. |
| `--branch` | default `main` |
| `--config` | this project's config.json |
| `--use-defaults` | use this repo's SAMPLE tree instead. An alternative to `--config`, never both. |
| `--force-config` | replace a config that already exists |
| `--version-id` / `--commit` | also reserve the first version. Both or neither. |

**A local path must be a git repository — for every run, not just incremental ones.** A plain
directory fails at the clone with `fatal: Could not read from remote repository`, because a
commit is not optional anywhere: the version's directory is named after it
(`workspaces/<pid>/<commit[:16]>/`), the checkout is made by `git clone --branch <b>` and
`git checkout <sha>`, and the baseline search compares commits. There is no code path that
parses a directory without one.

Making one is two commands and costs nothing:

```
git -C D:\code\my-cpp init
```
```
git -C D:\code\my-cpp add -A
```
```
git -C D:\code\my-cpp commit -m "initial"
```

Give `onboard` the real branch with `--branch`; it is recorded on the project and every later
`generate` uses it. If you skip it, the default is `main`, and on a repo whose branch is
something else the run stops at the clone with `Remote branch main not found` — the message
names the branch and tells you to pass `--branch` or re-onboard.

The source is **cloned**, not read in place, so uncommitted edits are invisible until you commit
them. `warning: --depth is ignored in local clones` is normal: git never shallow-clones a local
path, and the full history is what the baseline search wants anyway.

### `generate`

Every flag it takes, in one line:

```
python analyzer.py generate --project-id myproj --commit <sha> --version-id v2 --branch main --scope "group:Support" --source D:\code\my-cpp --config my-config.json --data-dict dd2024 --create-version --no-llm --full --base-version v1 --no-narrowed-parse --verify-parse --unit Utils --force
```

| Flag | Effect |
|---|---|
| `--project-id`, `--version-id` | required |
| `--commit` | the full 40-character sha. **Default: the one recorded for this version** when it was reserved. |
| `--branch` | **Default: the project's branch**, as recorded by `onboard`. |
| `--scope` | one of `project` (default), `layer:A,B`, `group:A,B`, `component:A,B` |
| `--source` | clone from here if the commit is not checked out yet |
| `--config` | use this config instead of the project's |
| `--data-dict <id>` | merge `workspaces/<pid>/datadict/<id>.csv` into the data dictionary |
| `--create-version` | reserve the `versions` row if absent. Opt-in, so a mistyped `--version-id` fails instead of silently starting a new version. |
| `--no-llm` | no LLM at all — structure only, mechanical prose and labels |
| `--full` | force a full run even when a baseline exists |
| `--base-version <id>` | force this baseline instead of the nearest ancestor |
| `--no-narrowed-parse` | re-parse everything instead of only the changed translation units |
| `--verify-parse` | run narrowed AND full, diff them, use the full one. Slow; for validation. |
| `--unit <name>` | narrow the per-function FLOWCHART work to this unit. Repeatable. See below — it is a speed aid, not a scope. |
| `--force` | accepted; the commit dir is reused either way |

`--full`, `--no-narrowed-parse` and `--verify-parse` are all "do it the slow way on purpose".
None belongs in a routine run.

### Checking one unit's images with `--unit`

Rendering every unit's diagrams to look at one of them is a slow way to check your work.
`--unit` narrows the **image work** to the unit you name, on both `generate` and `reexport`:

```
python analyzer.py reexport --project-id myproj --version-id v2 --unit Utils
```
```
python analyzer.py generate --project-id myproj --version-id v3 --unit Utils
```

It narrows all three image views — flowcharts, unit diagrams and behaviour diagrams. Measured on
the sample project: **70 flowchart PNGs without it, 35 with `--unit Utils`**, and only
`Math_Utils.mmd` instead of both unit diagrams.

Other units' images already on disk are left alone, so what you get is the named unit's images
freshly rendered beside whatever was there before — which is what you want when you are checking
one unit repeatedly.

**Three cases, three behaviours:**

| You ask for | What happens |
|---|---|
| a unit in the scope you are running | rendered; everything else skipped |
| a unit in another component of the same run | that component renders nothing and says so; the run continues |
| a unit that exists nowhere, or outside the scope you asked for | hard error, listing the real units |

The middle row is the one that used to be broken. Documents are produced per component, so
Phase 3 runs once per component — `--unit Utils` reached the App run as well as the Math one and
killed the whole thing with `unknown --selected-unit 'Utils'`, *after* Math's diagrams had been
rendered. A unit that is simply elsewhere is not an unknown unit.

### What `--unit` does not do

**It is still not a document scope.** It narrows the IMAGES, and nothing else:

| | with `--unit Utils` |
|---|---|
| flowcharts | **only that unit's** |
| unit diagrams | **only that unit's** |
| behaviour diagrams | **only that unit's** |
| interface tables | unchanged — a table, not an image |
| the model (phases 1–2) | unchanged — every unit still parsed |
| the documents | unchanged — still whatever `--scope` asks for |

So `--unit Utils` on a project-scoped run still produces `App.docx` and `Math.docx`; it just does
not spend minutes drawing App's images while you are checking Math's. Other units' images already
on disk are left in place, so what you get is the named unit's, freshly rendered, beside whatever
was there before.

**There is no unit-level document today.** `--scope unit:Utils` does not exist: the DOCX exporter
has no unit filter, so a document covering one unit is not something the pipeline can currently
produce. The smallest document unit is a component (`--scope "component:Math"`).

An unknown unit name stops the run and lists the real ones. When a model already exists that
check happens **before Phase 1** rather than three phases in.

### `reexport`

Rebuild a version's documents from its **stored model** — no parsing, no LLM. This is what you
run after changing a view or the DOCX template.

```
python analyzer.py reexport --project-id myproj --version-id v2
```
```
python analyzer.py reexport --project-id myproj --version-id v2 --from-phase 4 --unit Uart --unit Spi
```

| Flag | Effect |
|---|---|
| `--from-phase` | 2 = re-derive, then views + export; 3 = views + export (default); 4 = export only |
| `--scope` | re-render a **narrower** slice than the version was generated with |
| `--unit <name>` | narrow the per-function flowchart work to this unit. Repeatable. |

It needs the version's commit still checked out, because flowcharts and line numbers are read
from the source. If the checkout is gone it says so rather than producing an empty document.

#### Re-derive without re-parsing

Parsing is the expensive part and it is already rows, so there is never a reason to redo it for
a change further down the pipeline. `--from-phase` says how far back to go:

```
python analyzer.py reexport --project-id myproj --version-id v2 --from-phase 2
```

| `--from-phase` | Re-runs | Use it after changing |
|---|---|---|
| `2` | derive → views → export | the model deriver (units, components, summaries) |
| `3` | views → export (default) | a view — interface tables, diagrams, flowcharts |
| `4` | export | the DOCX exporter or a template |

Phase 1 is never re-run by `reexport`. To re-parse, use `generate`.

Verified: deleting a version's `model_units` rows and running `--from-phase 2` rebuilt them,
with `Phase 1: Parse C++ source — skipped (--from-phase 2)` in the log.

#### Running phases individually

All four phases can be run on their own, and each writes to the database at its own boundary.
Verified by clearing a version's rows and rebuilding it one phase at a time:

| after | `entity_versions` | `model_units` | `model_edges` |
|---|---|---|---|
| (cleared) | 0 | 0 | 0 |
| phase 1 — parse | **60** | 0 | **18** |
| phase 2 — derive | 60 | **2** | 18 |
| phase 3 — views | 60 | 2 | 18 |
| phase 4 — export | 60 | 2 | 18 |

Phase 1 lands the parsed skeleton and the call graph; phase 2 adds the derived units; phases 3
and 4 only READ the model, which is why the counts stop moving. All four exited 0.

**What a phase does NOT do.** A phase writes its own model rows and stops. Everything *around*
them belongs to the orchestrator and does not happen if you invoke phases directly:

| | written by |
|---|---|
| the model — entities, units, edges, parse snapshot | the **phases** |
| `versions.base_path` (the flowchart engine resolves source files with it) | the orchestrator |
| `version_output_files` (the stored render, what another node serves) | the orchestrator |
| the manifest, the run report | the orchestrator |
| fingerprints + the reuse index (what makes the NEXT run incremental) | the orchestrator |

So running phases by hand is right for **iterating**, and wrong as a way to **produce a
version** — the rows would be correct while `base_path` stayed stale, the stored render stayed
old, and the next run found nothing to reuse.

That is why phases 3 and 4 are exposed as `reexport` rather than as raw phase numbers: it does
the orchestrator's part too, capturing the re-rendered views back into the database. Phases 1
and 2 are not exposed at all — use `generate`.

#### Model once, documents many times

This is the flexibility the file-based pipeline had, and it survived the move to the database
intact — the model is rows now, so phases 3 and 4 read it from there instead of from
`model/*.json`. Nothing else changed.

Parse the **whole project** once:

```
python analyzer.py generate --project-id ph --commit <sha> --version-id v1
```
```
Access/software_detailed_design_Access.docx
App/software_detailed_design_App.docx
Math/software_detailed_design_Math.docx
```

Then re-render any slice of it, without re-parsing anything:

```
python analyzer.py reexport --project-id ph --version-id v1 --scope "component:Math"
```
```
Math/software_detailed_design_Math.docx
```

```
python analyzer.py reexport --project-id ph --version-id v1 --scope "group:Support"
```
```
App/software_detailed_design_App.docx
Math/software_detailed_design_Math.docx
```

Omit `--scope` and you get the scope the version was generated with — the same documents
`generate` produced.

**Phase 4 alone** rebuilds only the DOCX, from the `interface_tables.json` phase 3 left behind.
Under two seconds, and the right thing to run while iterating on the exporter or a template:

```
python analyzer.py reexport --project-id ph --version-id v1 --scope "component:Math" --from-phase 4
```

The one thing to know: phase 4 reads phase 3's output, so it needs that output to still be
there. Wipe `output/` and `--from-phase 4` has nothing to export.

Scoping down costs nothing extra — the model already covers the whole layer, so a narrower
re-export is purely less view work. Scoping *up* beyond what the model holds is not possible;
generate a wider version for that.

### `status`, `check`, `report`

```
python analyzer.py status
```
```
python analyzer.py status --version v2 --out dump.txt
```
```
python analyzer.py check
```
```
python analyzer.py check --version v2 --quiet --out report.txt
```
```
python analyzer.py report
```
```
python analyzer.py report --version v2
```

`status` prints row counts (or one version in full). `check` reports **only what looks wrong** —
a healthy database gives a few lines saying so, and each finding says what it means and how to
fix it; this is the one to reach for first. `report` prints a version's generation report,
newest by default.

All three print to stdout; `--out` also writes a file.

### `doctor`, `check-llm`, `check-datadict`

```
python analyzer.py doctor
```
```
python analyzer.py doctor --quiet
```
```
python analyzer.py check-llm
```
```
python analyzer.py check-llm --raw --only description --max-tokens 256
```
```
python analyzer.py check-datadict dd_layer1.csv --layer Layer1 --quiet
```

`doctor` checks clang, node, graphviz and the browser before a long run stops on a missing one.
`check-llm` asks the gateway directly, so "no descriptions in the document" can be attributed to
the model rather than the pipeline. `check-datadict` validates a CSV **before** a run — a
malformed one used to be accepted in silence and the ranges simply never appeared.

### `llm-stats`

Every run writes `logs/llm_stats_<run-id>.json`. Pass two to see what a change did:

```
python analyzer.py llm-stats logs\llm_stats_A.json logs\llm_stats_B.json
```

It prints the config difference first, because a comparison you cannot attribute to a specific
change is two columns of numbers.

### `verify`

```
python analyzer.py verify
```
```
python analyzer.py verify --list
```
```
python analyzer.py verify incremental narrowed-parse
```
```
python analyzer.py verify --fast --keep-going
```

| Gate | What it proves |
|---|---|
| `tests` | the unit + API suites |
| `incremental` | a two-version run reuses and regenerates correctly |
| `narrowed-parse` | a narrowed parse equals a full one |
| `flowchart-reuse` | an incremental run carries flowcharts forward |
| `parity` | an incremental document equals a full one |
| `db-sync` | the model round-trips through real Postgres |
| `db-rebuild` | a fresh node could rebuild a version from the database |

They build their own fixtures and throwaway databases; none touch your data. It stops at the
first failure unless you pass `--keep-going`. Every one exists because something passed the unit
tests and was still broken.

---

## Scoping

**Quote the value.** A scope naming more than one thing contains a comma, and some shells treat
that as an argument separator — which surfaces as `expected one argument` and reads like a bug
in the tool.

```
--scope project
```
```
--scope "layer:Layer1"
```
```
--scope "group:Support"
```
```
--scope "group:Support,Access"
```
```
--scope "component:App,Math"
```

**Groups and components are not the same thing**, and mixing them up is the most likely reason a
scope is rejected. In the shipped sample config, `Support` is a *group* and `App` / `Math` are
*components* inside it. If you name a component where a group belongs, the error says so and
prints the corrected command. To see yours:

```
python -c "import json; cfg=json.load(open('workspaces/myproj/config.json')); [print(f'{g}: {list(c)}') for l in cfg['layers'].values() for g,c in (l.get('groups') or {}).items()]"
```

**One document or several?**

| Scope | Documents produced |
|---|---|
| `project` | one per **component**, across the whole project |
| `layer:L` | one per component in that layer |
| `group:G` | one per component in that group |
| `component:A,B` | **ONE combined document**, named `A_B` |

`component:` bundles deliberately — that is how you produce a single document covering a chosen
set. For App and Math as **separate** documents, scope to the group that holds them.

**What a scope does and does not limit:** it selects which **documents** are produced. Parsing
stays **layer-scoped**, because a function in one group can call into another group in the same
layer and a model missing those callees would give you wrong call graphs. So with `App,Math` in
`Layer1`, the stored model covers `Layer1` while the documents cover App and Math only.

---

## Per-layer inputs live in the config

A real project rarely has one set of macros or one data dictionary. These are **config keys, not
flags** — a layer owns its own inputs, so the layer name is never repeated in a separate map
where a typo would silently match nothing:

```json
{
  "layers": {
    "Layer1": {
      "path": "Layer1",
      "dataDictionary": "dd_layer1.csv",
      "macros": "macros.layer1.json",
      "groups": { "Support": { "Math": "Math", "App": "App" } }
    }
  },
  "clang": {
    "clangArgs": ["-target", "arm-none-eabi", "-UPUBLIC"],
    "macrosFile": "macros.json",
    "macrosByLayer": { "Layer1": "macros.layer1.json" }
  }
}
```

`engine/config/macros.layer1.example.json` is a working macro file. For a UI job you write none:
the API materialises `workspaces/<pid>/macros.json` from the project's
`preprocessor_definitions`.

**Include directories are discovered**, not listed. Every directory under a layer's `path` is
walked into `model/clang_include_paths.json` automatically — you only need to declare ones that
live *outside* your tree, like a third-party SDK.

---

## When a run stops

| Message | What to do |
|---|---|
| `no database is configured` | Add the `db` section to `engine/config/config.local.json`, then `python analyzer.py setup`. The model and every version artifact live there and nowhere else. |
| `WorkspaceNotFound: no workspace for project 'x'` | `python analyzer.py onboard` — the directory, config and rows all come from there. |
| `this run needs the database but there is no versions row for 'vX'` | Reserve it (the message prints the exact command), or add `--create-version`. |
| `<pid> has no config yet, and no --config was given` | Pass `--config <your.json>`, or `--use-defaults` for the sample tree. |
| `ALREADY EXISTS and differs from --config` | The project already has a config. `--force-config` replaces it. |
| `--config not found: <path>` | The path does not resolve. Nothing was created; fix it and re-run. |
| `<path> is not valid JSON` | The message prints the offending line and its neighbours. Comments and trailing commas are accepted, so it is usually a missing comma between entries or an unclosed brace. |
| `bad --scope '...'` | The message lists the four accepted forms. |
| `Unknown group(s) in the scope: X` | X is probably a **component**, not a group — the message says so and prints the corrected `--scope`. |
| `clone --depth failed` | `--source` is wrong or unreachable, or the sha is not on that branch. |
| `clone --depth failed: ... Filename too long` | Windows path limit. `git config --global core.longpaths true`, or move the workspace somewhere shorter. |
| `narrowed parse unavailable: baseline has no parser-level snapshot` | The baseline predates the feature. It falls back to a full parse; the next run narrows. |
| `LLM CALLS : accounting unavailable` | Run `python analyzer.py setup` — a migration is missing. |
| `run metadata is empty` | Phase 1 stored nothing; the flowchart engine will not resolve source files. |

A rejected request stops with the explanation and **no traceback** — the last line you see is
the one worth reading. A traceback means something genuinely broke, not that you typed the wrong
scope.

Full log: `logs/run_<date>.log`, one file per **day**, so it accumulates across runs.

---

## Reading the LLM cost

Every run's report ends with:

```
LLM CALLS (a failed call means the caller fell back to a mechanical result)
  Total     : 185    answered 180 (97%)
  Failed    : 5      empty 5, error 0  -> 2% of calls produced NOTHING
  Time      : 795s total  (240s waiting on the model, 555s in the rate-limit pause)
  Tokens    : 102000  (90000 prompt, 12000 completion)
```

A non-zero **Failed** count means the document contains fallback text rather than real prose.

If **Time** is mostly the pause rather than the model, `llm.rateLimitSeconds` is the lever. It
is `3.0` by default, which is right for a throttled corporate gateway and pure waste for an
on-prem hosted model that has no limit — set it to `0` there. That one value is usually the
largest speed difference available, and the Time line is how you tell whether it applies to you.

---

## What `engine/run.py` is

Still there, still runs the four phases, **not a front door**. It is what the orchestrator
spawns per phase, the way a compiler spawns an assembler: it takes a version id, a project id
and its roots, and would not know what to do without them. `reexport` is the supported way to
drive phases 3 and 4 by hand.
