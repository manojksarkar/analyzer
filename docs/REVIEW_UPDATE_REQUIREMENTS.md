# Review & Update — Requirements

Plain-English requirements for letting a reviewer correct LLM-written text in a generated document.
For review and sign-off. The structured engineering contract is
[docs/spec/REVIEW_UPDATE_SPEC.md](spec/REVIEW_UPDATE_SPEC.md).

## What it does

An end user reads the generated document in the UI. Where the LLM's wording is wrong, they correct
it. The correction is saved, shows immediately in the UI, appears in the exported DOCX, and carries
into the next version of the document. The original LLM text is kept so corrections can be undone
and, later, used to improve the model.

## Words we'll use

- **Slot** — a place in the document holding LLM text (one function's description, one flowchart
  node's label).
- **Override** — the human's replacement text for a slot.

**Scale.** Measured on a real project (`vis-aspice1` v1): about **57,000 slots per version** —
~13,000 stored fields, ~42,000 flowchart node labels, ~2,000 others. Almost none are ever edited, so
the design must be cheap when a version has zero overrides.

## 1. What can be edited (7 kinds)

| # | slot kind | appears in |
|---|---|---|
| 1.1 | function description | 1.2 Scope table, interface table, per-function Requirements, SWE.4 intro |
| 1.2 | behaviour input name | per-function table, Dynamic Behaviour table |
| 1.3 | behaviour output name | same |
| 1.4 | behaviour description | Dynamic Behaviour Requirements + the behaviour diagram arrows — **a list, edited as one block** |
| 1.5 | unit description | 1.2 Scope table — *needs prerequisite 10.1* |
| 1.6 | struct description | unit header table — *needs prerequisite 10.1* |
| 1.7 | flowchart node label | flowchart picture **and** every SWE.4 Test Step — one edit changes both |

- **1.8** SWE.4 Test Steps are **read-only**. Their wording *is* the flowchart node label; edit it
  there. There is no second entry point.
- **1.9** Not editable, because it never reaches a document: function phases, and the project /
  component / file summaries. These are **context** used to generate flowchart node labels.
- **1.10** Not editable, because it isn't LLM-written: interface IDs, direction, source/destination,
  visibility, data ranges, and the 1.1 / 1.2 introduction text (config templates).

## 2. Identifying a slot

- **2.1** Every slot has a stable id. Use ids that already exist — don't invent new ones.
- **2.2** Function, struct description and behaviour in/out names → the existing `entity_key`
  (unique per project).
- **2.3** Unit description → the existing `unit_key` (`Component|Unit`).
- **2.4** Behaviour description → the row's `(function id, external unit function)`.
- **2.5** Flowchart node label → `(version, entity_key, node id)`.
- **2.6** Node ids (`n0, n1, n2…`) are positional but **deterministic for identical source**, so they
  are stable exactly when the function is unchanged — which is the only case where an override
  carries forward.
- **2.7** If a function is **renamed or deleted**, its override is orphaned. The override is **kept
  and marked orphaned**, never auto-deleted — it is the user's work and it is training data, and a
  rename may be reverted.

## 3. Storing an override

- **3.1** Stored in the database, beside the model. Two things with different jobs: the **model**
  holds the text the document uses; the **override record** holds the LLM original, the human text,
  who edited it and when.
- **3.2** An override belongs to **one version**. Editing v3 does not change v1. A released version
  never changes retroactively.
- **3.3** Store **both** texts — the LLM's original and the human's replacement. Without the original
  there is no undo and no training pair.
- **3.4** Every edit is recorded, but history is **bounded**: keep the last **N** human edits per
  slot, N configurable. **The LLM original is never evicted** and is not counted against N.
- **3.5** Reading the current text is a direct lookup, not "the newest row in history" — it is read
  on every page render, so read speed must not depend on how often a slot was edited.
- **3.6** **No editable text may be set to empty** — any kind, not just descriptions.

## 4. Making it appear

- **4.1** The **model is the single source of truth**. View outputs (interface tables, flowcharts,
  behaviour rows) are derived from it and never written to directly.
- **4.2** Saving an override does two things as **one operation**: update the model, and re-derive
  the affected component's view rows. It must not be able to half-succeed.
- **4.3** The HTML view renders live from the database, so the correction shows on the next page
  load. No pipeline run needed.
- **4.4** Export reads the same derived rows, so the DOCX shows it too.
- **4.5** **Export verifies rather than assumes.** Before exporting, check that no override is newer
  than the last derivation; if one is, re-derive first or refuse and say so. This is what makes it
  reliable rather than merely correct — `reexport --from-phase 4` skips the step that would
  otherwise refresh the text.

## 5. Cascading — what regenerates when text is corrected

Some LLM text is generated **from** other LLM text. Correcting the input must regenerate what was
built on it, or the document keeps prose derived from wording the human already rejected.

| edited | must regenerate |
|---|---|
| **5.1** function description | its unit's description · the descriptions of its **direct callers** · behaviour call descriptions where it is caller or callee |
| **5.2** global description | its unit's description |
| **5.3** unit description | nothing |
| **5.4** struct description | nothing |
| **5.5** behaviour in/out name | nothing — built from source, parameters, globals, return type |
| **5.6** behaviour description | nothing |
| **5.7** flowchart node label | nothing |

- **5.8** **One level only.** Correcting A regenerates its direct callers; it does not continue up to
  their callers. Full transitivity could regenerate hundreds of functions from one edit, each costing
  an LLM call. A later full regeneration picks up the rest.
- **5.9** A cascade **never overwrites a slot that already has a human override**.
- **5.10** Flowchart node labels are **not** affected by a description edit. They are generated from
  the source code through the summary chain, not from descriptions — which is what keeps the cascade
  small.

## 6. Across versions

- **6.1** Generating a new version from a baseline: a function whose code is **unchanged** keeps the
  human text; a function whose code **changed** gets fresh LLM text describing the new code.
- **6.2** This works through the existing carry-forward, which copies from the baseline's **model**.
  **The LLM cache is not touched.**
- **6.3** A flowchart node override carries forward only when the function's source hash is
  unchanged.
- **6.4** A full regeneration with no baseline uses fresh LLM text. Overrides are **kept, not
  deleted** — just not applied to that version.

## 7. Images

- **7.1** Editing a flowchart node label re-renders that flowchart's image.
- **7.2** Editing a behaviour description re-renders that behaviour diagram.
- **7.3** Rendering is **asynchronous**.
- **7.4** **Export waits for pending renders.** Otherwise an export made seconds after an edit ships
  the new text everywhere and the old picture.
- **7.5** The document never shows a stale image.

## 8. UI and API

- **8.1** List the slots in a document, with each one's current text and whether it has been
  overridden.
- **8.2** Read one slot's current text — so the UI can confirm an update landed.
- **8.3** Update one slot. **One API call per edit** — a reviewer edits one piece of text at a time;
  no batch operation.
- **8.4** Undo — restore the LLM's original text.
- **8.5** Anyone who can view the document can see the text. Corrected text is **not highlighted** —
  it reads as normal document text.
- **8.6** Project admins and project members may edit.
- **8.7** Two people editing the same slot: **last write wins**.
- **8.8** No approval step in this version. An edit takes effect immediately.

## 9. For later (store now, use later)

- **9.1** Corrections are kept as **pairs** — what the LLM wrote, and what the human replaced it
  with. A correction without its original teaches nothing.
- **9.2** Store the context the LLM was given, and which model and prompt version produced the
  original, so a correction can still be interpreted months later.
- **9.3** Nothing is trained or self-learned in this feature. Storage only.

## 10. Prerequisites (separate pieces of work)

- **10.1** Unit and struct descriptions are currently generated **during DOCX export and stored
  nowhere**. They must move into Phase 2 and be stored before they can be edited. Two side benefits:
  the HTML view can show them at all, and every export stops re-paying for them.
- **10.2** All view output moves into the database; `output/` keeps only `.png` and `.docx`. Every
  flow — including export — reads from the database. Storage is largely done; **reading** is not.

## 11. What must be proven, not assumed

Each of these gets a test.

- **11.1** An override reaches the exported DOCX — including via `reexport --from-phase 4`.
- **11.2** An override reaches the **next version** when the function is unchanged.
- **11.3** A **changed** function gets fresh LLM text, not a stale human note about the old code.
- **11.4** Export never ships stale text or a stale image.
- **11.5** The LLM cache is not written to by this feature.
- **11.6** Correcting a function description regenerates its unit description and its direct callers,
  and leaves flowchart node labels untouched.
- **11.7** A cascade does not overwrite a slot that already has a human override.

## 12. Known limitations

- An override is orphaned by a rename or delete. It is kept, not migrated — the text cannot be
  assumed still correct for a renamed function.
- The caller cascade is one level, so a deep call chain is only fully refreshed by a later full
  regeneration.
- An override does not carry forward when the function's source changed, by design.
- Corrected text is not visually distinguished, so a second reviewer cannot tell what has already
  been corrected. This matters once the approval step is added.

## 13. Open items

- [ ] Approval workflow — out of scope for this version (request → project manager approves).
- [ ] Default value for **N** in 3.4.
- [ ] Whether orphaned overrides (2.7) need a cleanup command, or accumulate harmlessly.
- [ ] Design document — not written yet.
