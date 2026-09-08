# LLM Concurrency & Container Scaling — Implementation Plan

> Tracked implementation plan for the `docs/planning/ROADMAP.md` V1.x item **"Performance and
> LLM-usage optimisation"**. Complements `04-incremental-changes-implementation.md` §12
> (M-A…M-D, done) — those milestones remove redundant work on **re-runs / small diffs**
> (caching). This plan attacks the orthogonal axis: **wall-clock time for a first-ever, cold-cache
> generation**, which today is bounded by pure sequential LLM call count, not by cache misses.

## 0. Problem statement (measured, not assumed)

A single-layer, cold-cache generation currently takes **8+ hours minimum**. Root cause, verified
directly in code (`git grep` for `ThreadPoolExecutor|ProcessPoolExecutor|multiprocessing|asyncio`
across the repo returns **zero hits** — there is no concurrency anywhere in the pipeline today):

- [engine/llm_core/client.py:489-510](../../engine/llm_core/client.py) — every OpenAI-route call is
  wrapped in a process-wide `_OPENAI_LOCK` (only one request in flight, ever) plus an unconditional
  `time.sleep(rate_limit)` (default 3.0 s) **after every attempt, including failures**. This is
  deliberate — the comment explains it exists to protect a shared, rate-limited corporate gateway —
  but it caps the entire pipeline at ~1 LLM round-trip per (3 s + generation latency).
- Every LLM-consuming call site is a plain sequential `for` loop: function descriptions
  (pass 1 + pass 2 in [engine/llm_enrichment.py:1152-1295](../../engine/llm_enrichment.py)),
  behaviour names, 4-level hierarchy summaries, and per-function flowchart labeling + coherence
  ([engine/flowchart/flowchart_engine.py](../../engine/flowchart/flowchart_engine.py)). For a
  ~300-function layer (the verified sample: 297 functions / 184 files) this is on the order of
  1,500–2,000 sequential LLM round-trips.
- Non-LLM phases (libclang parsing in Phase 1, `mmdc` diagram rendering in Phase 3/4) are also
  single-threaded, but are a smaller share of the 8 hours since they carry no artificial throttle.
  Phase 1 additionally had a real bug, not just missing concurrency: every TU was parsed **three
  times** (`parse_file`/`parse_calls`/`parse_global_access` each ran `index.parse()` with identical
  args) — fixed in CC-4a (§5), 2026-09-08.

**Given:** self-hosting the LLM is now assumed possible (dedicated GPU capacity, sized as needed).
That removes the *reason* for `_OPENAI_LOCK`'s conservatism — a self-hosted inference server with
continuous batching can genuinely serve many concurrent requests. The plan below removes the
artificial serialization first (cheapest, highest-leverage, no infra dependency), then adds real
concurrent inference capacity and container-level horizontal scaling to match it.

**Target:** < 1 hour for the same single-layer cold-cache generation — roughly a 20–40× reduction
in effective wall-clock per LLM call.

## 1. Milestone tracker

| ID | Milestone | Scope | Status |
|---|---|---|---|
| **CC-1** | Client-layer concurrency primitives | `llm_core/client.py` — semaphore + rate limiter, config, thread-safety audit | **done** (2026-09-07) |
| **CC-2** | Parallelize call sites (wave-based) | Phase 2 descriptions/behaviour-names/summaries, Phase 3 flowchart labeling | not started |
| **CC-3** | Self-hosted inference tier, containerized | vLLM/TGI container(s), multi-replica K8s Deployment + HPA | not started |
| **CC-4a** | De-duplicate Phase 1's redundant re-parse | `engine/parser.py` — parse each TU once, reuse across all 3 passes | **done** (2026-09-08) |
| **CC-4** | Containerized CPU-bound fan-out | Phase 1 parsing, Phase 3 `mmdc` rendering — process pool or worker pods | not started |
| **CC-5** | Orchestrator-level multi-container scale-out | Phase/shard-per-pod scatter-gather (K8s Jobs), replaces single-host subprocess model | not started |
| **CC-6** | Call-volume reduction | Prompt batching, two-pass gating, cache-hit verification | not started |

Sequencing: **CC-1 must land first** (per your instruction) — it's the change with the best
effort/impact ratio and has no infra dependency; it can be validated against a single self-hosted
model instance before anything else moves. CC-2 depends on CC-1's primitives. CC-3 and CC-4 can run
in parallel once CC-1/CC-2 exist to consume the added capacity. CC-5 is the "many containers"
end-state and depends on CC-3/CC-4. CC-6 is independent and can land at any point.

---

## 2. CC-1 — Client-layer concurrency primitives

**Status: done (2026-09-07).** Implemented mostly as specified below, with one deliberate
deviation: at `max_concurrency<=1` (the default), `LlmClient._post_openai()` keeps the legacy
`_OPENAI_LOCK` + unconditional post-call `_throttle()` sleep as its own untouched branch, rather
than routing it through `_RateLimiter` — a real shared-bucket limiter cannot reproduce "always
sleep exactly `rateLimitSeconds`, even on the very first call" (an empty bucket never waits), so
the no-op guarantee below is met by branching, not by one formula that behaves identically at both
settings. Full detail, the bug found while testing it (a sliding-window off-by-one that
busy-looped), and the thread-safety audit results: `PROJECT_CONTEXT.md`'s `> Updated: 2026-09-07`
entry. CC-2 (parallelizing the call sites) has not started — CC-1 only makes concurrent calls
*safe*.

**File:** `engine/llm_core/client.py`. **Goal:** let N requests be in flight at once, sized to
whatever the backend can actually absorb, instead of a hardcoded 1.

### 2.1 Changes

- Replace `_OPENAI_LOCK = threading.Lock()` (client.py:124) with a **bounded semaphore**:
  `_CONCURRENCY_SEM = threading.Semaphore(max_concurrency)`, constructed from a new
  `max_concurrency: int = 1` constructor parameter on `LlmClient` (default `1` preserves today's
  exact behaviour for anyone who doesn't opt in). Every `with _OPENAI_LOCK:` block
  (client.py:493, 532, and the Ollama path if/when it also gets a concurrency cap) becomes
  `with _CONCURRENCY_SEM:`.
- Replace the unconditional `time.sleep(self._rate_limit)` in `_throttle()` (client.py:222-227)
  with a **token-bucket rate limiter** shared across the semaphore's permits: instead of "sleep
  3 s after every call regardless of concurrency" (which, under concurrency, would still cap
  throughput at 1/3s because the sleep happens *inside* the critical section), the limiter should
  cap **aggregate requests/second**, letting the semaphore's N permits each fire as soon as the
  bucket has capacity. Concretely: a `_RateLimiter` class holding a `deque` of recent request
  timestamps (or a simple leaky-bucket counter) protected by its own lock, with
  `acquire()` blocking until under `llm.requestsPerSecond`. This is a genuinely different
  rate-limiting *shape*, not just "run the old sleep less often" — with the old
  lock+sleep-inside-lock design, adding a semaphore alone would not increase throughput at all
  (the sleep still serializes everything inside the lock). This is the one subtlety in CC-1 to get
  right; don't ship the semaphore without also replacing `_throttle`.
- New config keys (validated in `engine/core/config.py` next to the existing
  `maxContextTokens` handling at config.py:283-297):
  - `llm.maxConcurrency` (int ≥ 1, default 1) — size of the semaphore. For a self-hosted vLLM
    instance, this should roughly match its configured `max_num_seqs` / batch concurrency.
  - `llm.requestsPerSecond` (float, default derived from `rateLimitSeconds` as
    `1 / rateLimitSeconds` for backward compatibility, `0` = unlimited) — replaces
    `rateLimitSeconds` as the authoritative knob once concurrency is in play; keep
    `rateLimitSeconds` accepted and auto-converted so existing configs don't break.
  - Both env-overridable (`LLM_MAX_CONCURRENCY`, `LLM_REQUESTS_PER_SECOND`) following the existing
    pattern in config.py's env-var table.
- Startup banner (`format_llm_config_banner`, config.py:419-450): add a `Concurrency: N req
  in-flight, R req/s` line so every run is self-documenting about which mode it ran in — matching
  the existing "measured, not assumed" convention in this repo.
- `LlmClient.generate()` / `.call()` are already the single choke point every caller goes through
  (per `PROJECT_CONTEXT.md` §8/§18 "Single LLM client class") — no call-site changes needed for
  CC-1 itself. CC-1 only makes it *safe and correct* to call `generate()`/`call()` from multiple
  threads at once; CC-2 is what actually starts doing so.

### 2.2 Thread-safety audit (do this before CC-2, not after)

Checked directly against source in this session:

| Component | Status | Note |
|---|---|---|
| `llm_core/cache.py` `EntityCache` | **already safe** | Per-instance `threading.Lock` around counters; `put()` writes via `tmp` + `os.replace` (atomic); one file per entity keyed by content hash, so concurrent writes to *different* entities never collide. No change needed. |
| `engine/core/progress.py` `ProgressReporter` | **already safe** | Own `threading.Lock` around `step()`/counters. |
| `llm_core/tokens.py` counter | **needs verification** | Uses `contextvars.ContextVar` for stage attribution — contextvars do **not** automatically propagate into a `ThreadPoolExecutor` worker thread; must submit via `functools.partial` wrapping `contextvars.copy_context().run(...)`, or accept that concurrent calls land in `"unspecified"` stage (acceptable but should be a conscious choice, not an accident). Confirm the counter increment itself is lock-protected (module docstring implies per-process singleton; verify before CC-2 lands). |
| `llm_core/context_builder.py` `ContextBuilder`, `llm_core/repo_map.py` `RepoMap`, `llm_core/few_shot.py` `FewShotPool` | **read-only after construction** | Built once per `enrich_functions_rich()` call from an immutable knowledge snapshot; methods don't mutate shared state. Should be safe to share across threads, but confirm no lazy-init mutable caches exist inside them before relying on it. |
| `engine/flowchart/pkb/cache.py` `PkbCache` | **needs verification** | Disk cache keyed by `functions.json` hash — check for the same tmp+replace atomicity pattern as `EntityCache` before parallelizing flowchart labeling (CC-2). |
| `.mmdc_cache/` (`utils.render_mermaid_cached`, per `04-incremental-changes-implementation.md` §12 M-A) | **needs verification** | Content-addressed by mermaid text, but confirm the write path is atomic (tmp+replace) before CC-4 parallelizes `mmdc` invocations — two threads racing to write the same cache key must not corrupt a PNG. |

### 2.3 Verification

- Unit test: spin up a trivial local HTTP stub (or `responses`/`requests-mock`) that records
  concurrent-request high-water-mark; assert `LlmClient(max_concurrency=8)` actually reaches ≥2
  concurrent in-flight requests and never exceeds 8.
- Regression: existing `tests/unit/` LLM-related tests must pass unchanged with `max_concurrency=1`
  (the default) — CC-1 must be a strict no-op at the default setting.
- Throughput micro-benchmark against a real self-hosted instance (see CC-3): fire 100 identical
  `generate()` calls at `max_concurrency=1` vs `max_concurrency=16`, compare via
  `llm_core.tokens.format_report()` (already tracks per-call latency/throttle/outcome) — this
  reuses existing instrumentation, no new tooling needed.

---

## 3. CC-2 — Parallelize the call sites (wave-based)

Once CC-1 makes concurrent calls *safe*, each sequential `for` loop over independent work becomes
a `ThreadPoolExecutor` loop. LLM calls are I/O-bound (network round-trip to the inference
container), so threads — not processes — are the right primitive here; this keeps shared state
(the `result` dict, `EntityCache`, `ContextBuilder`) in one address space.

### 3.1 Phase 2 — rich function descriptions (`enrich_functions_rich`, llm_enrichment.py:1069)

The topological order is already computed as a sequence of levels internally
(llm_enrichment.py:1108-1114 — the `while` loop's `ready` list *is* a wave: every function in it
has all its callees already `processed`). Today the code flattens all waves into one `order` list
and iterates it serially. Change:

- Keep `order` as a `List[List[str]]` (list of waves) instead of flattening.
- Pass 1 (llm_enrichment.py:1157-1222): for each wave, submit every function in the wave to a
  `ThreadPoolExecutor(max_workers=llm.maxConcurrency)`, `as_completed()` to collect results into
  `result` before moving to the next wave — later waves' functions read `result` for callee
  context (llm_enrichment.py:1170), so wave boundaries must be a hard synchronization point.
- Pass 2 (llm_enrichment.py:1230-1295): same shape — pass 2 needs pass 1 fully done (it reads
  `prior = result.get(key)`), but *within* pass 2 every function's refinement is independent of
  every other function's refinement (caller/callee context all comes from pass 1's already-final
  `result`), so pass 2 can run as a **single flat wave** (no leveling needed) at full concurrency.
- `ProgressReporter` calls (`progress.step(...)`) become concurrent — already lock-safe (§2.2), no
  change needed there.

### 3.2 Phase 2 — behaviour names & hierarchy summaries

- `_enrich_behaviour_names_llm` (model_deriver.py, per `PROJECT_CONTEXT.md` §11): independent
  per-function calls, no ordering constraint — flat `ThreadPoolExecutor` over the "poor name"
  subset.
- `_enrich_with_hierarchy_summaries` (4-level: function → file → module → project): each tier
  depends on the tier below being fully done (a file summary reads its functions' summaries), so
  this is a 4-wave pipeline, same shape as CC-2's Phase 2 descriptions — parallelize *within* each
  tier, synchronize *between* tiers.

### 3.3 Phase 3 — flowchart labeling (`flowchart_engine.py` `_process_function`)

Every function's CFG build → enrich → label → coherence pipeline is independent of every other
function's (per `PROJECT_CONTEXT.md` §13, coherence is per-function, not cross-function). This is
the largest and simplest concurrency win — no wave logic needed at all, just
`ThreadPoolExecutor(max_workers=llm.maxConcurrency)` over the function list in
`flowchart_engine.run()`. Two things to carry through correctly:
- `LabelGenerator`'s batch-halving-on-failure recursion (per function) must stay
  function-scoped — it already is, since each call operates on one function's CFG.
- The libclang `TranslationUnitParser.get_tu_full()` per-file cache
  (`flowchart_engine.py` §13 "TU parse... cached per-file") is read many times concurrently once
  functions from the same file run on different threads — confirm it's populated once (e.g. via a
  `functools.lru_cache` or a lock-guarded dict) rather than racing to parse the same TU twice; a
  double-parse is wasted work, not a correctness bug, but worth a one-line guard.

### 3.4 Verification

Per-milestone, re-run the same fixture (`SampleCppProject`, cold cache — delete
`.flowchart_cache/` and `.mmdc_cache/` first) before/after, compare wall-clock and the
`llm_core.tokens` report's total latency vs. total wall-clock (the gap between them **is** the
concurrency win — if they stay close together, something serialized that shouldn't have).
`tests/unit/` must pass unchanged (these are pure ordering/output tests, not timing tests, so
concurrency shouldn't touch their assertions — flag immediately if it does, that means a race).

---

## 4. CC-3 — Self-hosted inference tier, containerized

CC-1/CC-2 can raise concurrency to any number, but throughput is capped by how many requests the
model server can actually process at once. This milestone provisions that capacity as containers,
following the exact pattern already established in this repo's `Dockerfile` /
`k8s-deployment.yaml` for the API tier (namespace `aspice`, `ConfigMap`, liveness/readiness
probes, resource requests/limits, pod anti-affinity, rolling updates).

### 4.1 Inference server choice

- **vLLM** (OpenAI-compatible server, `vllm serve <model> --api-key ... `) — continuous batching
  gives genuine concurrent throughput on GPU, which is exactly what CC-1's semaphore needs a real
  backend for. Official `vllm/vllm-openai` image; no new Dockerfile needed, just a values/manifest
  layer.
- Fallback if GPU capacity is constrained: multiple **Ollama** replicas (CPU or smaller GPUs) behind
  a load balancer — each replica still serves one request at a time internally, so this scales by
  *replica count* rather than *per-instance batching*; still fully compatible with CC-1's semaphore
  since the client just needs a `baseUrl` that resolves to a load-balanced Service.

### 4.2 Container/K8s shape (multi-container spawning, mirrors `k8s-deployment.yaml`)

```yaml
# New Deployment: aspice-llm-inference (parallel to the existing aspice-api Deployment)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aspice-llm-inference
  namespace: aspice
spec:
  replicas: 4                 # start here; tune against CC-1's maxConcurrency benchmark
  strategy:
    type: RollingUpdate
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }
  selector:
    matchLabels: { app: aspice-llm-inference }
  template:
    metadata:
      labels: { app: aspice-llm-inference }
    spec:
      affinity:
        podAntiAffinity:                     # spread across GPU nodes, same pattern as aspice-api
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector: { matchExpressions: [{key: app, operator: In, values: [aspice-llm-inference]}] }
                topologyKey: kubernetes.io/hostname
      containers:
        - name: vllm
          image: vllm/vllm-openai:latest
          args: ["--model", "<model-name>", "--max-num-seqs", "16", "--port", "8001"]
          ports: [{name: http, containerPort: 8001}]
          resources:
            requests: { nvidia.com/gpu: 1, memory: 24Gi }
            limits:   { nvidia.com/gpu: 1, memory: 32Gi }
          readinessProbe: { httpGet: { path: /health, port: 8001 }, periodSeconds: 5 }
          livenessProbe:  { httpGet: { path: /health, port: 8001 }, periodSeconds: 10 }
---
apiVersion: v1
kind: Service
metadata: { name: aspice-llm-inference, namespace: aspice }
spec:
  type: ClusterIP
  ports: [{name: http, port: 8001, targetPort: 8001}]
  selector: { app: aspice-llm-inference }
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: { name: aspice-llm-inference, namespace: aspice }
spec:
  scaleTargetRef: { apiVersion: apps/v1, kind: Deployment, name: aspice-llm-inference }
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource: { name: gpu, target: { type: Utilization, averageUtilization: 80 } }  # or a custom
                                                                                       # queue-depth metric
                                                                                       # exported by vLLM
```

- `engine/config/config.json`'s `llm.baseUrl` points at the `aspice-llm-inference` Service
  (`http://aspice-llm-inference.aspice.svc.cluster.local:8001`), `provider: "openai"` (vLLM speaks
  the OpenAI wire format), and `llm.maxConcurrency` set to roughly
  `replicas × max_num_seqs` (start conservative, tune from CC-1's benchmark harness).
- This directly satisfies "think of multiple container spawning" — the inference tier scales
  horizontally the same way the existing API tier does (`kubectl scale` / HPA), and CC-1's
  semaphore + rate limiter is what lets the analyzer actually saturate N replicas instead of
  round-robining one request at a time.

### 4.3 Verification

- `kubectl scale deployment aspice-llm-inference -n aspice --replicas=N` for N ∈ {1, 2, 4, 8},
  re-run the CC-1 throughput micro-benchmark against the Service endpoint at each N, confirm
  near-linear throughput scaling until GPU/node capacity saturates — this is the number that
  determines the real `llm.maxConcurrency` ceiling, not a guess.

---

## 5. CC-4a — De-duplicate Phase 1's redundant re-parse (done)

**Status: done (2026-09-08).** Before touching CC-4's fan-out, Phase 1 was measured directly (not
assumed): `parse_file`, `parse_calls`, `parse_global_access` each called `index.parse()` on every
TU with byte-identical `args`/`options` — every file was parsed from scratch **three times**, and
the libclang parse (not the Python AST walk) is the dominant cost. Fix: `parser.py`'s new `_get_tu(path)`
parses each TU once and caches it (`_tu_cache`, cleared at the end of `main()`); all three passes
now reuse the same `TranslationUnit` object. The three passes still run as three separate full
loops over `source_files`, in the original order — see CC-4's blockers below for why they can't be
merged into one per-file loop.

Measured on `SampleCppProject` (184 files / 296 functions): Phase 1 wall time **7.22s → 3.12s**
(~2.3×). Verified byte-identical `model/*.json` output against a pre-change baseline (only
`metadata.json`'s `generatedAt` timestamp differed).

## 6. CC-4 — Containerized fan-out for CPU-bound phases

Smaller win than CC-1–CC-3 but real at layer scale (184 files, dozens of units), and it's where
"multiple container spawning" applies a second time, independent of the LLM tier:

- **Phase 1 (libclang parsing) — NOT embarrassingly parallel as originally scoped here.**
  Correcting the claim below (measured while implementing CC-4a, not assumed): `parser.py`'s three
  passes share plenty of mutable module state across files, not none. Two concrete blockers a
  `ProcessPoolExecutor(max_workers=os.cpu_count())` over the TU list must solve, not paper over:
  - `visit_calls` resolves a call's callee against the **fully-populated** `functions` dict
    (`called_key not in functions` at parser.py:1773) — it must see every file's definitions,
    not just its own worker's, or cross-TU calls to a function defined in a file processed by a
    different worker silently drop from the call graph.
  - `visit_definitions` dedups a header-defined function seen through multiple TUs via a shared
    `_visited_function_keys` set (parser.py:1462) — first file to visit it wins, deterministically,
    because `source_files` is processed in a fixed order. Split across worker processes (separate
    address spaces), every worker would independently "first-see" and re-record the same header
    function, and the merge order into the main process's `functions` dict would decide the
    winner — silently, unless the merge explicitly replays `source_files` order.
  - Net: a worker can't just mutate `functions`/`call_graph`/`_visited_function_keys`/etc. in
    place — each worker must return a per-file result (the CC-4a-cached TU makes this natural:
    parse once per file, run the pass-1 visitors, return the diff), and the main process merges
    all workers' results **in `source_files` order** before pass 2 (calls) starts, exactly
    reproducing today's single-process semantics. This is real design work, not a drop-in
    `ProcessPoolExecutor`; scope it properly before starting, in the same spirit as CC-1/CC-2's
    detailed designs (§2, §3) rather than CC-4's one-paragraph sketch.
  - At the container level: if Phase 1 is ever split out as its own K8s Job (see CC-5), it can fan
    out as N pods each parsing a shard of the TU list, results merged before Phase 2 starts — same
    merge-in-order requirement applies across pods, not just in-process workers.
- **Phase 3 diagram rendering (`mmdc`):** each invocation spawns a headless-Chromium subprocess
  (60 s timeout per diagram per `PROJECT_CONTEXT.md` §12) — CPU/memory-heavy and currently
  sequential. Because it's a real subprocess (not a Python-GIL-bound call), a
  `ProcessPoolExecutor` or even a plain worker-thread pool calling `subprocess.run` concurrently
  both work; containerizing this as its own small worker Deployment (`aspice-mmdc-worker`, N
  replicas, no GPU) isolates its memory/CPU footprint from the main analyzer process and lets it
  scale independently of the LLM tier — relevant because `mmdc` load and LLM load don't move
  together (a `--no-llm` timing run per `04-incremental-changes-implementation.md` §12 M-D would
  still want fast diagram rendering).
- Both are gated behind the CC-1/CC-2 thread-safety audit item on `.mmdc_cache/` write atomicity
  (§2.2) — fix that first if it isn't already atomic.

---

## 7. CC-5 — Orchestrator-level multi-container scale-out

The end state for "multiple container spawning": instead of one long-lived host running
`engine/core/orchestration.py`'s subprocess-per-phase pipeline start-to-finish, shard the work
itself across pods:

- Each phase (or a phase's shard — e.g. "Phase 2 descriptions for components A–F" vs "G–M") runs
  as its own short-lived **Kubernetes Job**, scheduled by a coordinator.
- This reuses the job-queue design already decided for the production platform in
  `01-technology-selection-study.md` (Postgres-as-queue, `SELECT … FOR UPDATE SKIP LOCKED`) rather
  than introducing a new queueing system — the coordinator claims a shard row, launches a Job pod
  for it, marks it done on completion.
- Net effect: **two independent axes of parallelism compound** — M worker pods (this milestone) ×
  N concurrent threads per pod (CC-2) × the inference tier's own batching (CC-3). This is the
  version of the plan that scales past what a single analyzer process's thread pool can drive
  through one `LlmClient`, and it's the natural next step after CC-1–CC-4 are proven on a single
  host.
- Sequencing note: this is the largest, riskiest change (touches orchestration, not just the LLM
  client) and should only be scoped in detail once CC-1–CC-4 are measured — if CC-1–CC-3 alone hit
  the <1h target (likely, given the ~20–40× headroom needed and CC-1+CC-3 together plausibly
  delivering most of that), CC-5 becomes optional headroom for larger-than-"single layer" runs
  rather than a hard requirement. Treat it as a stretch milestone, not a blocker.

---

## 8. CC-6 — Call-volume reduction (independent, stack anytime)

Cheaper before it's parallel is still cheaper after — these compound with CC-1–CC-5 rather than
compete with them:

- Batch multiple small functions' descriptions into one prompt (JSON array in/out) instead of one
  call each — cuts round-trip *count* directly, independent of concurrency.
- Re-verify `EntityCache` hit rate end-to-end on a real repeat run before assuming it's the reason
  re-runs are fast — confirm, don't assume (matches `04-incremental-changes-implementation.md`
  §12's own "measured" framing).
- Reconsider `twoPassDescriptions` defaulting to `true` unconditionally: gate pass 2 to functions
  with more than one distinct caller (single-caller functions gain little from a caller-context
  refinement pass) — cuts Phase 2 call volume roughly in half for leaf-heavy layers.
- Keep `selfReview`/`ensemble` off by default (3–4× multipliers) unless a quality regression
  specifically requires them; if enabled, they parallelize via the same CC-2 wave mechanism.

---

## 9. Risk register

| Risk | Mitigation |
|---|---|
| Concurrent writes corrupt a shared cache file | Audited in §2.2 — `EntityCache` already atomic; confirm `PkbCache` and `.mmdc_cache/` before CC-2/CC-4 touch them |
| `contextvars` stage-attribution silently breaks under threading | Explicit check in §2.2; acceptable degraded mode (`"unspecified"` stage) if not fixed, but should be a decision, not a surprise |
| Self-hosted inference under-provisioned, CC-1's concurrency just queues at the server | CC-3's scaling benchmark (§4.3) determines `maxConcurrency` from measurement, not a guess |
| `llm.maxConcurrency=1` default doesn't get bumped in existing deployed configs, so CC-1 ships with zero user-visible speedup until config is updated | Document the new keys prominently in the startup banner (§2.1) so a run with the old default is visibly flagged as running serial |
| CC-5's orchestrator change destabilizes the existing single-host pipeline | Scoped as optional/stretch (§6); CC-1–CC-4 are the load-bearing milestones for the <1h target |

## 10. Roadmap linkage

This plan is the detail behind `docs/planning/ROADMAP.md`'s V1.x line item "Performance and
LLM-usage optimisation." Suggest updating that line to link here once CC-1 is underway, the same
way V1.1/V1.2 link to `SWE4_PLAN.md`/`SWE2_PLAN.md`.

---

_End of document._
