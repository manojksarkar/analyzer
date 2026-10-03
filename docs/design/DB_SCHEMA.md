# Database — ER diagrams & debugging queries

The analyzer stores everything in PostgreSQL: the model, the view outputs, run metadata, the
reuse index and all app data. This is the map for looking inside it.

Schema source of truth: [`api/db/postgres/schema.py`](../../api/db/postgres/schema.py) (SQLAlchemy
Core, one `metadata`). Migrations: `alembic/versions/`. Design rationale:
[07 PG migration](../production-redesign/07-postgresql-migration-plan.md) ·
[02 database study](../production-redesign/02-database-design-study.md).

**Zoomable viewer:** [schema-atlas.html](schema-atlas.html) — the same content as a self-contained page
(Mermaid inlined, no network needed) with pan/zoom on the ER diagrams and a copy button on every query.
Open it in a browser: VS Code's Markdown preview renders Mermaid at a fixed size with no zoom.

## Contents

- [Connect](#connect)
- [Six table groups](#six-table-groups)
- [ER — model core](#er--model-core-the-one-that-matters-for-debugging)
- [ER — runs, versions, documents](#er--runs-versions-documents)
- [ER — access & inputs](#er--access--inputs)
- [ER — review & update](#er--review--update)
- [Conventions you need before querying](#conventions-you-need-before-querying)
- [Query cookbook](#query-cookbook)
- [Tables nothing writes](#tables-nothing-writes)
- [Use the tools first](#use-the-tools-first)

---

## Connect

DSN resolution order (`engine/core/db.py`): `DATABASE_URL` env → the `db` section of
`engine/config/config.local.json` → the compose default
`postgresql+psycopg://analyzer:analyzer@localhost:5432/analyzer`. It is a **machine-level**
setting — `--config` / `ANALYZER_CONFIG` never carries it.

```bash
# Windows, portable PG 16 on this box
PGPASSWORD=analyzer "C:/Users/User/pgsql/bin/psql.exe" -h 127.0.0.1 -U analyzer -d analyzer

# then:  \dt   list tables      \d entity_versions   describe one
```

---

## Six table groups

| Group | Tables | What it holds |
|---|---|---|
| **Model** | `entities` · `entity_versions` · `content_blobs` · `model_units` · `model_components` · `model_edges` · `model_summaries` | The parsed + derived C++ model |
| **Runs** | `projects` · `versions` · `analysis_jobs` · `commits` · `version_output_files` · `parse_snapshots` · `knowledge_base` · `incremental_plans` · `tu_includes` · `version_components` · `version_runs` | One analysis run and its artifacts; each component's documents and the version's latest run |
| **Reuse / LLM** | `reuse_index` · `llm_description_cache` · `llm_call_stats` | Incremental reuse + LLM accounting |
| **Documents** | `documents` · `document_sections` · `document_assignments` · `document_review_events` · `compare_results` · `document_diffs` · `job_functions` | The web app's document layer, and each document's review and approval |
| **Access** | `users` · `project_members` · `access_requests` · `notifications` · `data_dictionaries` · `data_dictionary_entries` | RBAC and project inputs |
| **Review** | `text_overrides` · `text_override_history` · `regeneration_queue` · `render_jobs` · `view_derivations` | Reviewers' corrections to LLM-written text, and the work a correction queues |

---

## ER — model core (the one that matters for debugging)

**Manifest of pointers (D-9).** A version does not copy the model. Stable identity lives in
`entities`; each version contributes one thin row per entity to `entity_versions`; the heavy
payload lives once in `content_blobs`, content-addressed. Carry-forward = pointing at the same
`content_hash`, so storage grows with *distinct content*, not versions × entities.

```mermaid
erDiagram
    projects  ||--o{ entities         : "owns (stable identity)"
    projects  ||--o{ versions         : ""
    versions  ||--o{ entity_versions  : "one thin row per entity"
    entities  ||--o{ entity_versions  : ""
    content_blobs ||--o{ entity_versions : "payload, shared by hash"
    versions  ||--o{ model_edges      : "the dependency graph"
    versions  ||--o{ model_units      : ""
    versions  ||--o{ model_components : ""
    versions  ||--o{ model_summaries  : ""
    content_blobs ||--o{ model_summaries : "deduped text"

    entities {
        bigint entity_id PK
        string project_id FK
        string entity_key UK "Component|Unit|qname|params"
        string kind "function|global|type|macro"
        string qualified_name
    }
    entity_versions {
        string version_id FK
        bigint entity_id FK
        string component
        string unit
        string file
        int    line
        string direction "In|Out"
        string direction_reason
        string visibility "public|private"
        string interface_id
        bool   is_visible "hide/unhide"
        string source_hash "code changed? -> classify"
        string fingerprint "reuse LLM output? -> reuse_index"
        string content_hash FK "payload pointer"
    }
    content_blobs {
        string content_hash PK
        string kind
        jsonb  payload "returnType, params, description, ..."
    }
    model_edges {
        bigint edge_id PK
        string version_id FK
        string kind "call|global_access|type_use|macro_use|override"
        string src_key "the USER"
        string dst_key "the DEPENDENCY"
        string mode "read|write (global_access only)"
    }
```

Every edge points **user → dependency**, so "who depends on X" is a reverse lookup on `dst_key`
(indexed: `ix_edges_reverse`). `calledByIds` is never stored — it is the reverse of `callsIds`,
rebuilt on load.

## ER — runs, versions, documents

```mermaid
erDiagram
    projects ||--o{ versions             : ""
    projects ||--o{ commits              : ""
    projects ||--o{ analysis_jobs        : ""
    projects ||--o{ reuse_index          : "first-writer-wins per fingerprint"
    projects ||--o{ llm_description_cache : "per PROJECT, not per version"
    versions ||--o{ analysis_jobs        : ""
    versions ||--o| versions             : "baseline_version_id (incremental)"
    versions ||--o{ version_output_files : "Phase-3 output/ files"
    versions ||--o{ parse_snapshots      : "post-Phase-1 skeleton"
    versions ||--o| knowledge_base       : "1 row, whole object"
    versions ||--o| incremental_plans    : "1 row, what to regenerate"
    versions ||--o{ tu_includes          : "narrowed-parse include closure"
    versions ||--o{ llm_call_stats       : ""
    versions ||--o{ documents            : ""
    documents ||--o{ document_sections   : ""
    documents ||--o| document_assignments : "its one reviewer"
    documents ||--o{ document_review_events : "the review record"
    versions ||--o{ version_components   : "per component a run asked for"
    versions ||--o| version_runs         : "its latest run and how far it got"
    projects ||--o{ compare_results      : ""
    compare_results ||--o{ document_diffs : ""

    versions {
        string id PK
        string project_id FK
        string version UK "UI-supplied, unique per project"
        string commit_sha
        string pipeline_status "parsing|deriving|...|complete|failed"
        string status "draft|in_review|approved - from its documents"
        string decision "incremental|full"
        int    regenerated
        int    reused
        string base_path "source checkout - NULL breaks flowcharts"
        jsonb  resolved_config
        jsonb  run_report "manifest.json, verbatim"
        text   report "report.txt"
    }
    version_output_files {
        string version_id PK
        string rel_path PK "e.g. Layer1.Diag/interface_tables.json"
        text   content
        string group_name
    }
    documents {
        string id PK
        string version_id FK
        string component "its output dir, e.g. Layer1.Util"
        string status "in_review|submitted|changes_requested|approved"
        string approved_by
        timestamptz approved_at
        string docx_sha256 "the Word file that was approved"
        string approved_docx_path "the copy kept at approval"
        string content_fingerprint "carries an approval to an unchanged next version"
        string carried_from "version id the approval came from"
    }
    document_review_events {
        string id PK
        string document_id FK
        string kind "assigned|claimed|submitted|approved|changes_requested|reopened|carried|generated"
        string actor_id "NULL: the run did it"
        timestamptz at
        text comment
        jsonb payload
    }
    version_components {
        string version_id PK
        string component PK "its output dir = documents.component"
        string state "waiting|generating|generated|failed"
        timestamptz requested_at
        timestamptz started_at
        timestamptz finished_at
        text error
    }
    version_runs {
        string version_id PK
        string command "generate|export|reexport|resume|web run"
        jsonb argv "repeated by resume"
        int pid
        string code_dir "frozen code of a --detach run"
        string outcome "running|complete|failed"
        string stage "progress: stage, done, total"
    }
```

A version is `approved` when every one of its documents is: the status is derived and written on
each approval and reopen (`api/services/review_workflow.py`; contract
[REVIEW_APPROVE_API_SPEC](../spec/REVIEW_APPROVE_API_SPEC.md)).

A version's model covers whole layers; its documents are made per component, by any number of runs
(`generate`, `export`, `reexport`, `resume`). `version_components` has a row per component a run
asked for; a component of the model with no row and no documents is "not requested" — worked out
when read (`api/services/version_components.py`). `version_runs` is the latest run; whether it is
still alive is a Postgres advisory lock its process holds (`engine/core/version_run.py`), never a
column ([CLI_COMMANDS](../CLI_COMMANDS.md#a-run-that-lasts-days)).

## ER — access & inputs

```mermaid
erDiagram
    users    ||--o{ project_members  : ""
    users    ||--o{ access_requests  : ""
    users    ||--o{ notifications    : ""
    users    ||--o{ document_assignments : ""
    projects ||--o{ project_members  : ""
    projects ||--o{ access_requests  : ""
    projects ||--o{ data_dictionaries : ""
    data_dictionaries ||--o{ data_dictionary_entries : "one CSV row each"
    projects ||--o{ macro_definitions : ""
```

`organizations` was dropped (D-8) — `projects.org_id` is a plain free-text tenant tag, not a FK.
`users.is_superuser` marks a user who may act on every project without a `project_members` row
(migration 0014). It is `false` for everyone, the seeded `admin@aspice.dev` login included, until set
on purpose: `python tools/grant_access.py --set-superuser --email <address>`.

## ER — review & update

A reviewer's correction replaces one LLM-written text — a **slot** — in one version.
`slot_key` is built by `engine/review/slot.py` and nothing else; `human_text` is what the
document prints. The model is patched in the same transaction, and the next version carries
the row forward (`is_orphaned` once the text's entity is gone). The unit description a
`unitDescription` slot corrects is `model_units.description`, which Phase 2 writes.
Specs: [REVIEW_UPDATE_SPEC](../spec/REVIEW_UPDATE_SPEC.md) ·
[REVIEW_UPDATE_API_SPEC](../spec/REVIEW_UPDATE_API_SPEC.md).

```mermaid
erDiagram
    versions ||--o{ text_overrides        : "one row per corrected text"
    versions ||--o{ text_override_history : "every save, capped per slot"
    versions ||--o{ regeneration_queue    : "texts built FROM a corrected one"
    versions ||--o{ render_jobs           : "flowchart pictures to redraw"
    versions ||--o{ view_derivations      : "when Phase-3 output was last derived"

    text_overrides {
        string version_id PK
        string slot_kind PK "description|unitDescription|structDescription|nodeLabel|..."
        string slot_key PK "built by review/slot.py only"
        text   llm_text "what the LLM wrote"
        text   human_text "what the document prints"
        bool   is_orphaned "carried forward, entity gone"
        string updated_by
        string updated_at
    }
    text_override_history {
        bigint history_id PK
        string version_id FK
        string slot_kind
        string slot_key
        text   human_text
        int    seq "per slot, drives the cap"
    }
    regeneration_queue {
        string version_id PK
        string slot_kind PK
        string slot_key PK
        string reason
        string source_slot_kind "the correction that queued it"
        string source_slot_key
    }
    render_jobs {
        bigint job_id PK
        string version_id FK
        string flowchart_id
        string png_name
        string status
    }
    view_derivations {
        string version_id PK
        string view_name PK "a view: interfaceTables, testSpecs"
        string group_name PK "the component it was derived for"
        string derived_at
    }
```

An export refuses to ship old wording (`engine/review/export_guard.py`): it is **stale** when a
correction is newer than the derivation, **for the correction's own component**, of a view its text
reaches and the exported document prints. `view_derivations` holds one row per (version, view,
component) — `group_name` is the component, in `layer1.sample-core` form — and is rebuilt at every
capture from the `_derivations.json` records Phase 3 stores with its output (a save that re-derives
SWE.4 rows marks those records too). Rows with `view_name = '*'`, written before 2026-09-29, are
ignored.

---

## Conventions you need before querying

**`entity_key` is the join key everywhere** (`model_edges.src_key`/`dst_key`, `reuse_index`,
`parse_snapshots`), and its *shape* is what classifies the entity (`model_store._entity_kind`):

| Kind | Shape | Example |
|---|---|---|
| function | `Component\|Unit\|qname\|params` (≥3 pipes) | `Layer1.Diag\|ClassStatics\|statBumpPublic\|` |
| global | `Component\|Unit\|name` (2 pipes) | `Layer1.Diag\|ClassStatics\|StatCounters::s_publicCount` |
| macro | `name@file` (no pipe) | `SHARED_MAX@Layer1/Sample/Core/SharedDefs.h` |
| type | anything else | `SharedLevel` |

Note the **trailing pipe** on a no-argument function — `…|statBumpPublic|`, not `…|statBumpPublic`.
Use `LIKE 'Comp|Unit|name|%'` if you are unsure of the parameter part.

**Three hashes, three jobs (D-15).** `source_hash` — did the code change? (drives `classify`).
`fingerprint` — can I reuse the LLM output? (drives `reuse_index`). `content_hash` — is this payload
byte-identical to one already stored? (drives blob dedup). All hex strings, so they join cleanly.

**Everything per-version cascades.** `PER_VERSION_TABLES` at the bottom of `schema.py` lists the 14
tables a version owns; deleting the `versions` row removes them all. `entities` and `content_blobs`
are **shared** and deliberately survive.

**JSONB access:** `->` returns jsonb, `->>` returns text. `payload->>'description'` for a value,
`jsonb_pretty(payload)` to read a whole blob.

---

## Query cookbook

Every query below was run against a live database. Replace `'f1'` with your version id and
`'myproj'` with your project id.

### Orientation — what is in here

```sql
-- Recent runs, newest first: did it finish, was it incremental, how much was reused?
SELECT p.name, v.id, v.version, v.pipeline_status, v.decision,
       v.regenerated, v.reused, v.created_at
FROM versions v JOIN projects p ON p.id = v.project_id
ORDER BY v.created_at DESC LIMIT 10;

-- What a version actually produced
SELECT (SELECT count(*) FROM entity_versions WHERE version_id = v.id) AS entities,
       (SELECT count(*) FROM model_edges     WHERE version_id = v.id) AS edges,
       (SELECT count(*) FROM model_units     WHERE version_id = v.id) AS units,
       (SELECT count(*) FROM version_output_files WHERE version_id = v.id) AS out_files,
       v.base_path
FROM versions v WHERE v.id = 'f1';
```

`base_path` NULL is a real bug signature: the flowchart engine then resolves every source file
against `""` and returns empty flowcharts **with the run still reporting success**.

### Find an entity

```sql
SELECT e.entity_key, e.kind, ev.file, ev.line, ev.direction, ev.visibility, ev.interface_id
FROM entities e JOIN entity_versions ev USING (entity_id)
WHERE ev.version_id = 'f1' AND e.qualified_name ILIKE '%statBump%';
```

### Read a function's full payload (the LLM-filled part)

```sql
SELECT e.entity_key, jsonb_pretty(b.payload)
FROM entity_versions ev
JOIN entities e USING (entity_id)
LEFT JOIN content_blobs b ON b.content_hash = ev.content_hash
WHERE ev.version_id = 'f1' AND e.entity_key = 'Layer1.Diag|ClassStatics|statBumpPublic|';
```

### Why does this interface say In / Out?

```sql
-- the derived answer and its stated reason
SELECT e.qualified_name, ev.direction, ev.direction_reason, ev.visibility
FROM entity_versions ev JOIN entities e USING (entity_id)
WHERE ev.version_id = 'f1' AND e.qualified_name = 'statBumpPublic';

-- the facts it was derived FROM: which globals the function reads/writes
SELECT mode, dst_key AS global
FROM model_edges
WHERE version_id = 'f1' AND kind = 'global_access'
  AND src_key = 'Layer1.Diag|ClassStatics|statBumpPublic|';
```

### Call graph — callers and callees

```sql
-- who calls it (the impact direction, uses ix_edges_reverse)
SELECT src_key AS caller FROM model_edges
WHERE version_id = 'f1' AND kind = 'call'
  AND dst_key = 'Layer1.Diag|ClassStatics|statBumpPublic|';

-- what it calls
SELECT dst_key AS callee FROM model_edges
WHERE version_id = 'f1' AND kind = 'call'
  AND src_key = 'Layer1.Diag|ClassStatics|statBumpIndirect|';

-- transitive impact: everything that reaches X, up to 5 hops
WITH RECURSIVE up(key, depth) AS (
    SELECT 'Layer1.Diag|ClassStatics|statBumpPublic|'::varchar, 0   -- cast is required
  UNION
    SELECT me.src_key, up.depth + 1
    FROM model_edges me JOIN up ON me.dst_key = up.key
    WHERE me.version_id = 'f1' AND me.kind = 'call' AND up.depth < 5
)
SELECT key, min(depth) AS hops FROM up GROUP BY key ORDER BY 2;
```

### Globals — who writes what

```sql
SELECT dst_key AS global,
       count(*) FILTER (WHERE mode = 'write') AS writers,
       count(*) FILTER (WHERE mode = 'read')  AS readers
FROM model_edges
WHERE version_id = 'f1' AND kind = 'global_access'
GROUP BY 1 ORDER BY writers DESC;
```

### Diff two versions (what incremental should have seen)

```sql
WITH a AS (SELECT e.entity_key, ev.source_hash FROM entity_versions ev
           JOIN entities e USING (entity_id) WHERE ev.version_id = 'cs1'),
     b AS (SELECT e.entity_key, ev.source_hash FROM entity_versions ev
           JOIN entities e USING (entity_id) WHERE ev.version_id = 'cs2')
SELECT coalesce(a.entity_key, b.entity_key) AS entity_key,
       CASE WHEN a.entity_key IS NULL THEN 'added'
            WHEN b.entity_key IS NULL THEN 'removed'
            ELSE 'changed' END AS change
FROM a FULL OUTER JOIN b USING (entity_key)
WHERE a.entity_key IS NULL OR b.entity_key IS NULL
   OR a.source_hash IS DISTINCT FROM b.source_hash;
```

Zero rows = the two versions are byte-identical code, so 0 regenerated is correct, not a bug.

### Reuse is not happening — why?

```sql
-- the index is first-writer-wins per (project, fingerprint)
SELECT count(*) FROM reuse_index WHERE project_id = 'myproj';

-- a version only qualifies as a baseline once pipeline_status is terminal
SELECT id, version, pipeline_status, created_at FROM versions
WHERE project_id = 'myproj' ORDER BY created_at DESC;

-- how many of this version's entities could have matched an indexed fingerprint
SELECT count(*) FILTER (WHERE ri.fingerprint IS NOT NULL) AS matchable, count(*) AS total
FROM entity_versions ev
LEFT JOIN reuse_index ri ON ri.project_id = 'myproj' AND ri.fingerprint = ev.fingerprint
WHERE ev.version_id = 'f1';
```

### LLM — did the calls buy anything?

```sql
-- n is calls; outcome splits ok / empty / error. "1 in 3 empty" is the number that
-- catches replies being destroyed after arrival while token counts look healthy.
SELECT phase, kind, outcome, sum(n) AS calls,
       round(sum(latency_seconds)::numeric, 1)  AS secs,
       round(sum(throttle_seconds)::numeric, 1) AS throttled,
       sum(prompt_tokens) AS in_tok, sum(completion_tokens) AS out_tok
FROM llm_call_stats WHERE version_id = 'f1'
GROUP BY 1,2,3 ORDER BY calls DESC;

-- functions that came back with no description at all
SELECT count(*) FILTER (WHERE coalesce(b.payload->>'description','') = '') AS empty_desc,
       count(*) AS total
FROM entity_versions ev JOIN entities e USING (entity_id)
LEFT JOIN content_blobs b ON b.content_hash = ev.content_hash
WHERE ev.version_id = 'f1' AND e.kind = 'function';

-- an empty cache after an LLM run means every description is re-paid for next run
SELECT project_id, namespace, cache_version, count(*)
FROM llm_description_cache GROUP BY 1,2,3;
```

### Phase-3 output (what Phase 4 and the API read)

```sql
SELECT rel_path, group_name, length(content) FROM version_output_files
WHERE version_id = 'f1' ORDER BY length(content) DESC LIMIT 20;

-- read one file out
SELECT content FROM version_output_files
WHERE version_id = 'f1' AND rel_path = 'Layer1.Diag/interface_tables.json';
```

### Phase-1 skeleton (before LLM enrichment)

```sql
SELECT name, pg_size_pretty(length(payload::text)::bigint) FROM parse_snapshots
WHERE version_id = 'f1' ORDER BY length(payload::text) DESC;
-- names: functions.json, globalVariables.json, edges.json, hashes.json, dataDictionary.json,
--        entity_files.json, func_keys.json, override_pairs.json, address_taken.json, metadata.json
```

### Review — what a reviewer corrected

```sql
-- Every correction on a version: what the LLM wrote, what the document prints, and whether
-- its text still exists in this version (is_orphaned: carried forward, entity gone)
SELECT slot_kind, slot_key, is_orphaned, updated_by, updated_at,
       substr(llm_text, 1, 60) AS llm, substr(human_text, 1, 60) AS human
FROM text_overrides WHERE version_id = 'f1'
ORDER BY slot_kind, slot_key;

-- Would an export ship old wording? When each view was last derived, per component. A
-- correction newer than its own component's row, for a view its text reaches and the exported
-- document prints, is stale -- engine/review/export_guard.py decides which views those are
SELECT view_name, group_name AS component, derived_at
FROM view_derivations WHERE version_id = 'f1'
ORDER BY group_name, view_name;
SELECT slot_kind, slot_key, updated_at FROM text_overrides WHERE version_id = 'f1'
ORDER BY updated_at DESC;
```

### Review and approval — who approved what

```sql
-- A version's review: each document's state, its reviewer, who approved it and when
SELECT d.process, d.component, d.status, a.user_id AS reviewer,
       d.approved_by, d.approved_at, d.carried_from, left(d.docx_sha256, 12) AS docx
FROM documents d LEFT JOIN document_assignments a ON a.document_id = d.id
WHERE d.version_id = 'f1' ORDER BY d.component, d.process;

-- One document's review record, oldest first: the evidence an approval rests on
SELECT at, kind, actor_id, comment, payload
FROM document_review_events WHERE document_id = 'doc1a2b3c4d' ORDER BY at;
```

### Staged generation — which components, which run

```sql
-- A version's components: what each run asked for, how it went
SELECT component, state, requested_at, started_at, finished_at, error
FROM version_components WHERE version_id = 'f1' ORDER BY component;

-- Its latest run and how far it got (alive or not is the advisory lock, not this row)
SELECT command, pid, host, outcome, stage, done, total, progress_at, log_path
FROM version_runs WHERE version_id = 'f1';
```

### Integrity spot-checks

```sql
-- a content_hash with no blob reads back as an entity with NO payload
SELECT count(*) FROM entity_versions ev
LEFT JOIN content_blobs b ON b.content_hash = ev.content_hash
WHERE ev.content_hash IS NOT NULL AND b.content_hash IS NULL;

-- versions stuck mid-pipeline (silently skipped as a baseline => 0% reuse forever)
SELECT id, version, pipeline_status FROM versions
WHERE pipeline_status IS DISTINCT FROM 'complete';

-- dedup working? refs >> blobs means payloads are shared as intended
SELECT b.kind, count(*) AS blobs, sum(r.refs) AS refs
FROM content_blobs b
JOIN (SELECT content_hash, count(*) refs FROM entity_versions GROUP BY 1) r
  ON r.content_hash = b.content_hash
GROUP BY 1;
```

### Housekeeping

```sql
SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS total
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;

-- deleting a version cascades to all 14 per-version tables; entities/content_blobs survive
DELETE FROM versions WHERE id = 'f1';
```

Prefer [`tools/delete_project.py`](../../tools/delete_project.py) over hand-written `DELETE`s for a
whole project — it knows the order.

---

## Tables nothing writes

Declared in `schema.py`, created by the migrations, and **empty at runtime because no code path
inserts into them**. Do not read "0 rows" here as a bug:

| Table | Where the data actually is |
|---|---|
| `view_interface_tables` | `version_output_files`, as `<group>/interface_tables.json` |
| `view_behaviour_rows` | `version_output_files` |
| `model_unit_diagrams` | `version_output_files`, as `<group>/unit_diagrams/*.mmd` |
| `model_flowcharts` | `version_output_files` (PNG/DOCX binaries stay on disk, D-14) |
| `macro_definitions` | Per-layer macros come from config, not the DB |

---

## Use the tools first

Most debugging questions already have a script — these run the joins above and interpret the result:

| Tool | Question it answers |
|---|---|
| [`tools/check_db.py`](../../tools/check_db.py) | Is anything in the database inconsistent? (reports only findings; exit 1 = findings) |
| [`tools/dump_db.py`](../../tools/dump_db.py) | Dump everything (unreadable once a project is real — prefer `check_db`) |
| [`tools/audit_project.py`](../../tools/audit_project.py) | Whole-project health across model, views and documents |
| [`tools/why_unchanged.py`](../../tools/why_unchanged.py) | Why did incremental classify this entity as unchanged? |
| [`tools/why_private.py`](../../tools/why_private.py) | Why is this function `private` (and so absent from the interface table)? |
| [`tools/diagnose_incremental.py`](../../tools/diagnose_incremental.py) | Reuse / regeneration decisions for a run |
| [`tools/llm_stats.py`](../../tools/llm_stats.py) | LLM spend and outcome breakdown |
| [`tools/verify_pg_readers.py`](../../tools/verify_pg_readers.py) | Prove the data is really read from Postgres, not a disk fallback |
