# Fast Word-file updates — rebuild only what a correction changes

> Status: **built 2026-10-07** (branch `feat/fast-word-updates`), proposed 2026-10-06. It changes what
> an update *runs*. When a Word file is out of date, who may update it, the API and the screens stay
> as in [WORD_FILE_UPDATES.md](WORD_FILE_UPDATES.md). What a save does:
> [REVIEW_UPDATE_DESIGN.md](REVIEW_UPDATE_DESIGN.md). Decisions taken with the user: §9. Where the
> build departs from the proposal: §5, "Changed while building".

## 1. Result

Measured on Sample Core (28 flowcharts), as the web app runs an update (a detached job):

| After one correction of… | Before (develop) | Now | LLM calls in the update |
|---|---|---|---|
| a flowchart label | 237 s, Phase 3 for the whole component | **13–22 s, export only** — 91–94 % less | none |
| an input name, a unit description, a behaviour row | 189–227 s | 26–37 s | none |
| a description | 34 s — and the texts written from it kept the rejected wording | **26–36 s**, those texts rewritten | one per text written from it (11 for `statsAccumulate`) |

- A run reported on 2026-10-06 took 15 min for one label; the same update now takes about 15–30 s.
- No LLM text is written from a label, an input or output name, a unit, struct or behaviour
  description, so those updates call no LLM.
- **A description is different.** Other LLM texts are written from it (§4.1), and the update rewrites
  exactly those, then exports. The times above used a local stand-in LLM that answers at once; at the
  gateway's 3–6 s a call, `statsAccumulate`'s 11 calls add about 45 s. Most of the rest is drawing the
  three relabelled charts' pictures — new pictures, so no cache can hold them.
- **An update rewrites only the texts in its own components** (D3). A text in another component waits
  in the regeneration queue until that component is updated, or re-derived.
- The documents are the ones a full rebuild would make (§6).

## 2. Why an update was slow

The update after one label correction, measured on Sample Core (28 flowcharts, no LLM, a web update):

| Step | Time | Needed |
|---|---|---|
| start, restore the stored output to disk | 11 s | partly |
| behaviour diagrams: 2 redrawn (with the LLM on, every arrow's description asked again) | 23 s | no |
| unit diagrams: 3 redrawn | 26 s | no |
| flowcharts: graphs and labels | 2 s | no |
| flowcharts: 28 Word pictures redrawn | 142 s | 1 of 28 |
| export SWE.3 (its 2 Mermaid diagrams redrawn) + SWE.4 | 17 s | about 3 s of it |
| store, record | 5 s | yes |

Four causes:

1. **The save did the work but did not say so.** Before exporting, the update asks the export guard
   whether a stored view is older than a correction, and runs Phase 3 if so. The save already brought
   every stored copy up to date, but only a description save recorded it (2026-10-06e). For every other
   kind the guard played safe.
2. **A corrected chart's Word picture was drawn after the Word file was written.** The render job was
   drawn at the end of a run (`incremental/store._draw_pending_pictures`), so the guard had to send a
   label correction through Phase 3.
3. **The picture caches were per run.** `.dot_cache` (flowcharts) and `.mmdc_cache` (Mermaid) were
   looked up next to the code. A web or `--detach` run works from a code copy that leaves them out
   (`core/frozen_run._IGNORED`), so every run started empty and redrew every picture in a headless
   browser (5–12 s each). Behaviour diagrams bypassed the cache altogether.
4. **Behaviour call descriptions were not cached.** `CallDescriptionGenerator` asked the LLM for every
   arrow on every Phase 3, with the gateway's 3 s pause after each call — costing time, and changing the
   wording of rows nobody corrected.

And the update did not rewrite the texts written from a corrected description: only Phase 2 did
(`model_deriver._take_regeneration_queue`), and an update starts at Phase 3.

## 3. The idea

After a generation, everything a Word file needs is stored: the model, every view's output (database
rows) and every picture (files beside the version). A correction changes a few known pieces, and the
save already rewrites them in its own transaction. So the update only:

1. draws the picture a label correction changed, once;
2. rewrites, with the LLM, the texts in its components whose prompt contains a corrected description
   (§4.1);
3. rebuilds the Word files of the components the changes are printed in, from what is stored.

It runs no view the corrections did not change, redraws no unchanged picture, and calls the LLM only
for (2).

## 4. What each kind of correction changes

| Kind | Printed in | The save updates | The update then |
|---|---|---|---|
| `description` (function, global) | SWE.3: interface row, the function's table · SWE.4: its spec | model, `interface_tables.json` copies, SWE.4 specs and UT export | rewrites the texts written from it (§4.1, P5), exports SWE.3 + SWE.4 |
| `inputName`, `outputName` | SWE.3: the function's table and its behaviour tables | model — the exporter reads the model | exports SWE.3 |
| `unitDescription` | SWE.3: the unit section | model — the exporter reads the model | exports SWE.3 |
| `structDescription` | SWE.3: the unit header table of every unit that shows the type, in any component | model, and every stored `unit_headers.json` row of the type (P1) | exports SWE.3 of each component that shows it |
| `behaviourDescription` | SWE.3: that behaviour row | every stored copy of the `_behaviour_pngs.json` row | exports SWE.3 |
| `nodeLabel` | SWE.3: the chart's picture wherever it is printed · SWE.4: test steps, UT export | every stored copy of the flowchart JSON and DOT, web SVG, SWE.4 specs and UT export | draws the PNG, exports SWE.3 + SWE.4 |

- No picture other than a flowchart carries corrected text. Behaviour, unit and component diagrams show
  names only.
- An undo (R4) saves the original text, so it follows its kind's row.

### 4.1 LLM texts written from a corrected text

**The rule:** an update rewrites, with the LLM, every text whose prompt contains a corrected text, and
nothing else.

- **One level.** A rewritten text does not make the texts written from *it* rewrite (REQ-CS-02).
- **A reviewer's text is never rewritten** (REQ-CS-03). In a chart this holds node by node.

Read from the prompt builders, only descriptions are read by other prompts:

| A corrected… | is read by the prompt of… | Builder |
|---|---|---|
| function description `F` | the descriptions of `F`'s callers, callees and the other functions of its file | `llm_enrichment._build_function_context` (callees, callers, siblings), the repo map |
| | the descriptions of the globals `F` reads or writes, itself or through calls | `enrich_globals_rich` (read and write sites) |
| | the description of `F`'s unit | `get_unit_description` |
| | the behaviour rows `F` is in: their incoming call, or their call tree | `CallDescriptionGenerator._build_call_context`, `MermaidBuilder.build_diagram_for_caller` |
| | the node labels of `F`'s chart (its purpose), of its callees' charts, and of every chart that reaches `F` within 4 calls | `flowchart/pkb/builder` (purpose, callers, callee hierarchy), `flowchart/llm/generator` |
| global description `G` | the descriptions, and the input and output names, of the functions that reach `G` | `_build_function_context` (globals), `get_behaviour_names` |
| | the node labels of those functions' charts | `pkb/builder._build_global_context` |
| | the description of `G`'s unit | `get_unit_description` |

No prompt reads an input or output name, a unit, struct or behaviour description, or a node label.

**A row's incoming call is the LLM's too.** The behaviour view describes it from the caller it drew
the row for — and that caller is not always the row's `externalCallerId`: the selector takes callers
of callers, and the view pairs its i-th caller with the i-th direct caller from another component. So
a function's correction reaches the rows of every function it calls, directly or not.

**Exact, not approximate.** Prompts are trimmed to a token budget, so a far caller can fall out of one.
A candidate is rewritten only when its prompt really changes: the update builds the prompt's inputs
twice without the LLM, with every description correction taken back to its LLM original and as they
are, and compares the two.

Example, `gatewayMean`'s description, measured: the save queued 10 texts — the descriptions of
`statsAccumulate`, `statsAverage` (its callees) and `gatewayRecordSample` (same file), the `CoreGateway`
unit description, the Lib → `gatewayMean` behaviour row, and the charts of `gatewayMean`,
`statsAccumulate` and `statsAverage`; in Lib, `libMeanOf`'s description and chart (waiting, D3).

**What the code did before this:**

| Gap | Result | Now |
|---|---|---|
| `review/cascade.dependents_of` recorded a function's callers, unit and behaviour rows, and a global's unit | most texts written from a correction were never rewritten | the whole table (`cascade.dependents_of`, `_Graph`) |
| the knowledge base keeps the old description until Phase 2 rebuilds it, and the label and description prompts read it first | a rewrite would be given the old text | the model's descriptions laid over it when a prompt is built (P5) |
| the LLM cache keeps the old answer: writes are "on conflict do nothing", and the description and label keys do not contain these inputs | the next generation brings the old text back | a rewritten text replaces its cache entry (`EntityCache.replace`) |

## 5. The design, as built

### P1. The save finishes the data work

- **It stamps what it brought up to date**, as a description save has since 2026-10-06e: `flowcharts`
  after a label redraw, `behaviourDiagram` after a behaviour row, `unitHeaders` after a struct
  description. A stamp vouches for **every** stored copy (`export_guard.stamp_saved`), so the save
  rewrites every copy first (`rerender.redraw_flowchart`, `find_behaviour_rows`, `patch_unit_headers`).
  `viewsDerived` in the answer still names SWE.4 views only (API spec R8).
- **`inputName`, `outputName`, `unitDescription`: no view holds a copy.** The guard does not ask a view
  about them (`review/derive.copies_for`); `views_for` still answers which documents print them (R9).
- **`structDescription`:** every stored `unit_headers.json` row of the type gets the text
  (`rerender.patch_unit_headers`), and `unitHeaders` is stamped for those components; the guard judges
  a struct per component (`word_files.struct_placement`).

### P2. The update exports only

- The update judges with `pictures=False`: a corrected chart's picture still owed does not send it to
  Phase 3. It draws its components' owed pictures, under the version's writer lock, **before** it exports
  (`analyzer._draw_owed_pictures`, `render_queue.run_pending(components=…, retry_failed=True)`), into every
  stored copy's directory; run.py asks the guard again then.
- An export-only run restores only its own components' stored output (`run._restore_output_from_db`),
  and the guard judges only its components (`assert_exportable(components=…)`).
- **The fallback is unchanged.** Phase 3 + 4 still run for a component a newly added layer changed, a
  view no save could bring up to date, or a guard that cannot read the stamps. After P3 and P4 it costs
  seconds, not minutes.

### P3. Never redraw an unchanged picture

- `.dot_cache` and `.mmdc_cache` live under the data root (`utils.picture_cache_dir`), so every run
  shares them, frozen code copies included. Their writes are atomic (`utils.keep_picture`: a temporary
  file, then a rename).
- Behaviour diagrams go through the same cache (`views/behaviour_diagram.py`, keyed as
  `render_mermaid_cached` keys it).
- Not only for review: every generation, export, resume and fallback Phase 3 gains. Sample Core's
  Phase 3 + 4 took 20–24 s instead of 217 s.

### P4. Never ask the LLM again for an unchanged behaviour description

- `CallDescriptionGenerator` answers are cached by the whole prompt (`llm_enrichment._cached_desc`,
  `cache_material`): the two descriptions they are written from, the model and `llm.cacheVersion`.
- A corrected description changes the key, so exactly the calls written from it are asked again. Every
  other row keeps its words, and a re-run reproduces the document.

### P5. The update rewrites the texts written from a correction

A step of the update, before the export: `engine/review/rewrite.py`. `analyzer.py` runs it in its own
process, under the version's writer lock, after drawing the owed pictures — in every run that writes
Word files from the stored model (`_render_version`: `reexport`, and a staged generation's `export` and
`resume`); the API's in-process re-export runs it as `engine/review/rewrite.py`, a child process — the
step takes on a run's identity, whose project scopes the LLM caches, and the API's process serves every
project. With nothing queued in the run's components it returns before doing anything else
(`rewrite.queued`), so a generation's `export` is as before. A run that derives the model again
(`resume` of a run cut short in Phase 2, `reexport --from-phase 2`) skips it: Phase 2 rewrites the
queued descriptions itself, from the model it makes, and names and charts wait for the next update.

For each queued text of the update's components (D3; `rewrite.scope_components` turns a group or layer
scope into its components):

1. **Skip what must not be rewritten.** A reviewer's own text — retired (REQ-CS-03). A component with an
   approved document — left queued until it is reopened. A chart no stored document prints — retired.
2. **The prompt check.** The model is loaded twice — `then`, every description correction in force taken
   back to its LLM original, and `now` — with the knowledge base brought up to date with each
   (`pkb.knowledge.overlay_descriptions`). Each kind's prompt inputs are built from both and compared:
   `_build_function_context` under both passes' budgets, a global's read and write sites,
   `_iface_items_for_unit`, the name prompt's globals (only when the static names are poor, so the LLM
   is asked), a chart's context packet with its callees, a behaviour row call by call. A prompt that did
   not change retires its entry unchanged.
3. **Rewrite each with the generator that wrote it**, from the model as it is, descriptions first so a
   unit description is written from its functions' new ones:
   - a description: `enrich_functions_rich(regenerate=, only=)` — past the cache, these functions alone —
     or `enrich_globals_rich`;
   - a unit description: `get_unit_description`;
   - input and output names: Phase 2's static names, then `_enrich_behaviour_names_llm`; stored only
     when the LLM answered (it now says which functions it named), keeping a name a reviewer corrected;
   - a behaviour row: rebuilt as the view builds it (`generate_diagram_for_caller`, for the caller the
     view drew it for), each LLM call asked again only when its prompt moved — a call that did not keeps
     its stored words, and the call cache learns them;
   - a chart's labels: **the update's Phase 3** (below).
4. **Store each where Phase 2 or 3 does**, through the save's writers, in a transaction of its own under
   the version's save lock, after checking again that no reviewer corrected it meanwhile:
   `set_entity_field` + `patch_interface_tables` + each component's SWE.4 re-derive for a description,
   `set_unit_description`, `write_behaviour_row` on every copy; then the stamps. A text whose rewrite got
   no answer keeps its words and its entry.

**A chart's labels go to the update's Phase 3.** The step leaves the charts in a request file
(`rewrite.write_labels_request`), and the update runs `run.py --from-phase 3 --views
flowcharts,testSpecs,utExport --rewrite-labels <file>` instead of the export alone — all views when a
correction made meanwhile put another behind (`analyzer._with_label_rewrite`). There:

- `run_views --views` runs only those of the views the doc type needs; the derivation record keeps the
  others' entries, so their stamps stand. run.py restores only the update's components' stored output
  for it, as for an export: these views read their own directory.
- The flowcharts view charts the named functions alone (`flowchart_engine --rewrite-labels <request>
  --only-rewrite`) and splices them into the stored charts run.py restored, by `functionKey`
  (`_splice_rewritten`); every other file, the summary included, is put back. The corrected labels then
  go on top as in any Phase 3, and only the changed charts' pictures are drawn (the rest are cache hits).
- The engine skips the label cache for those charts, lays the model's descriptions over its knowledge
  base before the first chart it labels (`_with_current_descriptions`), and **replaces** the cache entry
  with the new labels (`_replace_labels`). A chart where the LLM fell back on a node keeps its earlier
  labels and is not reported. Each chart rewritten is appended to the request's report.
- The update retires the reported charts' entries once its output is **stored** (`rewrite.labels_done`):
  retired earlier, a failed capture would leave the queue saying stored charts were rewritten.

**Changed while building** — the proposal said:

| Proposed | Built | Why |
|---|---|---|
| draw a corrected label's Word picture right after the save, in the background | drawn by the update, before it exports | the saving host may hold no output tree; the update's process has it, under the writer lock, so a save and an update never draw it at once |
| the save updates the knowledge base's copy of a description | the model's descriptions laid over the knowledge base when a prompt is built | the knowledge base is one payload per version: rewriting it per sentence, and keeping it right through rewrites, costs more than laying the model over it where a prompt is built — and costs nothing when every chart is cached |
| a chart's labels rewritten by the flowchart engine "for that function only" | the update's Phase 3, the flowcharts and SWE.4 views alone | the engine needs the run's clang settings and the stored charts on disk, which Phase 3 already arranges |
| the behaviour row's incoming call is written without the LLM | it is the LLM's, from the caller the view drew the row for | read from `build_diagram_for_caller` while building |

### What stays

The API, R9, the screens, the locks and holds (WORD_FILE_UPDATES §4.6), the exporters and approval all
stay. An update is still a detached job per component; its code copy costs 0.5 s. A web update whose
components have texts queued shows the rewrite, and any charts' Phase 3, as Phase 3
(`pipeline_runner._rewrites_queued`); one with none shows Phase 3 as skipped, as before.

## 6. Why it is reliable

- **Nothing new writes a document, and no new prompt.** The save and the rewrite store rows through the
  functions Phase 2 and 3 use (`build_dot` via `redraw_flowchart`, `test_specs.build` via
  `swe4_rederive`, `apply_to_docx_rows`, the description builders, the flowchart engine). The Word files
  come from the same exporter as before.
- **The guard still decides.** Export-only happens only when every view the documents print is stamped
  current for that component. A save that could not bring a view up to date does not stamp it, and that
  component goes through Phase 3: slower, never wrong (REQ-AP-04).
- **The rewrite list is pinned to the prompts**, by tests: `test_review_cascade.py` (the candidates),
  `test_review_rewrite.py` (with a stub LLM: only texts whose prompt changed are asked; a reviewer's text,
  another component's and an approved one's stay; no answer keeps the words and the entry; a behaviour row
  keeps every unmoved call's words; the view splices only the charts the engine reported),
  `test_flowchart_label_cache.py` (a named chart skips the cache and replaces it; a fallback keeps the
  earlier labels).
- **Proved on Sample Core.**
  - P1–P4 (2026-10-06, no LLM), for a label on a printed chart, a description, an input name, a unit
    description and a behaviour row: the Word files from export-only equal a full Phase 3 + 4 rebuild
    (`tools/doccheck` clean at P4, the text of both documents identical, the new chart picture in and
    the old out).
  - P5 (2026-10-07), with a local stand-in LLM whose every answer is a hash of its prompt — so a text
    whose prompt changed comes back changed and one whose prompt did not comes back the same: the
    description of `gatewayMean` queued 10 texts; the update rewrote the 8 in Sample Core (3 descriptions,
    the unit description, 3 charts, the behaviour row — its 3 LLM bullets, its "returns to" bullets kept);
    Lib's 2 waited; both Word files printed the new texts; the next update found nothing to do.
- **Generation is as it was** (checked 2026-10-07c). Develop and this branch, side by side on the sample
  repo with the same stand-in LLM and hash seed: a fresh `generate` and an incremental one sent the same
  prompts — develop 5 more in the incremental run, behaviour calls the branch answered from its cache (P4)
  — and stored the same model and views; the 12 Word files have the same text and pictures. What differs
  is not in a Word file: fewer PNGs on disk (§10), a label cache that keeps every label, faster runs.

## 7. What was built

| Part | Where |
|---|---|
| P3: picture caches under the data root; behaviour diagrams through the cache | `engine/utils.py`, `engine/views/behaviour_diagram.py` |
| P1: stamps after every copy; `copies_for`; the struct patch, judged per component | `engine/review/override_service.py`, `rerender.py`, `derive.py`, `export_guard.py` |
| P2: pictures before the export, the guard per component, restore by component | `engine/review/render_queue.py`, `engine/run.py`, `analyzer.py`, `api/services/pipeline_runner.py`, `engine/core/model_store.py` |
| P4: the behaviour description cache | `engine/behaviour_diagram/llm_call_description.py` |
| P5: the whole map; the rewrite step; replacing cache writes; the names' answer; the knowledge base overlay; the new entries carried to the next version | `engine/review/cascade.py`, `engine/review/rewrite.py`, `engine/llm_core/cache.py`, `engine/core/db_util.py`, `engine/llm_enrichment.py`, `engine/model_deriver.py`, `engine/flowchart/pkb/knowledge.py`, `engine/review/carry_forward.py` |
| P5: the charts in Phase 3 | `engine/run.py` (`--views`, `--rewrite-labels`), `engine/run_views.py`, `engine/views/__init__.py`, `engine/views/flowcharts.py`, `engine/flowchart/flowchart_engine.py`, `engine/flowchart/config.py` |
| P5: wiring | `analyzer.py` (`_rewrite_queued`, `_with_label_rewrite`, `_labels_done`), `api/services/pipeline_runner.py`, `api/routes/text_overrides.py` (a chart's name in a save's answer), the web app's queue list (`flowchartLabels`) |
| Word pictures for the printed charts alone (§10) | `engine/docx_common.py` (the rule), `engine/docx_exporter.py`, `engine/views/flowcharts.py` |

## 8. Not chosen

| Option | Why not |
|---|---|
| The incremental engine | It saves parsing and LLM calls for unchanged code. A correction has neither. |
| Patching the .docx in place | It adds a second writer of the document, which must match the exporter forever. A component exports in seconds now. Revisit only if a large component's export is measured too slow. |
| A Phase 3 that runs only the stale views | After P1 nothing is stale after a correction. The update's own Phase 3 for rewritten charts runs only the flowcharts and SWE.4 views — those the rewrite changed, not those a guard calls stale. |
| Rewriting the whole chain below a correction | Unbounded in a deep call graph, and against the rule: only texts that read the corrected text (§4.1). |
| Rewriting only the direct neighbours' texts | Cheaper for a much-called function, but it leaves texts that read the correction unchanged. |

## 9. Decisions

Decided with the user, 2026-10-06:

| # | Decision |
|---|---|
| D1 | An update rewrites, with the LLM, the texts whose prompt contains a corrected text, and only those (§4.1, P5). |
| D2 | Behaviour descriptions are cached (P4). A re-generation keeps their wording; new wording comes when a description they are written from changes, or when `llm.cacheVersion` is raised. |
| D3 | An update rewrites only the texts in its own components. A text in another component waits in the regeneration queue for that component's next update, or for the next generation (P5). Changed the same day from "the update that publishes the correction rewrites it in any component", to keep an update inside its own components. |

Nothing is open. A dependent in a component with an approved document waits until the document is
reopened. That follows the approval rule (P5), not a new decision.

## 10. Also found

- **Only the printed charts get a Word picture** (built, 2026-10-07b). SWE.3 prints a public
  function's flowchart and its private callees' — on the Sample Core test, 4 of 28 — and Phase 3 drew all
  28 pictures, a rewrite every chart it relabelled. The flowcharts view now draws the pictures of the
  printed ones alone, by the exporter's own rule (`docx_common.printed_flowcharts`, which the exporter
  prints by), hidden functions counted; the others keep their graph, labels and web picture. Measured:
  4 pictures drawn where 28 were, the same Word file. A chart an incremental run carries is drawn when it
  is printed and its baseline drew none.
- **The Sample Core test's 4 of 28 is its setup.** App/Main.cpp and Hub/Hub.cpp call `coreAdd` and
  `coreOrchestrate`, but `#include "Sample/Core/Core.h"` needs `Layer1` as an include folder and the test
  project declares none ("Layer1 has NO include dirs"), so those calls are not seen and the Core
  functions count as uncalled from other files. Lib's `#include "../Core/CoreGateway.h"` resolves from
  its own folder. With include folders (the e2e config), 14 Sample Core functions are public.
- **The label cache lost a run's last minute of labels** (fixed, 2026-10-07). `EntityCache.put` writes a
  batch every 1,000 rows or 60 s, and the flowchart engine never flushed it at the end: every chart
  labelled in a run's last minute — all of them, on a run that took less — was labelled again by the
  next run, in new words. The engine flushes once every chart is labelled (`_flush_labels`).
- **An incremental run dropped the names and chart entries** (fixed, 2026-10-07c). A new version
  inherits the baseline's queue (`carry_forward.carry_queue`, REQ-CS-01), but by a rule that knew only
  the kinds queued before P5: a function's names and a chart's labels fell through and stayed on the
  baseline. No generation rewrites those texts, so the new version printed the words written from the
  rejected text, and nothing asked for them again. They now travel while their function is there; a
  names entry stays behind only when both names are a reviewer's.
