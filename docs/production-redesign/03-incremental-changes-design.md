# Incremental Changes Design — C++ Analyzer Production Platform

| | |
|---|---|
| **Document** | Incremental Changes (Delta Regeneration) Design |
| **Project** | C++ Codebase Analyzer — Production Platform (POC → Production) |
| **Status** | Draft for Review |
| **Version** | 1.0 |
| **Date** | 2026-06-12 |
| **Prepared by** | _______________________ |
| **Reviewed by** | _______________________ |
| **Audience** | Engineering Leadership / Architecture Review |

---

## 1. Purpose & Goal

A **full** document generation re-runs the entire pipeline — LLM enrichment and flowchart rendering for **every** function — which takes **hours** (e.g. ~5 hours for a 1,000-function project, dominated by the rate-limited LLM calls). When a user makes a **small** code change and regenerates, repeating the whole run is wasteful.

**Goal:** detect what changed since the last generation, **regenerate only the affected parts, reuse everything else**, and update the document — turning **hours into minutes** for small changes, with **no stale content**.

This is "incremental build" applied to documents — the same principle behind `make`, `ccache`, and Bazel.

---

## 2. Scope (v1) and deferrals

**In v1:**
- **One content hash per code entity** (function / global / macro / type) for change detection.
- **`git diff` (files) + entity hashing (entities)** for change detection.
- **Dependency-graph impact analysis** to find everything affected by a change.
- **Selective regeneration** of the expensive LLM outputs for affected entities; **reuse** stored outputs for the rest.
- **Reassemble** the document.
- **Latest document + commit per branch.**

**Deferred to later phases (noted where relevant):**
- **Per-artifact hashing** — finer-grained reuse (e.g. a comment-only change reuses the flowchart).
- **Image-render cache** — skip re-rendering unchanged flowcharts (tied to the object-storage phase).
- **Full version history** — keeping many versions/branches with Git-style deduplication.
- **Object storage** for images / documents at scale.

---

## 3. The core idea

Four steps:

```
Detect  ->  Impact  ->  Regenerate (only affected)  ->  Reassemble
```

A function's expensive work (LLM **description** + flowchart **labeling**) is **reused** if it didn't change and **regenerated** only if it (or something it depends on) changed. The savings come from skipping the **rate-limited LLM work** for the ~99% of functions that didn't change.

**Concrete:** if ~1% of functions change, plus their dependents (~5% total), we re-run the LLM for **~50 functions instead of 1,000** → roughly **5 hours becomes minutes** of LLM work (plus parse and reassembly).

---

## 4. Change detection

### 4.1 Two layers — git for files, hashing for entities

| Layer | Tool | Why |
|---|---|---|
| **Which files changed** | `git diff base..new --name-only` | a **clean file list** — git's core competency (we do *not* parse its scattered hunk output) |
| **Which entities changed** | **entity hashing** (parse the changed files, hash each entity, compare to stored) | precise, formatting-insensitive, no diff-text parsing |

So git narrows *which files to parse*; hashing pins down *which entities actually changed* inside them.

### 4.2 What we hash (the four entity types)

Everything the document renders from user code is one of these. We store **one hash per entity**:

| Entity | What goes into the hash (a change here → regenerate) | Identity key |
|---|---|---|
| **Function** | signature (params + return) **+ body + doc-comment + visibility** | `module\|unit\|qname\|paramTypes` |
| **Global variable** | type + name + initializer + visibility | `module\|unit\|qname` |
| **Macro / `#define`** | name + full macro text/value | `file\|name` |
| **Type** (struct/class, enum, typedef) | full definition (fields / values / underlying) | `qname\|file` |

*On keys (avoiding name collisions):* a key is **never** just the bare name — it always includes the **defining file** (`file|name`, `file|qname`), and the **line/location** where two could still collide (a macro redefined in the same file, or anonymous/local types). So two same-named macros or types in **different files** are treated as **distinct** entities.

*Why hash globals/macros/types separately:* when you change a global, macro, or type, the functions that *use* it do **not** change their own code — e.g. a function still just writes `MAX` even after `#define MAX` changes value, so the **function's** hash would not move. We therefore hash these entities **on their own** to detect the change, and impact analysis (§5) then refreshes the functions that use them.

### 4.3 Hash properties

- **Token-based** (via libclang) → ignores whitespace / indentation / CRLF↔LF, but **includes comments** (they feed descriptions).
- **Full SHA-256** (32 bytes), never truncated → collisions are effectively impossible.
- **One uniform function** applied to each entity's source extent (same for all four types).
- Stored as `{ entity_key → hash }` **per (project, branch)**.
- **Size (worked example):** 1 project with **20,000 functions + 3,000 other entities = 23,000 hashes × 32 bytes ≈ 0.7 MB per branch**. Kept for **10 branches** → **≈ 7 MB** (≈ 30 MB once the entity key and row overhead are counted).

### 4.4 Change classification

Compare current `{key → hash}` against the stored set for that branch:

| Condition | Meaning |
|---|---|
| key present, hash same | unchanged → **reuse** |
| key present, hash differs | **changed** → regenerate |
| key only in current | **new** |
| key only in stored | **deleted** |

A **move / rename** appears as **delete(old key) + add(new key)** — the key encodes identity/location, so it is caught automatically, and the "added/deleted entity affects its callers" rule (§5) handles the fallout.

---

## 5. Impact analysis

Detecting *what changed* is not enough; we must regenerate everything that **depends on** it.

### 5.1 Direction — changes flow **up** to callers/users

A function's document content is built from its **callees** (its description uses callee context; its flowchart references them; it inherits their globals). So when something changes, the impact flows **upward to everything that uses it** — *not* down to its callees.

### 5.2 The dependency axes

We propagate the changed set across **all** of these (not just calls):

| Axis | Edge followed | Effect |
|---|---|---|
| **Call graph** | callee → **transitive callers** | callers regenerate |
| **Type usage** | type → users | functions/globals using the type |
| **Globals** | global → accessors | accessors + their transitive callers |
| **Macros** | macro → users | functions referencing the macro |
| **Containment** | function → file → module → project | file/module/project **summaries** refresh |
| **Diagrams** | a call-edge add/remove | the affected unit/module/behaviour **diagrams** |
| **Cross-group** | the **whole-project** graph | regenerate the entity in **every** group it appears in |

### 5.3 The hard cases (handled, not ignored)

| Case | Handling |
|---|---|
| **Indirect calls** (function pointers / callbacks) and **virtual dispatch** | static analysis can't resolve these exactly → **over-approximate**: treat a virtual call as an edge to **all overrides**, a function-pointer call as an edge to **any address-taken function**. Over-regenerate a little; **never miss**. |
| **Move / rename** | the entity **key** changes → detected as delete + add → its callers are pulled in by the add/delete rule (§4.4). |

### 5.4 Algorithm

Reverse-reachability traversal (BFS) over the dependency edges, with a visited-set that safely handles recursion/cycles. In PostgreSQL this is a `WITH RECURSIVE` query, or a **materialized closure table** for hot reads. The dependency edges are stored in the database.

### 5.5 Worked example

```
func1 -> a -> b -> c        (all of these reach c)
func2 -> x -> y             (none reach c)
z -> c                      (z reaches c)
```

If **`c` changes**, the impact set is **{ c, b, a, func1, z }** — the transitive callers of `c`.
`func2, x, y` are **not** regenerated: they never call `c`, so `c` changing cannot make them stale.

---

## 6. Selective regeneration

For the **impact set only**:
- re-run the **LLM** (description, flowchart labeling),
- re-derive **edges / direction / behaviour names**,
- recompute affected **summaries** and **diagrams**.

For **everything else**: **reuse** the stored outputs (a cache hit keyed by the entity's hash). This is where the time is saved — the rate-limited LLM work is skipped for unchanged entities.

> **v1 note on images:** the stored Mermaid scripts and LLM descriptions are reused for unchanged entities (saving the dominant LLM cost). **Image rendering** is re-done during reassembly in v1; an **image-render cache** (to skip re-rendering unchanged flowcharts) is a later optimization tied to the object-storage phase.

---

## 7. Reassemble the document

Build the updated document from its pieces — **reused** (unchanged) plus **regenerated** (affected). We **reassemble from pieces** rather than editing the existing document in place: it is simpler and far more reliable than patching the document's internal structure. The result is stored as the branch's **new latest document**.

---

## 8. Branch & baseline handling

We keep the **latest commit + latest document per branch** (not one global commit, and — in v1 — not a full history).

**The rule:** an incremental diff is valid **only if the stored commit is an ancestor of the new commit.** Otherwise the diff is not a valid baseline, and we do a **full generation**.

```
on regenerate(project, branch, new_commit):

    base = last_generated_commit[project, branch]      # per-branch baseline

    if base is None:                                    # first time for this branch
        -> FULL generation
    elif git merge-base --is-ancestor base new_commit:  # base is a true ancestor
        -> INCREMENTAL  (git diff base..new_commit)
    else:                                               # rebase / force-push / diverged
        -> FULL generation                              # safe fallback, never wrong

    store last_generated_commit[project, branch] = new_commit
    store latest_document[project, branch]        = new_document
```

This makes the **first generation for a new branch** a full generation, and every subsequent regeneration on that branch incremental against **its own** baseline. The `--is-ancestor` check also catches **history rewrites** (rebase/force-push) and routes them to a safe full regeneration.

---

## 9. End-to-end flow

```
TRIGGER: regenerate(project, branch, new_commit)        [clone / pull repo]
   |
   v
[0] BASELINE CHECK
    base = last_commit[project, branch]
    if base is None  OR  not ancestor(base, new_commit)  ->  FULL generation -> done
   |
   v   (base is an ancestor)
[1] CHANGE DETECTION
    git diff base..new_commit --name-only          ->  changed FILES
    parse changed files -> entity hashes vs stored ->  { changed, new, deleted } ENTITIES
   |
   v
[2] IMPACT ANALYSIS
    propagate over the dependency graph
    (calls / types / globals / macros / containment)
                                                   ->  REGENERATION SET (+ summaries, diagrams)
   |
   v
[3] SELECTIVE REGENERATION
    re-run LLM for the REGENERATION SET
    reuse stored outputs for everything else
   |
   v
[4] REASSEMBLE
    build the updated document from reused + regenerated pieces
    store as the branch's latest document; baseline = new_commit
```

---

## 10. Reliability & safety

- **Bias to over-regenerate, never to stale.** Every ambiguous case (indirect/virtual calls, formatting noise, non-ancestor commits) is resolved by regenerating **more**, never less. Over-regeneration costs minutes; stale output is a correctness defect.
- **Full-generation fallback** for first-time branches, rebases, force-pushes, and diverged histories — always correct.
- **Manual "force full regeneration"** option for the cases static analysis cannot see.
- **Operator-side invalidation** (separate path): if the analyzer's recipe changes (LLM model, prompts, render settings, engine version), all caches are invalidated by an operator action — **not** part of the user's code-diff flow.
- *(Optional)* a **periodic full regeneration** (e.g. per release) to self-heal any missed incremental edge case.

---

## 11. Technology fit — no new database or system

The incremental feature is served entirely by the chosen stack (this is *why* we favoured PostgreSQL-with-CTEs over a graph DB):

| Need | Served by | New? |
|---|---|---|
| Store entity hashes | PostgreSQL — tables | existing |
| Store the dependency graph (edges) | PostgreSQL — tables | existing |
| Impact analysis (transitive closure) | PostgreSQL recursive CTE / closure table | existing |
| Per-branch baselines | PostgreSQL | existing |
| Run the incremental job | Postgres job queue + stateless workers | existing |
| **Clone repo + `git diff` + `git merge-base`** | **`git` CLI in the worker image** | ➕ add (a tool) |
| **Clone private repos** | **Git credentials** (SSH deploy key or HTTP access token) from a **secrets store** | ➕ add (a secrets flow) |

So the **only** additions are around **git ingestion**, which the production "register a git URL" flow needs regardless. No new database, queue, or storage system.

**Why `git merge-base`?** It answers *"is commit A an ancestor of commit B?"* We use it as the **gate** that decides **incremental vs full** regeneration: if the stored baseline is a true ancestor of the new commit, we diff incrementally; otherwise (rebase / force-push / diverged / first-time branch) we fall back to a **full generation** (see §8). Without it, we could apply a diff against the wrong baseline and produce a wrong document.

**Repo credentials are deployment-independent (not tied to on prem or Kubernetes).** To clone a private Bitbucket repo, the worker needs a credential — an **SSH deploy key** or an **HTTP access token / app password**. *Where* it is stored depends on the deployment: **Kubernetes Secrets** if on K8s; otherwise a **secrets manager** (e.g. HashiCorp Vault) or a restricted-permission credential injected into the worker's environment. The **project owner/admin supplies the credential when registering the repository**; it is stored **encrypted** and handed to the worker only at clone time — **never hardcoded**.

---

## 12. Summary

> **On each regeneration:** check the per-branch baseline with `git merge-base --is-ancestor` (else full regen); use `git diff` to find changed files; hash the entities (functions, globals, macros, types) in those files to find the changed set; expand it across the dependency graph (calls + types + globals + macros + containment, over-approximating the un-resolvable calls) to the full impact set; re-run the LLM for **only** that set, reuse stored outputs for the rest, and reassemble the document as the branch's new latest version.

This delivers **correct, fast** incremental updates — **hours → minutes** for small changes — on the **existing** technology stack, with the heavier optimizations (per-artifact hashing, image caching, full version history) clearly deferred to later phases.

---

_End of document._
