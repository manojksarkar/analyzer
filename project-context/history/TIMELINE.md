# Timeline — every dated change, one line each

> **Project context — the timeline.** Start at [PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md), the
> index. One line per dated change, newest first: its date tag, its headline (the entry's own
> words) and the file that holds it. Read this to know what changed and when; open the entry for
> the detail. **A new dated entry needs its line here** — `tests/unit/test_project_context_fits.py`
> fails until it has one.

## 2026-10

| Date | Change | File |
|---|---|---|
| 2026-10-05k | A project's repository can be a local path (a git repository's folder on the server): checks, a folder-listing route, `repositories.localRoots`; the mockup's switch and Browse panel | [13](13-2026-10-05c.md) |
| 2026-10-05j | The New Project wizard's branch is one box to search and pick in; the Get Started mockup follows the built Projects page | [13](13-2026-10-05c.md) |
| 2026-10-05i | Review & approval smoke-tested in a browser (7 of 7 steps); a `reviewer` membership is a developer in the web app; the Overview of a project it cannot read says so | [13](13-2026-10-05c.md) |
| 2026-10-05h | Web, from the review of 2026-10-05g: Compare's removed-document address, Compare's reads before the shown version is known, a pick made while a document loads, Esc in the reviewer menu | [13](13-2026-10-05c.md) |
| 2026-10-05g | Web: the reader re-rendered every section on each save (a memo that wrapped only the outer call) -- fixed; flowcharts fit the column and open full size; keyboard access; deep links follow the document's version; a re-export waits for R9 | [13](13-2026-10-05c.md) |
| 2026-10-05f | Web: seven UI-review leftovers closed -- no refetch on every visit, no cold-load flashes, no placeholder tabs, diffs not by colour alone, backticked text rendered, Compare deep links and a reference picker, the wizard keeps its step on reload; the Overview's runs are polled always | [13](13-2026-10-05c.md) |
| 2026-10-05e | Web: the review & update gaps the audit found are closed; orphans can be discarded; only the stale components' downloads are marked; version cards and the Overview say how runs were made and which are at work | [13](13-2026-10-05c.md) |
| 2026-10-05d | Proved with the LLM on: adding a layer asks the LLM only about the new layer | [13](13-2026-10-05c.md) |
| 2026-10-05c | R9 names the components whose documents are behind; `GET /projects/{pid}/runs` lists the runs at work from either front door | [13](13-2026-10-05c.md) |
| 2026-10-05b | Orphaned corrections can be discarded (R12); a correction no document prints no longer keeps a version stale; Phase 3 puts back a correction the model lost; Download All builds its ZIP on disk; `clean-runs`; the versions list says how each version was made | [11](11-2026-09-29e.md) |
| 2026-10-05 | The web app re-exports a version made from the command line, and only the stale components when asked; a save that meets a regenerating run says so with a code; RF-1 closed; only the layers the run's config has are offered | [11](11-2026-09-29e.md) |
| 2026-10-04f | A git command that does not finish is stopped: the API's and the engine's git runners have a time limit, kill the whole process tree, and never prompt | [11](11-2026-09-29e.md) |
| 2026-10-04e | A version takes components of another layer: `export` of one adds its layer to the same version -- every layer re-parsed, the LLM only for the new layer, the old layers' documents marked stale where the new layer changes them | [11](11-2026-09-29e.md) |
| 2026-10-04d | A private repository's token no longer travels in a URL; the config import is proved to ask the API a fixed number of times; the wizard no longer copies the whole folder tree on every keystroke | [11](11-2026-09-29e.md) |
| 2026-10-04c | The wizard's developer search no longer calls the API without end; a run's code copy waits out a file another process holds, and two runs started in one second no longer share a folder | [11](11-2026-09-29e.md) |
| 2026-10-04b | A database error no longer reaches the caller; a late cancel is finished on every path; a web re-export waits out a correction instead of refusing; a run's every engine tries a timed-out connection again; setup stamps only a migration it knows | [11](11-2026-09-29e.md) |
| 2026-10-04 | Background runs hardened after a review: a database blip at a run's end no longer deletes its work or leaves the job unfollowed; cancel, export and a recycled process id are safe; each version keeps its own config. Small API fixes: Globals count, the draft no longer takes over the project view, projects sorted, the last admin stays | [11](11-2026-09-29e.md) |
| 2026-10-02c | A web run goes on when the API restarts: it runs in the background like `--detach`, the API follows it and follows it again after a restart; a run that dies keeps its version for `resume` | [11](11-2026-09-29e.md) |
| 2026-10-02b | `analyzer.py generate` makes SWE.3 and SWE.4 by default (`--doc-type all`), like a web run | [11](11-2026-09-29e.md) |
| 2026-10-02 | Staged generation: one model per version, documents per component, any number of runs; a long run survives the API and code changes; one writer per version; `resume` after a crash | [11](11-2026-09-29e.md) |
| 2026-10-01e | People can be added: an invite makes an active member and creates the account when there is none; `analyzer.py user` and `tools/create_users.py` create accounts | [11](11-2026-09-29e.md) |
| 2026-10-01d | Review and approval: a document has one reviewer and is submitted, approved, sent back or reopened on the record; a version is approved when all its documents are; every version gets its documents recorded however it was made | [11](11-2026-09-29e.md) |
| 2026-10-01c | Mermaid diagrams render in the minlag/mermaid-cli docker image when it draws on the machine, else in local mmdc as before; `doctor` asks for one of the two | [11](11-2026-09-29e.md) |
| 2026-10-01b | Three things the 2026-09-30g merge checks found, fixed: pictures lost under load, jobs that said "running" for ever, and old versions' descriptions lost on re-export | [11](11-2026-09-29e.md) |
| 2026-10-01 | Review & update has a screen: the document reader's edit mode | [11](11-2026-09-29e.md) |

## 2026-09

| Date | Change | File |
|---|---|---|
| 2026-09-30i | A corrected flowchart label shows on the web page at once: R8 redraws the chart's SVG | [11](11-2026-09-29e.md) |
| 2026-09-30h | A re-export writes every document the version has, and R9 asks about all of them | [11](11-2026-09-29e.md) |
| 2026-09-30g | `integrate/ui-v5` merged develop — PR #70's review & update is on the web app's branch; the branch's 13 dated entries moved whole into file 12 | [11](11-2026-09-29e.md) |
| 2026-09-30f | Config import: core files are user inputs, filled from ONE folder pick in step 2; Import config moved to the top of step 1 | [12](12-2026-09-29-web-app.md) |
| 2026-09-30e | Web app CSS lowered for old browsers | [12](12-2026-09-29-web-app.md) |
| 2026-09-30d | `tools/copy_changes.py` — copy this repo's changes into the office project, deletions included | [12](12-2026-09-29-web-app.md) |
| 2026-09-30c | `start-app` — one command that starts the API + web app cleanly | [12](12-2026-09-29-web-app.md) |
| 2026-09-30b | Flowcharts in the web app are server-drawn SVGs | [12](12-2026-09-29-web-app.md) |
| 2026-09-30 | The PR #70 review: the seven must-fix items fixed, the whole review feature passes on PostgreSQL, and fifteen follow-ups are BACKLOG RF-1…RF-15 | [11](11-2026-09-29e.md) |
| 2026-09-30 | SWE.4 in the web app, end to end; overnight test projects; round-1 UI review fixes | [12](12-2026-09-29-web-app.md) |
| 2026-09-29f | `tools/review_api_test/` tests the whole review feature through the REST API; its first run found a re-export that rebuilt only the first group of a version generated for several | [11](11-2026-09-29e.md) |
| 2026-09-29f | Run Analysis: any mix of components, and Skip LLM, under Advanced options | [12](12-2026-09-29-web-app.md) |
| 2026-09-29f | New Project wizard: onboarding UX pass | [12](12-2026-09-29-web-app.md) |
| 2026-09-29e | Every review route gives a slot one shape — `text`, `llmText`, `humanText`, `isOverridden`, `isOrphaned`, `canUndo`, `updatedBy`, `updatedAt` — and every save answers with the slot as it now is; R8 returns each saved node and the rebuilt DOT | [11](11-2026-09-29e.md) |
| 2026-09-29e | The SWE.3 page in the web app reads like the DOCX | [12](12-2026-09-29-web-app.md) |
| 2026-09-29d | The review of every review & update flow, and its ten fixes: a save writes one row and saves of a version take turns; the regeneration queue is paid where each text is written, and travels to the next version; an orphan is no correction; a 4xx is the caller's fault | [10](10-2026-09-26.md) |
| 2026-09-29d | Onboarding is per core, as the engine is: a project has cores (macros, data dictionary, compile commands each) and every layer picks one | [12](12-2026-09-29-web-app.md) |
| 2026-09-29c | R7 and R8 name a flowchart by its function id, `flowchart_id`, in the query and the body -- not a base64 token in the path | [10](10-2026-09-26.md) |
| 2026-09-29c | Every component path is checked, from the wizard to the run, and a run stops BEFORE the parse on a component that gets no file | [12](12-2026-09-29-web-app.md) |
| 2026-09-29b | Rebased onto develop `5542736` as branch `review_update_v3`: develop's six commits bring no new LLM text; one thing to decide — doccheck's pair check reads the behaviour bullets a reviewer can rewrite (RU-6) | [10](10-2026-09-26.md) |
| 2026-09-29b | A config file in and out of the web app: Import config in the New Project wizard, Download config on a project | [12](12-2026-09-29-web-app.md) |
| 2026-09-29 | The export guard asks per view, component and document; a saved correction re-derives the SWE.4 specs; the restore before a run finally runs | [10](10-2026-09-26.md) |
| 2026-09-29 | The web app works end to end on develop again — branch `ui_v2`, cut from develop `5542736`; local commits only, NOT pushed, NOT merged (user reviews first) | [12](12-2026-09-29-web-app.md) |
| 2026-09-28b | A new session now meets the changes the numbered sections do not describe | [10](10-2026-09-26.md) |
| 2026-09-28 | `PROJECT_CONTEXT.md` is an index now; the content is in `project-context/` | [10](10-2026-09-26.md) |
| 2026-09-27d | Context files, skills and the merge handover brought up to date for `review_update_v2` — docs and comments only, no behaviour change | [10](10-2026-09-26.md) |
| 2026-09-27c | Checked against Manoj's written rules, and one more place where a version id crossed projects: a web job's baseline | [10](10-2026-09-26.md) |
| 2026-09-27b | The open points from the rebase review, fixed: a `layer:` scope produces documents again; the document page shows the unit description; every R11 row… | [10](10-2026-09-26.md) |
| 2026-09-27 | `review_update_v2` verified line by line against both branches, and develop's struct/class/union descriptions made fully reviewable: R11 offers only… | [10](10-2026-09-26.md) |
| 2026-09-26f | Review & update rebased onto develop as branch `review_update_v2`: develop's one new LLM text -- the struct/class/union description in the unit… | [10](10-2026-09-26.md) |
| 2026-09-26e | Corrections now survive the next version and a Phase-2 re-derive -- unit, struct and behaviour-name corrections were lost -- and a correction to code… | [10](10-2026-09-26.md) |
| 2026-09-26d | A re-export is a job of its own, addressed by version: its status goes queued -> running -> complete \| failed, one runs at a time per version, and… | [09](09-2026-09-24.md) |
| 2026-09-26c | The review routes never checked that the version in the path belongs to the project in the path. An unknown id looked like an empty version; another… | [09](09-2026-09-24.md) |
| 2026-09-26b | A sign-in lasts a working day, not 15 minutes -- and the server can set it | [09](09-2026-09-24.md) |
| 2026-09-26 | Every run started from the web app failed at once -- and once it could start, it hung for ever on SQLite. Both fixed. A CLI-onboarded project is now… | [09](09-2026-09-24.md) |
| 2026-09-26 | doccheck v2 — five levels, P1–P4 priorities, one report for every check | [10](10-2026-09-26.md) |
| 2026-09-25b | Is a corrected flowchart shown from the database? Its DOT is, its picture is not. R7 now returns the DOT, and the API spec has the UI flows (§3a) | [09](09-2026-09-24.md) |
| 2026-09-25b | a static member reached through an object is a global use; a brace in an inline body's literal no longer eats members | [10](10-2026-09-26.md) |
| 2026-09-25 | undo and history of a flowchart label were unusable from Swagger; the superuser flag was only half applied; and when each correction becomes VISIBLE… | [09](09-2026-09-24.md) |
| 2026-09-25 | a unit header declaration is read until its braces close | [10](10-2026-09-26.md) |
| 2026-09-24g | A run says what it will do before it parses | [09](09-2026-09-24.md) |
| 2026-09-24f | A CLI version id is a name inside its project | [09](09-2026-09-24.md) |
| 2026-09-24e | check-llm speaks Ollama | [09](09-2026-09-24.md) |
| 2026-09-24e | `llm.sslVerify` (6edfcd3) REVERTED. The "unable to get local issuer certificate" failure is not a trust problem in the client: `tools/check_llm.py`… | [09](09-2026-09-24.md) |
| 2026-09-24d | doccheck counts functions and globals apart, and explains an RV-4 move | [09](09-2026-09-24.md) |
| 2026-09-24c | S3-7 — a global earns its interface row from a user in ANOTHER unit | [09](09-2026-09-24.md) |
| 2026-09-24c | re-export could not find a version's source, and told the user to regenerate: a full LLM run to recover at most a git checkout | [09](09-2026-09-24.md) |
| 2026-09-24b | RV-4 — an orphan header is listed ONCE, by one owner unit | [09](09-2026-09-24.md) |
| 2026-09-24b | `--use-model` refused every version whose scope has no global variables — so no `reexport`, including the `--from-phase 3` a corrected document needs | [09](09-2026-09-24.md) |
| 2026-09-24 | RV-6 — the unit diagram draws the unit's published globals | [09](09-2026-09-24.md) |
| 2026-09-24 | `generate --unit` failed before parsing with "Units in scope: (none)". `--selected-unit` is now validated where it is consumed — Phase 3 — except… | [09](09-2026-09-24.md) |
| 2026-09-23f | firmware-team SWE.3 review, round 1: tracked in docs/BACKLOG.md as RV-1…RV-7 | [08](08-2026-09-21.md) |
| 2026-09-23e | doccheck caught up with `147c4cd`'s unit header table | [08](08-2026-09-21.md) |
| 2026-09-23c | doccheck's terminal report redrawn for reading | [08](08-2026-09-21.md) |
| 2026-09-23b | struct / class / union are listed in the unit header table, and the client answered the whole question list | [08](08-2026-09-21.md) |
| 2026-09-23 | the unit header table is no longer filtered by visibility, and a declaration is no longer an interface | [08](08-2026-09-21.md) |
| 2026-09-23 | three defects in the listings, found by answering "when do I get text, llmText and humanText?" -- the question made me check rather than recall | [08](08-2026-09-21.md) |
| 2026-09-22e | a real project reported `nodeCount: 0` on every flowchart and an empty R7 label list. NOT a bug in the listing — the stored output predates `cfg` | [08](08-2026-09-21.md) |
| 2026-09-22d | walking the flowchart-label UI flow end to end found two defects and a wrong spec. None of 2191 tests caught any of them | [08](08-2026-09-21.md) |
| 2026-09-22c | R11 `GET .../slots` — what CAN be edited. `REQ-API-01`'s other half, which I had under-delivered | [08](08-2026-09-21.md) |
| 2026-09-22b | publication is now judged per UNIT, not per file | [08](08-2026-09-21.md) |
| 2026-09-22b | `users.is_superuser` — an operator account that reaches every project. Migration 0014 | [08](08-2026-09-21.md) |
| 2026-09-22 | `tools/doccheck/` — compare two generated documents by what they say | [08](08-2026-09-21.md) |
| 2026-09-22 | a CLI-onboarded project was unreachable over HTTP. Two defects in the seam between the two front doors, found by the first Swagger session on the… | [08](08-2026-09-21.md) |
| 2026-09-21e | the Static Design component container diagram is page-fitted, and its box styling is uniform | [06](06-2026-09-06.md) |
| 2026-09-21d | SWE.3 and SWE.4 now ask the same question about an external caller | [06](06-2026-09-06.md) |
| 2026-09-21b | SWE.4 prints the class-qualified method name | [08](08-2026-09-21.md) |
| 2026-09-21 | re-export could not find a version's checkout | [07](07-2026-09-18.md) |
| 2026-09-21 | `analyzer.py setup` could not upgrade a database that already existed. Found on the first real Postgres install, by a run dying mid-Phase-1 | [07](07-2026-09-18.md) |
| 2026-09-21 | oversize flowchart PNGs were half-painted, silently | [08](08-2026-09-21.md) |
| 2026-09-20c | review_update_v1 - the API spec now carries a full request/response contract per endpoint, and it was documenting a wire format the server does not… | [07](07-2026-09-18.md) |
| 2026-09-20b | review_update_v1 - a second audit, this time against the PIPELINE rather than against the feature's own tests. All 43 requirements are met; three… | [07](07-2026-09-18.md) |
| 2026-09-20 | visibility reworked: protected is private, methods read their C++ access, and a `PUBLIC` marking no longer guarantees a row | [07](07-2026-09-18.md) |
| 2026-09-20 | review_update_v1 - the feature run END TO END on SQLite, and the ordering bug that only a real run could find | [07](07-2026-09-18.md) |
| 2026-09-19e | review_update_v1 - a spec-vs-code audit, and its four fixes | [07](07-2026-09-18.md) |
| 2026-09-19d | review_update_v1 step 9 - `REQ-PRE-02`, the export path | [07](07-2026-09-18.md) |
| 2026-09-19c | review_update_v1 - both queues are now DRAINED by a run | [07](07-2026-09-18.md) |
| 2026-09-19b | review_update_v1 - the pipeline now CALLS the feature | [07](07-2026-09-18.md) |
| 2026-09-19 | review_update_v1 step 8 - carry-forward; `slot_shape` finally has a reader | [07](07-2026-09-18.md) |
| 2026-09-18f | review_update_v1 step 7 - images | [07](07-2026-09-18.md) |
| 2026-09-18e | review_update_v1 step 6 - the cascade, recorded rather than run | [07](07-2026-09-18.md) |
| 2026-09-18d | review_update_v1 - HTTP tests for the review API, and the two defects they found | [07](07-2026-09-18.md) |
| 2026-09-18c | review_update_v1 step 5 - the HTTP API and undo | [07](07-2026-09-18.md) |
| 2026-09-18b | review_update_v1 step 4 - the export guard; plus a merge handover doc | [07](07-2026-09-18.md) |
| 2026-09-18 | a static member written through a FIELD is now covered | [06](06-2026-09-06.md) |
| 2026-09-18 | DB debugging reference added — docs/design/DB_SCHEMA.md | [06](06-2026-09-06.md) |
| 2026-09-18 | review_update_v1 steps 3b + REQ-API-08 built; behaviourDescription now has a save path, and its slot key had a collision | [06](06-2026-09-06.md) |
| 2026-09-17d | review_update_v1 - how the two non-model kinds are corrected | [06](06-2026-09-06.md) |
| 2026-09-17c | review_update_v1 — the flowchart API becomes flowchart-wise, not label-wise | [06](06-2026-09-06.md) |
| 2026-09-17b | review_update_v1 step 3 — the override service | [06](06-2026-09-06.md) |
| 2026-09-17 | review_update_v1 step 2 — slot storage + addressing; and REQ-ID-02's justification was wrong | [06](06-2026-09-06.md) |
| 2026-09-16 | unit and struct descriptions move out of the DOCX exporter into Phase 2 and become stored data | [06](06-2026-09-06.md) |
| 2026-09-10 | the project-directory walk is no longer an include-path source by default | [06](06-2026-09-06.md) |
| 2026-09-08 | Re-onboarding a version id now updates its commit sha | [05](05-2026-08-25.md) |
| 2026-09-07 | One run may now span several layers | [06](06-2026-09-06.md) |
| 2026-09-06 | a flush deleted the artifacts it was not handed; the audit's model checks did not know about hash-only rows | [05](05-2026-08-25.md) |
| 2026-09-06 | Group and component identity is LAYER-QUALIFIED | [06](06-2026-09-06.md) |
| 2026-09-05c | `tools/audit_project.py` - a read-only audit of what a project stored and every invariant the incremental design relies on | [05](05-2026-08-25.md) |
| 2026-09-05b | phase summaries named model JSON files that are not written; the SWE.4 cover page read "Software Project" | [05](05-2026-08-25.md) |
| 2026-09-05 | a NUL character in one description killed Phase 2 after the whole LLM run had been paid for | [05](05-2026-08-25.md) |
| 2026-09-02 | `compile_commands.json` ingest — INCLUDE PATHS ONLY, first cut | [05](05-2026-08-25.md) |
| 2026-09-01b | SWE.4 ported onto the DB-native pipeline; explicit `PUBLIC` was being ignored | [05](05-2026-08-25.md) |
| 2026-09-01 | `llm_call_stats` timing columns were dead everywhere; `alembic upgrade head` cannot build a fresh DB (KNOWN, deliberately NOT fixed) | [05](05-2026-08-25.md) |

## 2026-08

| Date | Change | File |
|---|---|---|
| 2026-08-29 | a missing baseline `address_taken` snapshot silently made pointer-table functions private | [04](04-2026-08-18.md) |
| 2026-08-25b | the flowchart engine was rendering the WHOLE version for every component | [05](05-2026-08-25.md) |
| 2026-08-25 | re-derive without re-parsing; unit narrowing made to work | [04](04-2026-08-18.md) |
| 2026-08-24e | re-export left the database holding the OLD render | [04](04-2026-08-18.md) |
| 2026-08-24d | generate reads branch and commit from the database | [04](04-2026-08-18.md) |
| 2026-08-24c | phase-level flexibility confirmed intact and exposed | [04](04-2026-08-18.md) |
| 2026-08-24b | `--unit` reaches the pipeline; re-export stopped changing the document set | [04](04-2026-08-18.md) |
| 2026-08-24 | one CLI: `analyzer.py` | [04](04-2026-08-18.md) |
| 2026-08-23 | poc-4 merged onto the DB architecture; the file backing removed | [04](04-2026-08-18.md) |
| 2026-08-22b | behaviour diagram package replaced + LLM path rewired | [04](04-2026-08-18.md) |
| 2026-08-22 | the CSV-failing-silently work rebased onto the per-layer data dictionary | [04](04-2026-08-18.md) |
| 2026-08-21b | incremental: a `--data-dictionary` CSV never reached an incremental run's model | [04](04-2026-08-18.md) |
| 2026-08-21 | `tools/check_data_dictionary_csv.py` — pre-flight validator for the `--data-dictionary` CSV, written while diagnosing "all SWE.3 data ranges are NA"… | [04](04-2026-08-18.md) |
| 2026-08-18 | Per-layer data dictionary — closes backlog SH-3 | [04](04-2026-08-18.md) |
| 2026-08-14 | doc 09 Phase 0/1 + B5a + C1 + B1(output) landed | [03](03-2026-08-03.md) |
| 2026-08-13 | `clang.clangArgs` is now a discoverable config key — the fix for cross-target parse errors like `use of undeclared identifier '__builtin_arm_wfi'` | [03](03-2026-08-03.md) |
| 2026-08-13 | PG-7b cutover COMPLETE — Postgres is the source of truth | [03](03-2026-08-03.md) |
| 2026-08-12c | Phase 1 parse diagnostics — a log trail for "why is this function missing from `model/functions.json`?" | [03](03-2026-08-03.md) |
| 2026-08-12b | LLM observability: every call is now timed and attributed to a pipeline stage | [03](03-2026-08-03.md) |
| 2026-08-12 | the OpenAI gateway throttle is now a config key, `llm.rateLimitSeconds` | [03](03-2026-08-03.md) |
| 2026-08-11 | `run.py` rejects unknown options and stray positionals instead of ignoring them | [03](03-2026-08-03.md) |
| 2026-08-10 | flowchart labels: every call is named, always as `Name()` | [03](03-2026-08-03.md) |
| 2026-08-10 | storage cutover, reader half — PG-5a/5b/7a | [03](03-2026-08-03.md) |
| 2026-08-09 | config redesign — three sources, three roles | [02](02-2026-07-01.md) |
| 2026-08-07 | macro ingestion: JSON input + per-layer scoping + the API/UI path that was silently dropping defines | [03](03-2026-08-03.md) |
| 2026-08-03c | data ranges now measured by libclang instead of guessed from type names | [03](03-2026-08-03.md) |
| 2026-08-03b | root cause of the `NA` Data Range column: typedefs never recorded what they alias | [03](03-2026-08-03.md) |
| 2026-08-03 | data-dictionary range lookup: `"NA"` now means "unknown", not an answer | [03](03-2026-08-03.md) |

## 2026-07

| Date | Change | File |
|---|---|---|
| 2026-07-29 | flowchart node labels are word-wrapped (branch `fix/flowchart-issue`) (status-board note) | [status boards](STATUS_BOARDS.md) |
| 2026-07-28 | flowchart engine console output cleaned up (branch `fix/flowchart-issue`) (status-board note) | [status boards](STATUS_BOARDS.md) |
| 2026-07-27 | flowcharts now render with Graphviz, not Mermaid (branch `fix/flowchart-issue`) (status-board note) | [status boards](STATUS_BOARDS.md) |
| 2026-07-23 | docs restructure + agent role-skills | [02](02-2026-07-01.md) |
| 2026-07-23 | SWE.4 test-case generation methods scoped | [02](02-2026-07-01.md) |
| 2026-07-22 | SWE.4 unit-test-spec generation — discovery + design locked; implementation plan approved | [02](02-2026-07-01.md) |
| 2026-07-22 | engineering backlog gets a home: `docs/BACKLOG.md` | [02](02-2026-07-01.md) |
| 2026-07-21 | planning docs made leadership-facing + consolidated | [02](02-2026-07-01.md) |
| 2026-07-21 | 3.23 conditional `#define` shows both branches (DONE) (status-board note) | [status boards](STATUS_BOARDS.md) |
| 2026-07-21 | e2e test suite resurrected + snapshots regenerated (DONE, test-only) (status-board note) | [status boards](STATUS_BOARDS.md) |
| 2026-07-20 | unit-header value-column batch (3.20–3.22) (status-board note) | [status boards](STATUS_BOARDS.md) |
| 2026-07-19 | second V1 correctness batch logged (3.11–3.19) from client/office review — all ADDITIONS, nothing reversed | [02](02-2026-07-01.md) |
| 2026-07-18 | V1-fixes status reconciled + flowchart-in-DOCX verified resolved | [02](02-2026-07-01.md) |
| 2026-07-17 | multi-line `#define` value no longer truncated in the unit-header table | [02](02-2026-07-01.md) |
| 2026-07-17 | orphan-header symbols surface in the using unit's header table | [02](02-2026-07-01.md) |
| 2026-07-16 | fix 3.6 — unit-diagram edges oriented by the interface owner's In/Out | [02](02-2026-07-01.md) |
| 2026-07-15 | fix 3.4 — interface direction from transitive global writes | [02](02-2026-07-01.md) |
| 2026-07-15 | fixes 3.1 + 3.2 — parser scope: exclude emulator files, parse headers | [02](02-2026-07-01.md) |
| 2026-07-15 | fix 3.5 — interface-table Source/Destination lists all non-self units (REQ-IT-12) | [02](02-2026-07-01.md) |
| 2026-07-12 | docs: web-app context doc relocated + mockups dir flattened | [02](02-2026-07-01.md) |
| 2026-07-11 | engine folder renamed `backend/` → `engine/` | [02](02-2026-07-01.md) |
| 2026-07-11 | folder restructuring — engine consolidated under `engine/` | [02](02-2026-07-01.md) |
| 2026-07-10 | pre-V1 correctness batch logged | [02](02-2026-07-01.md) |
| 2026-07-02 | brand: ArtiFex product mark (logo icon) | [02](02-2026-07-01.md) |
| 2026-07-01 | fix — compare view showed no changes | [01](01-2026-06-22.md) |
| 2026-07-01 | fix — explicit incremental baseline ignored | [01](01-2026-06-22.md) |
| 2026-07-01 | fix — flowcharts never generated | [01](01-2026-06-22.md) |
| 2026-07-01 | Documents page now has a SWE.2 filter and shows real docs under SWE.2 | [01](01-2026-06-22.md) |
| 2026-07-01 | docs now re-scope on commit/version switch (#5) | [01](01-2026-06-22.md) |
| 2026-07-01 | Run Analysis modal — "Start Analysis" stayed disabled when the commit list loaded *after* the modal opened | [01](01-2026-06-22.md) |
| 2026-07-01 | design mockups: added `docs/ui-mockups/projects-portfolio.html` — the main Projects screen as seen by a new org-level role above project admin… | [01](01-2026-06-22.md) |
| 2026-07-01 | new-project wizard Step 3 folder tree was slow to appear | [01](01-2026-06-22.md) |
| 2026-07-01 | new tool — import a viewable project from existing analyzer output, no pipeline re-run | [02](02-2026-07-01.md) |
| 2026-07-01 | UI — job phase stepper: removed the "Phase N" ordinal, promoted the step name | [02](02-2026-07-01.md) |
| 2026-07-01 | brand — enlarged the ArtiFex lockup in the web app | [02](02-2026-07-01.md) |
| 2026-07-01 | fix — commit sha shown as the project name in the DOCX cover + 1.1 Purpose/Scope | [02](02-2026-07-01.md) |
| 2026-07-01 | product name locked = ArtiFex | [02](02-2026-07-01.md) |
| 2026-07-01 | fix — wide Document Inspector sections (Interface Table) were clipped/invisible | [02](02-2026-07-01.md) |
| 2026-07-01 | fix — sliced (tall) flowcharts rendered as mermaid text, no image, in the web UI | [02](02-2026-07-01.md) |
| 2026-07-01 | fix — generated design docs reclassified SWE.2 → SWE.3 | [02](02-2026-07-01.md) |

## 2026-06

| Date | Change | File |
|---|---|---|
| 2026-06-30 | dashboard document numbers scoped to the latest version (#4) | [01](01-2026-06-22.md) |
| 2026-06-30 | loaders / no empty-state flash (#3) | [01](01-2026-06-22.md) |
| 2026-06-30 | JSONC base config (#7). `api/services/pipeline_runner.py::_write_project_config` parsed the base `engine/config/config.json` with plain `json.load` | [01](01-2026-06-22.md) |
| 2026-06-30 | layer-config conversion now preserves the wizard's per-file/per-folder selection (#6) | [01](01-2026-06-22.md) |
| 2026-06-30 | new commits now sync on every commit-list view (#2) + "last synced" shown in picker | [01](01-2026-06-22.md) |
| 2026-06-30 | offline Material Symbols font (#1) | [01](01-2026-06-22.md) |
| 2026-06-30 | fix new-project wizard branch/tree mismatch — selecting a non-default branch in Step 1 still showed the default branch's folder structure in Add… | [01](01-2026-06-22.md) |
| 2026-06-30 | fix new-project wizard Step 4 "developers vanish after create" + team UI cleanup | [01](01-2026-06-22.md) |
| 2026-06-27 | fix compare page rendering raw JSON — `api/services/compare_engine.py` `compute_document_sections_diff` was serialising raw `interface_tables.json`… | [01](01-2026-06-22.md) |
| 2026-06-27 | React app now lives in `web-app/` (was `frontend/app/`) and is wired to the live FastAPI API (§19) via typed mappers/hooks | [01](01-2026-06-22.md) |
| 2026-06-23 | all five inner React pages — `ProjectDetailPage`, `DocumentsPage`, `ComparePage`, `VersionsPage`, `TeamPage` — rebuilt as faithful 1:1 ports of their… | [01](01-2026-06-22.md) |
| 2026-06-23 | version4 — Incremental Changes feature design + foundations: backend adapted to main's `layers`/`component` schema | [01](01-2026-06-22.md) |
| 2026-06-22 | feat/frontend-app branch created from `main` | [01](01-2026-06-22.md) |
