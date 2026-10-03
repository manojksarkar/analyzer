# Review and approval — design

How a generated document gets a reviewer, is reviewed, and is approved; and how a version's approval
follows from its documents. Built 2026-10-01 on the recommendations of the research notes (all nine
taken as recommended; the open questions at the end remain). HTTP contract:
[REVIEW_APPROVE_API_SPEC](../spec/REVIEW_APPROVE_API_SPEC.md) · screens: [docs/ui-mockups/](../ui-mockups/)
(`documents.html#review`, `#changes`, `#approve`, `#approved`; `project-detail.html`, `versions.html`).
Correcting the LLM's text is the separate review & update feature ([REVIEW_UPDATE_DESIGN](REVIEW_UPDATE_DESIGN.md)).

## Principles

1. **A document is approved, not a section.** A version is Approved when all its documents are —
   derived, never a separate click.
2. **Two roles, no new ones** (D-8). A *reviewer* is whoever is assigned to a document, not a role.
   The project **admin** approves.
3. **Approval is evidence.** Every step is an event with who, when and a comment, and an approval
   records the exact Word file it approved.
4. **What was approved stays approved.** An approved document is locked; changing it means reopening it,
   on the record. A new version keeps the approval of a document whose content did not change.
5. **One word per state**, everywhere: In review · Ready for approval · Changes requested · Approved.

## Roles

| | Admin | Developer |
|---|---|---|
| Assign / re-assign / remove a reviewer | ✓ | — |
| Claim an unassigned document (become its reviewer) | — | ✓ |
| Correct the LLM's text (review & update) | ✓ | ✓ (any member, as built) |
| Submit a document for approval | ✓ (own reviews) | ✓ when they are its reviewer |
| Approve · Request changes · Reopen | ✓ | — |
| Re-export | ✓ | — |
| Read, download | ✓ | ✓ |

A pending (invited, not accepted) member can do nothing until they accept.

## A document's life

```
                     a run creates the document
                                 │
                                 ▼
                     ┌────────────────────────┐
                     │       IN REVIEW        │  no reviewer yet → "Needs a reviewer"
                     │  reviewer corrects the │  admin assigns · developer claims
                     │  text (review & update)│
                     └───────────┬────────────┘
                                 │ reviewer: Submit for approval  (comment)
                                 ▼
                     ┌────────────────────────┐
              ┌──────│   READY FOR APPROVAL   │──────┐
              │      └────────────────────────┘      │
 admin: Request changes                        admin: Approve
 (comment required)                            (only when its Word file is up to date;
              │                                 records the file's hash)
              ▼                                      ▼
  ┌────────────────────────┐            ┌────────────────────────┐
  │   CHANGES REQUESTED    │            │        APPROVED        │  locked: no corrections,
  │ reviewer fixes, then   │            │                        │  the Word file is the one
  │ Submit for approval ───┼──▶ READY   │                        │  that was approved
  └────────────────────────┘            └───────────┬────────────┘
                                                    │ admin: Reopen (reason required)
                                                    ▼
                                               IN REVIEW (same reviewer)
```

An admin reviewing alone may also Approve straight from In review — the event says so.

## Who does what, start to finish

```
 ADMIN                              REVIEWER (developer)             THE APP
 ─────                              ────────────────────             ───────
 Run v1.1 ──────────────────────────────────────────────────────▶ 6 documents, In review, no reviewer
                                                                    version v1.1: 0 of 6 approved
 Assign: Bob → Util, Lib (4 docs)
         Alice → Sample Core (2) ───────────────────────────────▶ event "assigned"; notifies Bob, Alice
                                    sees My reviews (4)
                                    opens Util SWE.3 → Edit
                                    corrects 3 texts ──────────────▶ banner: Word file not up to date
                                    Submit for approval
                                    "Checked every function." ─────▶ event "submitted"; notifies admins
 sees Ready for approval (1)
 opens Util: Bob's comment,
 3 corrections, Word file stale
 Re-export ─────────────────────────────────────────────────────▶ Word file up to date
 Approve ───────────────────────────────────────────────────────▶ event "approved" + file hash;
                                                                    Util locked; notifies Bob
 Lib: Request changes
 "Input names of libAdd are vague." ────────────────────────────▶ event; notifies Bob
                                    fixes, Submit again ────────────▶ Ready for approval
 Approve … until 6 of 6 ────────────────────────────────────────▶ version v1.1 Approved (derived)
 Run v1.2 (Util changed) ───────────────────────────────────────▶ Lib, Sample Core: Approved
                                                                    ("carried from v1.1");
                                                                    Util: In review, Bob kept, notified
```

## A version's status — derived

```
 any document not Approved ───▶ IN REVIEW   "9 of 15 approved"
 every document Approved   ───▶ APPROVED    by the last approver, at the last approval
 a document reopened       ───▶ back to IN REVIEW
```

## Rules

| Action | Who | From | Guard | Records | Notifies |
|---|---|---|---|---|---|
| Assign / re-assign | admin | not Approved | reviewer is an active member | `assigned` (from → to) | the new reviewer |
| Claim | developer | In review, no reviewer | — | `assigned` (self) | admins |
| Submit for approval | the reviewer, or admin | In review, Changes requested | comment ≤ 2,000 chars | `submitted` + comment | admins |
| Approve | admin | Ready, or In review | the document's Word file is up to date (R9 for its component) | `approved` + comment + DOCX hash | the reviewer |
| Request changes | admin | Ready | comment required | `changes_requested` + comment | the reviewer |
| Reopen | admin | Approved | reason required | `reopened` + reason | the reviewer |
| Correct a text | member | not Approved | refused (409 `DOCUMENT_APPROVED`) while a document printing the text is approved | the correction's own history | — |
| Bulk approve | admin | Ready only | each as Approve; the dialog names the count and skips the rest | one event each | — |

## Where it meets the rest

| Situation | Then |
|---|---|
| A new version (incremental or full) | Each document's content fingerprint (`compare_render.render_fingerprint`) against the baseline's: **same and approved there → Approved**, event `carried` naming the version; else In review, the baseline's reviewer kept. |
| A correction on an approved document | Refused — reopen it first. |
| A re-export | Allowed; it cannot change an approved document's text, so its file hash still matches. |
| Download | Unchanged. The reader's banner already warns when a Word file lacks corrections. |
| SWE.3 and SWE.4 of one component | Two documents, reviewed and approved separately. A label correction changes both, so it is refused when either is approved. |

## Screens

| Screen | What changes |
|---|---|
| **Documents** | Status column with the four states; Reviewer column ("Unassigned" in amber); version bar "v1.1 · 2 of 6 approved"; real bulk **Assign** (picker) and **Approve** (Ready ones only, confirm). |
| **Reader → Review tab** | Replaces the placeholder sections: status, reviewer, Word-file status, the action for this role and state (Submit with comment · Approve / Request changes · Reopen), and the **activity timeline**. Approved: a lock banner; Edit is off. |
| **Overview** | Admin: Ready for approval · Needs a reviewer · Changes requested. Developer: My reviews, with what each needs. |
| **Versions** | The derived status and "N of M approved"; who approved a fully approved version, and when. |
| **Bell** | Assigned, submitted, changes requested, approved, reopened. |
| Removed | "Mark Complete", Compare's per-section Accept/Decline/Submit (Compare stays for reading changes), the Due Date column, the 4 placeholder sections. |

## API and data

| Change | Detail |
|---|---|
| `documents.status` | `in_review` · `submitted` · `changes_requested` · `approved`, enforced; + `approved_by`, `approved_at`, `content_fingerprint` |
| One reviewer | `document_assignments` unique on `document_id`; assign = replace |
| **New** `document_review_events` | `document_id, version_id, kind (assigned, submitted, approved, changes_requested, reopened, carried), actor_id, at, comment, payload` (from/to reviewer, DOCX hash, carried-from version) |
| Routes | [REVIEW_APPROVE_API_SPEC](../spec/REVIEW_APPROVE_API_SPEC.md) §3 — the existing assignment, submit, approve and request-changes routes keep their paths with the rules above; new: `reopen`, the document and project event feeds. Every route checks the document belongs to the project. |
| Retired | `PATCH …/{doc}` status, `PATCH …/sections/{key}`, `approve-all` by version, `PATCH /versions` status |
| Version | status computed from its documents in `GET /versions`; `PATCH /versions` status no longer accepted |
| R9 | `?document_id=` — readiness for one document's component and document type (`export_guard.staleness(…, component=)`) |
| Corrections (R3, R6, R8, R4) | 409 `DOCUMENT_APPROVED` when an approved document prints the text |
| Notifications | written by each event, to the people in the Notifies column |
| Existing data | `approved` documents stay approved, with one `approved` event "before the log"; the newest assignment per document is kept; sections stay in the table, unused |

## Open questions

1. **A correction to an approved document** — refuse (above), or allow it and reopen the document
   automatically?
2. **Approve straight from In review** — allowed (above) for an admin who reviews alone, or always two
   people?
3. **Carry-over** — a document whose code did not change but whose *neighbour's* did can still change
   (a caller's description, a behaviour row). The fingerprint is of the rendered document, so that is
   caught; is "same rendered content" the right bar?
4. **Due dates and the claim pool** — the mockups have them; nothing here needs them. Later?
