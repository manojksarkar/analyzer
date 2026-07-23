# Document-Generation Playbook

> How ArtiFex generates each ASPICE document. This is the shared approach behind every doc-type
> ([SWE2_PLAN](SWE2_PLAN.md), [SWE4_PLAN](SWE4_PLAN.md), and later SYS.2 / SWE.1 / SYS.1). Each plan
> describes only what is specific to it and points back here for the common method.

## One model, every document

ArtiFex analyses the C++ codebase once into a single shared model. **Every document is generated from that
same model, so the documents are consistent with each other by construction** — the same function,
interface, or component reads the same way across SWE.2, SWE.3 and SWE.4.

The quality bar is **logical correctness**, not word-for-word match to a client template. A coherent,
traceable, code-derived draft is a valid first version that the client then reviews and refines.

## The code is the anchor

We generate **SWE.3 (detailed design) today**, and the other documents relate to it directly:

- **SWE.4 (unit verification)** *verifies* what SWE.3 designed — it stays at the same unit level and
  transforms design content into test specifications.
- **SWE.2 (architecture)** *rolls up* the component/unit detail into a higher, architecture-level view.

Because SWE.3 already exists, the input side for the next documents is largely in place.

## What we can generate today vs. what needs input

For each document we separate the content into three buckets:

- **Floor** — everything derivable from the code and the existing SWE.3 outputs. This is buildable now and
  forms a shippable first draft with no external input.
- **Gaps** — content that needs information we don't have yet (e.g. requirements, resource/configuration
  semantics). These are stubbed or omitted until a source is available.
- **Optional inputs** — client-provided material (a feature list, a test-case policy, sample documents)
  that *sharpens* a draft but never blocks it.

## Where human judgement is needed

Most content is a deterministic transformation of the model. A few areas are **open-ended derivations** —
there is no single correct answer, only a right-sized draft:

- SWE.2 — collapsing thousands of functions into the product **feature list**.
- SWE.4 — enumerating a **right-sized set of test cases** per function.

For these we **draft, then confirm with the client**, and judge a draft by coverage, stability across
re-runs, and client acceptance on a sample — rather than treating it as a fixed lookup.

## The one shared dependency

Several documents need **requirements traceability** (linking content to requirement / work-item IDs).
That source — Polarion, and ultimately SWE.1 — is **not yet available**, so traceability fields are
deferred across both SWE.2 and SWE.4 until it exists.
