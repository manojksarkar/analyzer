# Review and approval — HTTP contract

How a document is assigned a reviewer, reviewed, approved, sent back and reopened, over HTTP. Update
this file first when the contract changes, then the code and the tests.
Design (why, rules, screens): [REVIEW_APPROVE_DESIGN](../design/REVIEW_APPROVE_DESIGN.md) · mockups:
[docs/ui-mockups/](../ui-mockups/) (`documents.html#review`, `#changes`, `#approve`, `#approved`) ·
correcting the LLM's text is a separate contract: [REVIEW_UPDATE_API_SPEC](REVIEW_UPDATE_API_SPEC.md).

All paths are under `/api/v1`. `D` = `/projects/{project_id}/documents`, `V` =
`/projects/{project_id}/versions/{version_id}`. Errors use the API's envelope:
`{"detail": {"code", "message", "status"}}`.

## 1. States

| `status` | Label | Set by |
|---|---|---|
| `in_review` | In review | a run; `reopen` |
| `submitted` | Ready for approval | `submit-review` |
| `changes_requested` | Changes requested | `request-changes` |
| `approved` | Approved | `approve`, bulk approve, or a run carrying an approval forward |

A **version** is `approved` when it has documents and every one is approved, else `in_review` — derived,
never set by hand. An approved document is **locked**: no corrections to the text it prints.

## 2. Shapes

**User ref** — `{"user_id", "name", "initials"}`.

**Document** — every route that returns one:

```json
{
  "id": "docc1442", "name": "Util", "subtitle": "Detailed Design", "process": "SWE.3",
  "layer": "Layer1", "group": "Layer1.Util", "status": "submitted", "version_id": "verf6223ff0",
  "due_date": null, "created_at": "…", "updated_at": "…",
  "assignees": [{"user_id": "u2", "name": "Bob Kumar", "initials": "BK"}],
  "reviewer": {"user_id": "u2", "name": "Bob Kumar", "initials": "BK"},
  "review": {
    "comment": "Checked every function; corrected 3 texts.",
    "changes_comment": null,
    "approved_by": null, "approved_at": null, "approval_comment": null, "docx_sha256": null,
    "carried_from": null,
    "last_event": {"…": "an Event"}
  }
}
```

- `reviewer` — the one reviewer, or `null` ("Needs a reviewer"). `assignees` is the same person as a
  list of 0 or 1, kept for older clients.
- `review.comment` — the reviewer's comment at the last submit; `changes_comment` — the admin's at the
  last request for changes (cleared by the next submit).
- `approved_by` / `approved_at` / `approval_comment` / `docx_sha256` — set while `approved`, `null` otherwise.
  `docx_sha256` is the SHA-256 of the Word file that was approved (a copy is kept; see §4).
- `carried_from` — `{"version_id", "tag"}` when the approval came from an earlier version whose content
  was the same; else `null`.

**Event** — one step of a document's review record:

```json
{"id": "rev1a2b3c4d", "document_id": "docc1442", "version_id": "verf6223ff0", "kind": "approved",
 "actor": {"user_id": "u1", "name": "Alice Admin", "initials": "AA"}, "at": "2026-10-01T09:40:00+00:00",
 "comment": "Corrections read well.", "payload": {"docx_sha256": "9f2c…", "direct": false}}
```

| `kind` | `actor` | `payload` |
|---|---|---|
| `generated` | `null` (the run) | `{"kept_reviewer_from": "<version tag>"}` when the reviewer came from the baseline |
| `carried` | `null` (the run) | `{"from_version_id", "from_tag"}` |
| `assigned` | admin | `{"from_user_id": "u2" \| null, "to_user_id": "u3"}` |
| `unassigned` | admin | `{"user_id"}` |
| `claimed` | the developer | `{}` |
| `submitted` | reviewer or admin | `{}` (the comment is `comment`) |
| `approved` | admin | `{"docx_sha256", "direct": true \| false}` — `direct`: approved from In review |
| `changes_requested` | admin | `{}` |
| `reopened` | admin | `{}` (the reason is `comment`) |

## 3. Routes

| # | Route | Who | Does |
|---|---|---|---|
| A1 | `POST D/{doc}/assignments` | admin | Make one user the reviewer, replacing any |
| A2 | `POST D/assignments/batch` | admin | The same for several documents |
| A3 | `DELETE D/{doc}/assignments/{user_id}` | admin | Remove the reviewer |
| A4 | `POST D/{doc}/assignments/self` | developer, reviewer | Claim: become the reviewer of a document that has none |
| A5 | `POST D/{doc}/submit-review` | the reviewer, or admin | In review / Changes requested → Ready for approval |
| A6 | `POST D/{doc}/approve` | admin | Ready for approval (or In review: direct) → Approved |
| A7 | `POST D/{doc}/request-changes` | admin | Ready for approval → Changes requested |
| A8 | `POST D/{doc}/reopen` | admin | Approved → In review |
| A9 | `POST D/approve-all` | admin | Approve the listed documents that are ready; report the rest |
| A10 | `GET D/{doc}/events` | member | The document's record, newest first |
| A11 | `GET /projects/{project_id}/review-events` | member | The project's record, newest first |
| A12 | `GET D`, `GET D/{doc}` | member | Documents, with `reviewer` and `review` |
| A13 | `GET D/stats` | member | Counts per state |
| A14 | `GET /projects/{project_id}/versions`, `GET V` | member | Versions, status derived, with `review` counts |
| A15 | `GET V/export-readiness?document_id=` | member | R9 for one document: is its Word file out of date, and why |
| A16 | `GET /notifications`, `PATCH /notifications/{id}/read` | the user | Notifications, read ones included on request |
| A17 | `POST V/documents/register` | admin | Record the version's Word files that have no document yet, and open their review |
| A18 | `GET /reviews/mine` | the user | The documents the caller reviews, across their projects |
| A19 | `GET /projects/{project_id}/members` | member | Each member gains `open_reviews` |
| A20 | `POST /projects/{project_id}/members/invite` | admin | Add a person as an active member; create their account if there is none |
| A21 | `POST /auth/change-password` | the user | Replace one's own password (the temporary one first) |

"Admin" and "member" mean an **active** member (an invited, not yet accepted, member is neither) or a
superuser. Every route checks that the document belongs to the project in the path (404 otherwise).
A member's role is `admin`, `developer` or `reviewer` (any other value: **422** on invite and role
change); a `reviewer` acts as a developer does here — reviews, claims, submits.

### A1 — assign

**Request body** `{"user_id": "u3"}` (`{"user_ids": ["u3"]}`, exactly one, is accepted too).
**200** `{"document": Document}`. Event `assigned`; notification to the new reviewer, and to the one replaced.
**404** document or user · **409** `DOCUMENT_APPROVED` · **422** `NOT_A_MEMBER` (not an active member) or
more than one user.

### A2 — batch assign

**Request body** `{"document_ids": ["d1", "d2"], "user_id": "u3"}`.
**200** `{"assigned": ["d1"], "skipped": [{"document_id": "d2", "code": "DOCUMENT_APPROVED", "message": "…"}]}`.
A document of another project is skipped with `NOT_FOUND`. One notification to the reviewer.

### A3 — remove the reviewer

**204**. Event `unassigned`. **409** `DOCUMENT_APPROVED`.

### A4 — claim

**200** `{"document": Document}`. Event `claimed`; notification to the project's admins.
**403** not an active developer or reviewer (an admin assigns) · **409** `HAS_REVIEWER` or
`DOCUMENT_APPROVED`.

### A5 — submit for approval

**Request body** `{"comment": "Checked every function; corrected 3 texts."}` — required, 1–2,000 characters.
**200** `{"document": Document, "word_file": {"state", "job_id", "blocked_by"}}`. Event `submitted`;
notification to the admins (not the actor).
**403** neither its reviewer nor an admin · **409** `WRONG_STATE` (not In review / Changes requested) or
`NO_REVIEWER` · **422** empty or too long.

**Its Word file is updated for the approval** ([WORD_FILE_UPDATES §4.4](../design/WORD_FILE_UPDATES.md#44-a5--submit-for-approval)).
After the submit, when the document's Word file is out of date, the server starts the update of its
component (`reason: "submit"`, started by the submitter). `word_file.state`: `up_to_date` (nothing to do) ·
`updating` (`job_id`: started now, or a running update already covers it) · `out_of_date` (it could not
start: `blocked_by` says what holds the version — `kind` `generation` \| `update` \| `rebuild` \| `export` \|
`resume` \| `other`, `job_id`, `components`, `message`; the file stays out of date until that run ends).
A refusal never fails the submit.

### A6 — approve

**Request body** `{"comment": "Corrections read well."}` — optional, ≤ 2,000 characters.
**200** `{"document": Document}`. Keeps a copy of the Word file and its SHA-256; records the content
fingerprint (for carrying the approval forward, §4). Event `approved`; notification to the reviewer.
**409** `WRONG_STATE` (not Ready for approval / In review) · **409** `STALE_EXPORT` — its Word file is out of
date (A15: a correction it prints saved after the file was written, a layer added since, a picture being
drawn); `message`, and `why`, `corrections`, `pictures`, `layer` as in R9's `outOfDate`; update it first ·
**409** `WORD_FILE_UPDATING` — an update of its component is running (`job_id`); approve once it ends.

### A7 — request changes

**Request body** `{"comment": "The input names of libAdd are vague."}` — required, 1–2,000 characters.
**200** `{"document": Document}`. Event `changes_requested`; notification to the reviewer.
**409** `WRONG_STATE` (not Ready for approval) · **422** empty.

### A8 — reopen

**Request body** `{"reason": "The pump table changed after the review."}` — required, 1–2,000 characters.
**200** `{"document": Document}`; the reviewer stays. Event `reopened` (`comment` = the reason);
notification to the reviewer. **409** `WRONG_STATE` (not Approved) · **422** empty.

### A9 — approve several

**Request body** `{"document_ids": ["d1", "d2", "d3"], "comment": null}` — `document_ids` required (1–500).
**200** `{"approved": ["d1"], "skipped": [{"document_id": "d2", "code": "WRONG_STATE", "message": "…"}]}`.
Only Ready-for-approval documents are approved here (never In review); each as A6, one event each. A
skipped one carries A6's refusal: `code` `STALE_EXPORT` with `why`, `corrections`, `pictures`, `layer`, or
`WORD_FILE_UPDATING` with `job_id`. The old body `{"version_id"}` is refused (**422**).

### A10 / A11 — the record

`GET D/{doc}/events` → `{"events": [Event, …]}`, newest first.
`GET /projects/{project_id}/review-events?version_id=&document_id=&limit=50` → `{"events": [Event + "document":
{"id", "name", "process"}]}`, newest first; `limit` 1–200.

### A12 / A13 — documents and counts

`GET D` takes `status` (one of §1), `assignee_id` (a user id, or `none` for documents without a reviewer),
`version_id`, `process`, `q`, `page`, `per_page`. `GET D/stats?version_id=` →
`{"stats": {"total", "in_review", "submitted", "changes_requested", "approved", "needs_reviewer", "carried"}}`.

### A14 — versions

Each version gains `"review": {"documents", "approved", "in_review", "submitted", "changes_requested",
"carried", "carried_from": [{"version_id", "tag"}], "approved_by": User ref | null, "approved_at": iso |
null}`; `status` is derived (§1); `carried_from` names the versions carried approvals came from;
`approved_by` / `approved_at` are the last approval, set only when the version is approved.
`PATCH V` with `status` → **400** (a version's status follows its documents); `description` still works.

### A15 — export readiness for one document

`GET V/export-readiness?document_id={doc}` — the R9 answer (same body as without it) for that one document:
`outOfDate` holds it when its Word file is out of date (or is `[]`), `approvedKept` likewise, `stale` says
which, `writer` and `reexport` as for the version. The rule is the Word file's own
([WORD_FILE_UPDATES §4.3](../design/WORD_FILE_UPDATES.md#43-the-rule--when-a-word-file-is-out-of-date)) and
the same Approve uses. Without `document_id`: the whole version (REVIEW_UPDATE_API_SPEC §14).

### A16 — notifications

`GET /notifications?all=true&limit=30` — read ones included (newest first); without `all`, unread only, as
before. Each: `{"id", "type", "message", "project_id", "document_id", "read_at", "created_at"}`. `type` is
`review_assigned`, `review_unassigned`, `review_claimed`, `review_submitted`, `review_approved`,
`review_changes_requested`, `review_reopened`, `review_back_in_review`, and for Word file updates
`word_files_updated` (to the update's starter: "Word files updated: Brake Controller in v1.2.0.") and
`word_files_update_failed` (to the starter, and to the admins when Submit started it: "Update failed:
Brake Controller in v1.2.0 — <why>."). [WORD_FILE_UPDATES §4.7](../design/WORD_FILE_UPDATES.md#47-notifications--a16).
`PATCH /notifications/{id}/read` — **404** unless it is the caller's.

### A17 — record a version's documents

`POST V/documents/register` → **200** `{"registered": [Document, …], "carried": 2}` — a document for each
Word file of the version (`output/<component>/…docx`, SWE.3 and SWE.4) that has none, with its review
opened as after a run (§4). Idempotent: `registered` is `[]` when every file has its document. For a
version generated from the command line before it recorded its documents, or before review and approval
existed. Regenerates nothing. The CLI does the same: `python analyzer.py register --project-id P
--version-id V`.

### A18 — my reviews

`GET /reviews/mine?include_approved=false&limit=200` → `{"documents": [Document + "project": {"id",
"name"} + "version": {"id", "tag"}], "total"}` — every document the caller is the reviewer of, in every
project they are an active member of (a superuser: all), newest version first; approved ones only with
`include_approved=true`.

### A19 — members

Each member of `GET /projects/{project_id}/members` gains `"open_reviews"`: the documents of the project's
latest version they review that are not approved. Removing a member (`DELETE …/members/{user_id}`) also
takes them off every document of theirs that is not approved — event `unassigned` (payload
`left_project: true`), the admins told — so no document waits on someone who can no longer act on it.

### A20 — adding a member

The Team page finds the person with `GET /users/search?q=` (a substring of the name or the email; the
caller is never in the answer) or takes a typed address.

**Request body** `{"email": "priya.sharma@company.com", "role": "developer", "name": "Priya Sharma"}`
(`name` optional: used only when an account is created; default from the address).
**201** `{"invite": {"id", "email", "role", "status": "active"}, "member": Member, "account": {"created":
true, "temporary_password": "k7Qm…"}}` — the person is an **active** member at once: they can be assigned and
review straight away. An address with no account gets one; its temporary password is in this answer and
nowhere else (the Team page shows it once). An existing account: `created: false`,
`temporary_password: null`. A membership left `pending` by an older invite becomes the active one. The
person is notified (`member_added`). **409** `ALREADY_MEMBER` · **422** `INVALID_EMAIL`, or a role outside
`admin|developer|reviewer`. Addresses are stored in lower case; sign-in accepts any case.

For development and demos: `python tools/create_users.py [--project-id P]` (by default `admin@aspice.dev` as
the admin and `dev1`…`dev5@aspice.dev`, password `demo1234`), `--file team.csv`, or one `--email`; one person from the command line:
`python analyzer.py user add --email … [--project-id P]` (also `user password`, `user list`).

### A21 — change password

**Request body** `{"current_password": "k7Qm…", "new_password": "at-least-8-chars"}` → **200**.
**403** `WRONG_PASSWORD` · **422** `WEAK_PASSWORD` (under 8 characters).

### Corrections on an approved document

The review & update writes — `PUT V/overrides/slot`, `PUT V/overrides/behaviour`, `PUT V/flowcharts/labels`,
`DELETE V/overrides/slot` — answer **409** `DOCUMENT_APPROVED` when a document of this version that prints
the text is approved: the SWE.3 or SWE.4 document of the text's component (a struct description, whose key
names no component: any approved document of the version). Reopen it first.

### Retired

| Route | Now |
|---|---|
| `PATCH D/{doc}` with `status` | **400** — states move only through A5–A9. `due_date` (`YYYY-MM-DD` or `null`) is stored — it was accepted and dropped before |
| `PATCH D/{doc}/sections/{key}` | removed (**405**) — review is per document, not per placeholder section |
| `POST D/approve-all` with `{"version_id"}` | **422** — list the documents (A9) |
| `PATCH V` with `status` | **400** — derived (A14) |

## 4. Behind the routes

- **A run records its documents and opens their review** — every way a version is made: the web app's
  job (`POST /projects/{project_id}/jobs`), `analyzer.py generate` (at its end, inside a web job too, so a
  run whose server restarted under it still has its documents; `--no-register` skips it), a re-export,
  `analyzer.py register` and A17. Recording is idempotent (`api/services/document_registry.py`). Which
  component an output dir is: the project's layers, else the version's resolved config, its `config.json`
  beside the output, the project's `config.json`; a dir none of them names is skipped, unless none names
  any component, when the dirs themselves are taken.
- **Opening a review**: each new document is compared with the same document (process + component) of the
  baseline version — the run's baseline, else the project's previous version. Baseline approved and the
  rendered content the same → **approved**, `carried_from` set, event `carried`. The comparison is of the
  rendered content's fingerprint: the one stored at approval, and when that differs (or there is none —
  an approval made before fingerprints), the baseline fingerprinted again with the code of the day, so a
  change to how pages are built cannot stop an unchanged document from carrying its approval. Otherwise
  **in review**, keeping the baseline's reviewer if still an active member (event `generated`, payload
  `kept_reviewer_from`), and that reviewer is notified once per run (`review_back_in_review`).
- **The approved Word file** is copied when approved (`…/versions/<ver>/approved/<doc id>/<file name>`); downloads
  of an approved document (`GET D/{doc}/download`, the export-all zip) serve that copy, so a later
  update cannot change what was approved. When the copy is missing the working file is served only if its
  SHA-256 is `docx_sha256`; otherwise **409** `APPROVED_FILE_MISSING` (the zip: `document_ids`). Reopening
  drops the copy from use (the file stays).
- **Corrections while an update runs**: R3, R4, R6 and R8 answer **409** `WORD_FILE_UPDATING` (`job_id`,
  `components`) for a text whose component an update is writing now; every other component stays editable.
- **Version and project status** are written on every approval and reopen too — the version
  `approved` / `in_review`, and the project `complete` / `in_review` when it is the project's latest version.
