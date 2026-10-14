# Pipeline speed — measured, prototyped, planned

> Branch `perf/pipeline-speed` (from develop `369a2a1`, 2026-10-08; rebased onto develop `8d438de`,
> 2026-10-12), not merged. Every number here was
> measured on `SampleCppProject` (218 translation units, 385 functions, 25 components) against a stand-in
> LLM (`tools/perf/llm_standin.py`) that behaves like the office gateway, scaled down: 0.3 s per answer,
> one call per key at a time, calls on a key at least ~0.3 s apart (the office: 3–6 s, 3 s). How to
> reproduce: §7. What only the office can tell us: §6.

[1 Where the time goes](#1-where-the-time-goes) · [2 The levers](#2-the-levers) ·
[3 What was built, and how it was checked](#3-what-was-built-on-the-branch-and-how-it-was-checked) ·
[4 Edge cases](#4-edge-cases) · [5 Plan](#5-plan) · [6 Questions for the office](#6-questions-only-the-office-can-answer) ·
[7 Reproduce](#7-reproduce)

## 1. Where the time goes

**The LLM is the office's bottleneck.** The sample makes **762 LLM calls in Phase 2** (≈2 per function)
and **≈6 per function in Phase 3** (flowchart labels). Today every call is followed by a 3 s pause, one
call at a time, so each costs *its answer time + 3 s*:

| | Calls per function | Office cost per call today | ~1,500 functions |
|---|---|---|---|
| Phase 2 (descriptions, names, globals, structs, units) | ≈2 | 6–9 s | **5–8 h** (matches the reported 10 h with Phase 1) |
| Phase 3 flowchart labels (one call per 4 nodes + coherence) | ≈6 | 6–9 s | **15–22 h** — why staged runs take days |

| Phase 2 stage (sample) | Calls |
|---|---|
| function descriptions | 330 |
| input/output names | 310 |
| globals | 54 |
| structs | 42 |
| units | 26 |

**Without the LLM**, on the sample (instant stand-in):

| Phase | Time | What dominates |
|---|---|---|
| 1 Parse | 19.7 s | Python walking the AST (≈2/3: six full walks per file, 8 s) — libclang's own parse ≈1/3; every file parsed twice; 104 of 218 files are headers parsed on their own though a `.cpp` already included them |
| 2 Derive (no LLM) | ≈6 s | — |
| 3 Views, per component | 57–143 s | **pictures**: a new headless browser per picture (≈9.5 s each here); unit diagrams, behaviour diagrams, and with `views.flowcharts` on, every flowchart PNG |
| 4 Export, per component | 24–32 s | the two component diagrams, drawn again at export |

## 2. The levers

Ranked by what they save at the office. **Same output** = byte-identical model / views / pictures,
checked as described in §3.

| # | Lever | Saves | Same output | Risk | State |
|---|---|---|---|---|---|
| L1 | **Start pacing**: the gateway's gap counted from a call's *start*, not after it ends | each call max(answer, 3 s) instead of answer + 3 s: **1.5–2×** on LLM time, same key | yes | low | built, opt-in |
| L2 | **Several keys/endpoints (lanes)** with failover on 429/503/timeout | **×keys** on LLM time | yes (same model on every lane) | medium: gateway policy (§6) | built, opt-in |
| L3 | **Calls in parallel inside a stage** (how many: what the lanes allow, not a setting): names, globals, structs, units, flowchart labels per function; descriptions by call-graph round | lets L1/L2 work — one call at a time can use only one lane | yes | low–medium (threads) | built; follows the lanes |
| R1 | **One browser for many pictures** (Mermaid batch) | ≈4–5× a diagram; with R2, Phase 3 **3.5×** and the SWE.3 export **1.6×** on a component, cold caches (§3) | **yes, byte-identical PNGs** | low | built; wired for unit diagrams and the export's two component diagrams (behaviour diagrams next) |
| R2 | Same for flowchart PNGs (`render_dot.mjs` starts a browser per chart) | **5.4×**: 1.8 s a chart vs 9.8 s — hours on a 500-chart document | **yes, byte-identical PNGs** | low | built and wired (chunks of 50) |
| P1 | **Parse ahead on threads** | Phase 1 **−24 %** (16.2 → 12.3 s, best of 3; only the parse overlaps, the Python walk stays) | **yes** (model compared field by field, list order included) | **one native crash in 5 runs** with the first design — redesigned: **30 runs clean** since (§4.1) | built, opt-in (`parse` block) |
| P2 | **Skip headers a `.cpp` already covered** | Phase 1 **−30 %** (16.2 → 11.3 s, best of 3; 104 of 218 files not parsed alone) | **yes on the sample** | needs a one-time compare on the office code (§4.1) | **removed 2026-10-12**: the only lever that could change the output, for a small part of the run |
| P5 | **One parse per file instead of two**: pass 1 records each file's call and global-access candidates, resolved once every definition is known (pass 2 exists only for that) | Phase 1 ≈ −25–35 % (pass 2: 4.7 s of 15.9 s here) | must be proven (model compare) | medium: pass 2's visitors become a resolve step | research |
| P6 | **The walks in several processes**: each process parses and walks its share of the files and records what each file contributed; the main process folds the records in today's file order, so "first file wins" holds | Phase 1 up to ×processes (the walk is ⅔ of it and threads cannot share it: the GIL) | must be proven | high: the visitors write shared state directly; they would have to record per file first | research — worth it only if the office's `run.log` shows Phase 1 matters (§6) |
| P3 | One AST walk instead of six | Phase 1 maybe −40 % | must be proven | medium: six visitors, one traversal | research |
| P4 | **A field check for the bindings' null guard**: clang ≥ 19 bindings call `is_null()` (a second libclang call) before nearly every cursor read — 2.5M calls, ≈20 % of Phase 1 | Phase 1 **−25 %** (16.2 → 12.1 s, best of 3) | **yes** (parse snapshots and include lists identical) | low: libclang's `clang_equalCursors` for the null cursor is exactly kind 70 + zero fields; or pin the bindings to the libclang version | built, **always on** — checked at start against the bindings' own answer, which stays if they disagree |
| C1 | Fewer LLM calls: description + names in one call; bigger flowchart label batches (4 → 8–12 nodes); templated text for trivial accessors | Phase 2 −40 %, labels −50–66 % | **no — wording changes** | quality to review | decision for the user |
| X1 | Parse/derive only a component's closure | depends: high-level component small, a low-level one ≈ its whole layer | only with every caller/ancestor/descendant/global user parsed | high: a missed file silently changes publication, ids, directions | research (needs a baseline version) |
| X2 | Components of a run in parallel processes | ×processes on Phase 3–4 | yes | needs a limiter shared **across processes** first (B6) | planned |
| X3 | Load the model once per run, not 3–4× per component; restore/persist only what changed | minutes per component at office scale | yes | low | planned |

## 3. What was built on the branch, and how it was checked

| Piece | Where | Checked |
|---|---|---|
| Lanes, start pacing, failover, adaptive concurrency, busy retries, refused keys, the learnt pause | `engine/llm_core/pool.py`, `client.py` (`_post`, `_attempt_numbers`) | unit tests; L-runs below. **Off unless configured** — with no `lanes`/`pacing`, the client runs today's code path untouched (its tests pin `sleep(3.0)` after each call) |
| Calls at once per stage (follows the lanes) | `engine/llm_core/parallel.py`; descriptions (`_run_in_rounds`), names, globals, units, structs; flowchart labels (`_process_all_parallel`) | results applied in today's order; descriptions run a call-graph *round* at once (a round's functions call none of each other) and the last round of a cycle in today's order |
| Parse ahead | `engine/core/tu_prefetch.py`, `parser.py` (`_parse_ahead`); `speedups.parseWorkers` | `tools/perf/compare_models.py`: identical model, parse snapshots identical but a timestamp |
| Skip covered headers | removed 2026-10-12 (was `parse.skipCoveredHeaders`) | had given an identical model on the sample, `tu_includes` 114 rows instead of 218 |
| Mermaid batch | `engine/config/render_mmd_batch.mjs` | 8/8 PNGs byte-identical to `mmdc`; 1.8–2.7 s per diagram vs 9.5 s; browser killed mid-batch → relaunched, 11/11 drawn (§4.3) |
| Flowchart PNG batch | `engine/config/render_dot_batch.mjs` | 8/8 byte-identical to `render_dot.mjs`; 1.8 s per chart vs 9.8 s; browser killed mid-batch → relaunched, 14/14 byte-identical |

**Same output.** The stand-in answers a hash of the prompt, so identical answers mean identical
prompts — context, callee descriptions and order included. With one `PYTHONHASHSEED` (see §4.2),
develop's code, this branch as it runs by default, and this branch with everything parallel switched
on make the same model:

| Check | Today | Parallel | Result |
|---|---|---|---|
| DEV / D1 — Phase 1+2, whole sample | **develop's code** (`369a2a1`, exported) | this branch, defaults | **every model file identical**, descriptions and names included; every parse snapshot identical (`metadata.json` differs only in project name, workspace path and time) |
| D1 / D2 — Phase 1+2, whole sample | sequential, one parse thread | two lanes, 4 workers, parse ahead on 6 threads | **every model file identical** (functions, descriptions, names, units, data dictionary, globals, hashes, edges) |
| DEVF / F3 — one component end to end (`Layer1.Diag`, Phases 1–4) | **develop's code** | this branch, defaults (picture batches on) | **47/47 flowcharts identical**; both Word files identical cell by cell, same picture count; interface tables, test specs, unit headers, UT export identical; 11 of 13 PNGs byte-identical — the other two are diagrams Mermaid's ELK layout draws two ways on its own (§4.3) |
| F3 / F4 — one component end to end | sequential | two lanes, 4 workers | **47/47 flowcharts identical** (DOT and graph), **11/11 unit-diagram PNGs byte-identical** |

**Phase 1** on a quiet machine (no LLM, three rounds with the modes interleaved; the first base run,
28 s, an outlier):

| Mode | Best of 3 | Median | vs base |
|---|---|---|---|
| today (`base`) | 16.2 s | 19.1 s | — |
| field null check (P4) | 12.1 s | 12.4 s | −25 % |
| parse ahead, 6 threads (P1) | 12.3 s | 12.6 s | −24 % |
| skip covered headers (P2) | 11.3 s | 11.3 s | −30 % |
| **all three** | **8.4 s** | **8.7 s** | **−48 %** |

**LLM runs** (Phase 1+2, fresh project each, stand-in gateway):

| Run | Setup | Phase 2 | Calls/s | Lost calls |
|---|---|---|---|---|
| L1 | today: pause after each call | **480 s** | 1.6 | 0 |
| L2 | start pacing, 4 workers, one key | 267 s (**1.8×**) | 2.9 | 0 |
| L3 | + a second key | 152 s (**3.2×**) | 5.1 | 0 |
| L4 | over-asked lanes (3 at once per key; gateway allows 1), before the fixes | 248 s | 3.1 | **8 of 762** |
| L4b | the same, with adaptive concurrency + busy retries | 179 s | 4.6 | **0** (83 refused, all retried) |
| L5 | two keys, every Phase-2 stage parallel | 139 s (**3.5×**) | 5.7 — 86 % of what two keys allow | 0 |
| L5c | L5 on the code before the pacing rules | 150 s (**3.2×**; the machine was busy with the test suite) | 5.3 | 0 |
| L4c | L4b on the final code, first pacing fallback | 250 s | 3.1 | 0 — but the concurrency's refusals sent both lanes back to pacing "after" (§4.2); fixed |
| L4d | the same, the switch counting only refusals with one call in flight | 269 s | 3.0 | 0 — still switched: the race (§4.2) |
| L4e | the same, a step of pause per lone refusal | 238 s | 3.8 | 0 — but the pause crept up to the whole gap on both lanes: the race |
| **L4f** | the same, **the final rule** (pause judged per window of 20 calls) | **146 s (3.3×)** | 5.4 | **0**; the pause never moved |
| **L5d** | **L5 (two keys, one call each — the setup to recommend), final code** | **135 s (3.6×)** | 5.8 | **0**; 16 refused (the race), the pause never moved |
| L6 | a gateway counting its gap from a request's **end**, two good keys and a **revoked** third (the switch) | 255 s (**1.9×**) | 3.1 | 0 — the revoked key tried once and left out; start pacing refused on 10 of the first 20 calls per lane, both lanes back to "after" |
| L6c / L6d | the same, the window rule climbing a step per window / damped | 323 s / 292 s | 2.4 / 2.6 | 0 — the climb and an easing that kept bringing refusals back cost time |
| **L6e** | the same, **the final rule** (half a window refused: the whole gap at once; a step off that brings refusals back waits twice as long next time) | **255 s (1.9×)** | 3.0 | **0**; 46 refused (205 in L6c); the revoked key dropped after one call |

**Pictures, cold caches** (`Layer1.Diag`, Phases 3+4, an instant LLM, each run with an empty data
root so no picture comes from a cache; two runs each, alternating):

| | Phase 3 (views) | Phase 4 SWE.3 (export) | Peak memory, Phase 3 |
|---|---|---|---|
| develop — a browser per picture | 129–137 s | 24.5–24.8 s | 1.07 GB |
| this branch — pictures in one browser | **37–38 s (3.5×)** | **14.3–15.8 s (1.6×)** | 1.5 GB (three pages open) |

**One component end to end** (`Layer1.Diag`: Phase 1+2 of its layer, Phase 3+4 of the component):

| Run | Phase 2 | Phase 3 (flowchart labels: 146 calls) | Lost calls |
|---|---|---|---|
| F1 today | 276 s | 105 s | 0 |
| F2 two keys + 4 workers | 86 s (**3.2×**) | 40.5 s (**2.6×**) | 0 (25 busy refusals retried) |

Same flowchart outcome in both (47 functions, 46 mechanical fallbacks each, 0 errors). Limitation of
this check: the stand-in answers plain text, not the label JSON the labeller parses, so the LLM's own
labels were not exercised — ordering, assembly and the drawn charts were. A stand-in that answers label
JSON would close that.

**What on the branch is production code, and what is study scaffolding:**

| Kind | Pieces | Default |
|---|---|---|
| Ready to review for develop | lanes + start pacing + failover + adaptive concurrency + busy retries + refused keys + the learnt pause + the `LLM lanes:` log line (`pool.py`, `client.py`); `llm.workers` stages (`parallel.py` — its `executor` cancels queued work on an error or a Ctrl+C — descriptions, names, globals, units, structs, flowchart labels; one cache key, one question at a time); the LLM banner's lanes/pacing/workers lines; picture batches (`render_mmd_batch.mjs`, `render_dot_batch.mjs` — a dead browser relaunched — `utils.render_*_many`, unit diagrams, flowchart PNGs, the export's component diagrams) | LLM changes **off** unless configured; picture batches **always on** (byte-identical; a failing batch falls back per picture by itself, so there is no switch) |
| Parsing | the field null check — `speedups.fastNullCheck`, self-checked at start; parse ahead — `speedups.parseWorkers` (env `ANALYZER_PARSE_WORKERS` over it). `core.config.speedup_settings` | both off (develop's) |
| Kept as a measurement | one `time:` line at Phase 1's end — waiting for libclang vs walking the AST (a large wait is what parse ahead wins back) | logging only |
| Study scaffolding | none left: the per-walk timers and the `ANALYZER_PROFILE_PARSER` profiling hook are removed (2026-10-12) | — |
| Tools | `tools/perf/*` | — |

## 4. Edge cases

### 4.1 Parsing
- **A native crash with threads.** One of five 6-thread runs died with `0xC0000005` *after* parsing,
  in the middle of writing the model (5 of 10 parse snapshots stored; the run failed loudly, Phase 1
  resumable). The first design let each worker thread create and free its own libclang index. Now every
  index is made on the main thread and lent to one parse at a time; `faulthandler` prints every
  thread's stack if it happens again. **Gate: 30 runs of Phase 1+2 with six parse threads, all clean**
  (10, then 20 on the final code). Still opt-in: the office's translation units are far larger than
  the sample's — switch it on there after one clean run.
- Python bindings `clang 21.1.7` with `libclang 18.1.1`: a version mismatch to settle regardless.
- **Order is part of the output.** "First file wins" for functions, the data dictionary, type hashes;
  `calledByIds` order picks a behaviour diagram's caller. A parallel *visit* would change these; the
  prototype keeps visits sequential in today's order and parallelises only libclang's parse.
- `os.walk` order is not sorted: Windows and Linux can already see files in different orders.
- **Skipping covered headers — removed (2026-10-12), and why it stays out.** It loses what only a
  header's *own* parse compiles: an `#if` branch active stand-alone but inactive in every `.cpp` that
  includes it. It also leaves the incremental engine fewer TUs (`tu_includes`), so a narrowed re-parse
  would need the baseline's full include lists and a `parseFingerprint` that carries the mode. All that
  for −30 % of a phase that is a small part of the run. If it is ever wanted again: commit `ffe2689`
  has it, with the fingerprint marker.
- Memory: each parsed-ahead TU holds its AST; at most `workers + 2` alive (office TUs with big headers:
  hundreds of MB each — size `speedups.parseWorkers` to the machine: 2–4 on 8 GB, 6–8 on 16 GB and up).

### 4.2 The LLM
- **The office's 503 says "invalid response from the upstream server"** — the model behind the gateway,
  not a rate limit. Every key shares that upstream, so failover only spreads the failure. With lanes, a
  429/502/503 or a refused connection is retried without using up an attempt — **at most 6 times per
  call, within 10 minutes** — then the attempts count as today. The cap matters when one *prompt*
  makes the upstream fail every time (too long for the model): it costs six quick retries, not ten
  minutes. **A timeout or a 504 cools the lane but counts as an attempt**: it already waited the full
  timeout, and a prompt too slow for the model stays too slow.
- **A revoked or mistyped key** on one lane (401/403): the lane is left out for the rest of the run,
  with one warning, and the call goes to another lane without using up an attempt. Every key refused:
  the calls fail after their attempts, as today, not in a loop.
- **The gateway may count its 3 s from the END of a request**, not the start (§6) — or still count
  the last call when the next one arrives the instant its answer left. Either way start pacing is
  refused with the lane's one call in flight. The lane **learns a pause after each call, judged per
  window of 20 calls**: a window with more than a quarter of its calls refused that way (an
  end-counting gateway refuses about every other one) adds a tenth of the interval, up to the whole
  interval (pacing "after", today's behaviour; one warning when it gets there); five clean windows in
  a row take a tenth off. A refusal now and then — the race, a few percent — moves nothing; a refusal
  with several calls in flight is the concurrency's and lowers that instead.
  A window with **half** its calls refused that way leaves no doubt: the whole gap at once, then ease
  down; a step off that brings the refusals back doubles the clean windows the next one waits for.
  **The final rule is the best measured on all three gateways** — L5d 135 s, L4f 146 s, L6e 255 s.
  **Three simpler rules failed first,** each giving start pacing's gain away on a gateway it should
  keep it on, none losing a call: a switch back to "after" once a quarter of all a lane's calls were
  refused misread the concurrency's refusals (L4c: 250 s instead of 179 s); the same counting only
  refusals with one call in flight still misread the race (L4d: 269 s); a step of pause per such
  refusal, a step off per 50 answers, crept up to the whole gap on the race alone (L4e: 238 s).
  (The stand-in's scale exaggerates a refusal's cost: its cool-down is at least 1 s against a 0.3 s
  gap; at the office it is about one gap.)
- A `Retry-After` longer than 120 s is not believed (an hour's rest on one lane would hold the run).
- **What each lane did** is one log line when the phase ends: `LLM lanes: lane1: 412 calls, 3 busy,
  51s waited, pacing start; …` — the first thing to read after a run with lanes.
- **Check the lanes before a run:** `analyzer.py check-llm --only tiny` sends one small prompt on every
  lane, with the headers a run sends on it, and names each lane that did not answer.
- **A header set in the environment replaces every lane's** (`X_DEP_TICKET`, `USER_ID`, `USER_TYPE`,
  `SEND_SYSTEM_NAME`; `llm_core/headers._resolve`): with `X_DEP_TICKET` set, two ticket lanes send one
  ticket. `check-llm` warns when two lanes send the same thing to the same server.
- **All lanes must use the same model.** The description cache key does not include the model, so mixed
  models would mix wording per lane and per run.
- **The gateway's limit may be per user, not per key** (headers `User-Id`, `x-dep-ticket`): several
  keys of one user may share one limit — and several users' keys may need the gateway owners' approval.
- **Two jobs at once double the rate on one key**: lanes are per process. Phases run one after another,
  so one run is one process at a time — but two web jobs, or Phase 3 in parallel processes (X2), need a
  limiter shared across processes (a database row or file lease): open item B6.
- A lane asked for more than the gateway allows loses calls unless busy refusals are retried: found in
  L4 (8 lost), fixed by adaptive concurrency (a busy answer with several in flight lowers the lane's limit;
  50 good answers raise it again) and by busy refusals not using up attempts.
- **A bug found in review, fixed:** the first version of the free retry still moved the attempt number
  on, so a busy refusal followed by an ordinary error ended the call one attempt early. A test now pins
  "503, 400, 400, 200 → answered".
- **Two copies of one question.** The caches are shared, so in today's order a second copy (two
  `static` helpers with one name and body in two `.c` files; two structs with one name and fields)
  takes the first one's cached answer. In parallel both could miss the cache and ask the LLM, and a
  real LLM could word them differently. So work that shares a cache key runs one after another in
  today's order — descriptions by qualified name (the description cache's key), flowchart labels by
  source text (the label cache's key) — and names, units and structs ask a key's question once
  (one lock per key). Global descriptions have no cache, as today.
- Descriptions: only a round's functions run together; the final "cycle" round (everything left once a
  call cycle blocks progress) runs in today's order — it can be large on code with recursion (every
  caller above a cycle). Grouping only true cycle members would help but changes those prompts.
- **Today's first-time text already varies from run to run.** A description prompt lists the callees in
  set order, which follows Python's per-process hash seed: comparing today's sequential run with the
  parallel one, 24 of 385 descriptions differed — 23 of them functions with 2+ callees, the 24th one whose
  callee's text differed. The cache key sorts the callee hashes, so cache hits are stable and re-runs do
  not pay again; only a first generation varies. To compare a speed-up exactly, both runs need one
  `PYTHONHASHSEED`; to make runs reproducible for good, sort the callees in the prompt (changes those
  prompts once).
- On the sample the description rounds are 309, 42, 18, 11, 2, 2, 1 functions, with no cycle round, so
  309 can be asked at once. `tools/perf/llm_rounds.py <version>` measures it on office code.
- Thread safety: the shared caches (`aux_descriptions`, flowchart labels, the description entity cache),
  progress and context builders take a lock; only the HTTP wait overlaps. The LLM stage name follows
  each thread (`contextvars`), so the report still counts calls per stage.
- The flowchart child: libclang stays on its main thread (graphs first, in order), labels in parallel,
  each thread with its own label generator (it keeps per-call state), charts drawn in order.

### 4.3 Pictures
- The batch renderer must keep mmdc's defaults exactly (theme, white, 800×600, integer scale) — a
  different default changes every PNG and every content-addressed cache key's meaning.
- Mermaid's ZenUML plugin waits 1 s per diagram and logs to stdout: results go to a file, not stdout.
- **A browser that dies mid-batch** (one huge picture, out of memory) is launched again — at most twice
  per batch — and the picture it died under is tried once more. Without it every picture left would
  fail at once and go back to one browser per picture: right pictures, today's speed. Checked by killing
  the batch's browser mid-run: Mermaid 11/11 drawn, DOT 14/14 byte-identical to an uninterrupted run.
- A picture that fails in the batch (or times out: 90 s a diagram, 180 s a chart, as the per-picture
  paths allow) is drawn by `mmdc` / `render_dot.mjs` afterwards, as today. A timed-out chart that
  finishes late does not overwrite the one drawn meanwhile.
- **Mermaid's ELK layout is not stable on its own:** `mmdc` drew two sample unit diagrams
  (`ClassStatics`, `StaticViaObject`) two ways each in four runs (a few pixels at an arrowhead), and
  the batch draws the same two variants. Develop has it too; the content-addressed cache reuses
  whichever was drawn first.
- The docker Mermaid path (`mermaid_in_docker`) is not covered by the batch.

## 5. Plan

**Every speed-up is one key of ONE block, `speedups` in `engine/config/config.local.json`
(2026-10-14d). A key not set is develop's way, so an empty or absent block runs exactly as develop
does** — checked: develop's code against an empty block gives the same LLM calls in the same order,
the same model and the same files. `core.config.speedup_settings` reads it; a run's start says which
it uses (`Speed-ups: 2 llms, pacing start` or `Speed-ups: none -- this run works as develop does`).

| Key | Not set (develop's) | Set |
|---|---|---|
| `llms` | `[]`: llmServer's own ticket, one call at a time | more tickets or keys side by side (lanes, `llm_core/pool.py`); a lane takes what it does not set from `llmServer`; when listed, only they send calls |
| `pacing` | `"after"`: the ticket's pause counts from a call's END | `"start"`: from its start (§ below: one office run decides) |
| `parseWorkers` | `1`: one file at a time, parsed in `parse_file` on the parser's own index | a number or `"auto"` (half the CPUs, at most 8); env `ANALYZER_PARSE_WORKERS` wins |
| `pictureBatches` | `false`: each picture drawn alone | `true`: a view's pictures drawn by one browser; a miss is drawn alone |
| `fastNullCheck` | `false`: the bindings' own check, no probe parse | `true`: the field check, self-checked at start (off by itself where it disagrees) |

Until 2026-10-14 they were spread: `llmServer.lanes`, `llmServer.pacing`, `parse.workers`, a
`speedups.enabled` switch, and the batches and the null check always on. Those places are not read
any more; a run's start names each with its new place (`core.config.moved_settings`), and the run
goes on, the develop way. `LLM_API_KEYS=key1,key2` (env) still makes one lane per key when `llms`
is empty.

**How the office would switch the LLM changes on:**

```json
"speedups": {
  "llms": [ { "name": "ticket-a", "customHeaders": { "x-dep-ticket": "credential:TOKEN_A" } },
            { "name": "ticket-b", "customHeaders": { "x-dep-ticket": "credential:TOKEN_B" } } ],
  "pacing": "after"
}
```

`pacing: "start"` alone (one ticket) is the safest first step for pacing. A lane is a credential —
`customHeaders` (they replace llmServer's headers of the same name) or `apiKey`; it may also name a
`baseUrl`, a `name` for the log and `maxConcurrent` (default 1). A second person's ticket needs
their `User-Id` in its lane. The environment's `X_DEP_TICKET` / `USER_ID` / ... replace that header
on every lane.

| No longer an option | Now |
|---|---|
| `llm.workers` (and env `LLM_WORKERS`) | follows the lanes: 1 without `llms` or start pacing — develop's one call at a time — else twice what the lanes take at once (`core.config.llm_calls_at_once`) |
| a lane's own `pacing` and `rateLimitSeconds`, env `LLM_PACING` | `speedups.pacing` and `llmServer.rateLimitSeconds`, the same on every lane |
| skipping covered headers (`parse.skipCoveredHeaders`) | removed, code and all: the one lever that could change the output |
| picture batch switches (`ANALYZER_MMD_BATCH`, `ANALYZER_DOT_BATCH`, ...) | `speedups.pictureBatches` only |
| `speedups.enabled`, env `ANALYZER_SPEEDUPS` (2026-10-14 → 14d) | each key on its own; an empty block is develop |

- **Keys go in `config.local.json` or `LLM_API_KEYS` only.** Since 2026-10-13d that is the rule
  of the whole `llmServer` block: a project's or a version's config holds no server setting
  (`versions.resolved_config` and the workspace files are written without them), and a lane
  written in one would not be read. The run's LLM banner counts the lanes and prints no key (`lanes : 2 configured`,
  `pacing : start`, `calls at once : 4  (follows the lanes)`); the flowchart child reads the config itself, so no key is on a
  command line.
- **Ollama:** without lanes it stays one call at a time. To send several at once, give its lane
  `maxConcurrent` — and keep it within the server's `OLLAMA_NUM_PARALLEL`, or requests queue up there
  and time out.
- After the first run, read the `LLM lanes:` line at the end of each phase's log: busy answers,
  seconds waited, a refused key, the pause start pacing learnt (`+2.70s after each call` on a 3 s
  gateway means it counts from a call's end: start pacing gains little there).

**Should `pacing` default to `"start"`? Decided (2026-10-12): not yet — after one office run.**

| | |
|---|---|
| Why not now | `"start"` wins only when the gateway counts its gap from a call's START. If it counts from the END, start pacing is refused about every other call: each refusal is a retry and a cool-down, twice the requests on the gateway, and a ticket refused again and again might be flagged by the gateway's owners. The lane does learn the right pause by itself (L6e: back to today's speed, nothing lost), but pays refusals while it learns (46 in L6e). On an unknown gateway, `"after"` is what is known to work |
| The test | One office run with `"pacing": "start"` (one ticket is enough). Read the `LLM lanes:` line at the end of Phase 2 |
| Make it the default | few `busy`, and no learnt pause (no `+X.XXs after each call`) — the gateway counts from the start |
| Keep `"after"` | many `busy`, and a learnt pause near the gap (`+2.7s after each call` on 3 s) — it counts from the end |
| To flip the default | One line: the default of `pacing` in `core.config.SPEEDUP_DEFAULTS` becomes `"start"` (a machine can still set `"after"` in its `config.local.json`; `pacing` is not in `config.defaults.json`, which holds no server setting). The client tests that pin `sleep(3.0)` after each call cover `"after"` and stay |

**A — safe, same output (review and merge what is built; days):**
1. Picture batches (R1, R2) — on by default, byte-identical, per-picture fallback; wire the behaviour
   diagrams the same way.
2. Lanes + start pacing (L1–L3) — off until configured; switch on at the office with
   `pacing: "start"` first, then a second ticket once §6's question 1 is answered.
3. The field null check (P4) — `speedups.fastNullCheck`. Parse ahead (P1) — `speedups.parseWorkers`, off; its gate passed
   here (30 clean runs); switch on at the office after one clean run, then make `"auto"` the default.

**B — same output, needs a check on the office code:** model loaded once
per run (X3); then a cross-process limiter and components in parallel (X2, B6).

The cross-process limiter (B6), as it should be built:
- **Where:** one server at the office, so a small state file in the data root under an OS file lock
  (no database round trip per call); a row per lane with `SELECT … FOR UPDATE` when there is more than
  one server.
- **Leases, not counters:** a slot is a lease that expires after twice the call timeout, so a process
  killed in the middle of a call (a Stop, a crash, a restart) cannot hold its slot for ever.
- **One clock:** pacing compares times from one source — the file's own on one host, `now()` in the
  database across hosts.
- **Same rules as the in-process pool:** start pacing, cool-down with `Retry-After`, adaptive concurrency
  — shared, so two jobs on one key see one limit.

**C — changes wording, the user's decision:** fewer calls (C1), with a side-by-side review of the text.

**D — research:** one AST walk (P3); a component-closure parse with a baseline version (X1).

**The demo branch's accuracy catch** (`demo/fast-components`, LLM only for the requested components):
a requested function's prompt carries its callees' descriptions, so a callee in an unrequested component
arrives with none, and that function's text can be poorer than a full run's. Cheap middle ground: also
describe the requested functions' *direct callees*, one level out, whatever their component — every
requested prompt then sees its callees described, for a bounded number of extra calls (the callees of
the requested functions, not their whole layers). The flowchart prompts reach callees up to four levels
deep; one level covers the nearest, which matter most.

## 6. Questions only the office can answer
1. Gateway: is the limit per key, per user, per IP or global? Requests per second, or calls in flight?
   Is the 3 s counted from a request's start or from its end (start pacing helps only in the first
   case; in the second the lanes learn the pause after each call on their own)? Does it send `Retry-After`? What
   does it answer when it is over its limit — 429, or the 503 we saw? How many keys may we use, and may
   they belong to one user?
2. A `run.log` of the 10-hour run: the `Phase` lines and the "LLM calls by stage" table (answer time
   per call, prompt tokens, throttle) — to replace this page's estimates with the office's numbers.
3. The office machine: cores, memory (sizes parse-ahead and picture pages).
4. One layer's size: translation units, functions — and whether `views.flowcharts` is on there.

## 7. Reproduce
`tools/perf/`: `llm_standin.py` (the stand-in gateway), `timed_run.py` (one timed run on a scratch
copy of the sample), `compare_models.py` (two versions' models, exactly), `compare_parse.py` (Phase 1's
output alone), `llm_rounds.py` (how many descriptions can run at once), `standin_report.py`. A
throwaway database (`analyzer.py setup` on an empty one) through `DATABASE_URL`; the LLM pointed at the
stand-in in `engine/config/config.local.json`.
