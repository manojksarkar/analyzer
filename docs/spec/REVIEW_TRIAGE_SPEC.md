# Review triage — verdicts and scores

How a review of the generated SWE.3 documents is triaged, and how its per-section scores are recomputed.
The reviewers score each section and count every comment against it; many comments ask for something
the document does on purpose. A verdict on every comment separates the two, and the output shows the
score when only the real problems count.

The rules the document follows: [SWE3_WIKI.md](SWE3_WIKI.md). Open work: [BACKLOG](../BACKLOG.md) S3-12.

A review is named by its document and the version it read: `SWE3_V4`. A SWE.4 review (`SWE4_V5`) works
the same way, with `SWE4-` IDs.

The inputs:
- **[The issue list](#the-issue-list)** — ours, one list kept from review to review.
- **[The review input file](#the-review-input-file)** — one per review: the reviewers' sheet, with an
  Issue ID on each comment.
- **SWE3_WIKI** — as it was for the documents the review read.
- **The newest generated documents** — where each comment is checked: fixed or not.

The output: [five tables](#output). A [full example](#example) is at the end.

---

## IDs

| ID | Names | Form | Example |
|---|---|---|---|
| Review ID | one comment, in the reviewers' sheet | `V<version>_R<row>_<subrow>_P<part>` | `V4_R1_05_P1` |
| Issue ID | one issue, in the issue list | `SWE3-V<version>-NN` | `SWE3-V4-11` |
| Rule ID | one rule, in SWE3_WIKI | `SWE3-<section>-NN` | `SWE3-FD-02` |

- A review row with several points has one part per point (`P1`, `P2`); each part is one comment.
- An Issue ID carries the version of the review that first raised it; `NN` counts up within that
  review. It is never reused or renumbered.
- A Review ID does not name the document type; the review does (`SWE3_V4`).

---

## Verdict

| Verdict | Means | What happens |
|---|---|---|
| **Defect** | the document is wrong, its LLM wording included | the tool is fixed, or the text is corrected in the app |
| **Gap** | no rule covers the case | a rule is written, then the tool follows it |
| **As per rule** | the document is right; the reader expected something else | the answer names the rule |

- A Defect breaks a rule, so it always has a Rule ID. A case no rule decides is a Gap.
- A misread or a question the rules answer is **As per rule**; a question they do not answer is a **Gap**.
- A request for another design, where the document follows its rule, is **As per rule** too: the rule is
  talked about again with the reviewers (the agenda, under [Output](#output)).
- A verdict is never changed afterwards: it was right under the rules of its review.

---

## The issue list

Every issue any review raised, one row each, As per rule included. One sheet, `Issues`. The list:
[issue_list.xlsx](../review/issue_list.xlsx).

| Issue ID | Rule ID | Issue | Verdict |
|---|---|---|---|
| SWE3-V4-08 | SWE3-UH-01 | Structs and classes are missing from the unit header | Defect |
| SWE3-V5-01 | | A function defined by a macro has no entry | Gap |
| SWE3-V4-22 | SWE3-FD-01 | Private functions appear missing | As per rule |

| Verdict | Rule ID |
|---|---|
| Defect | the rule it breaks |
| Gap | empty, until its rule is written |
| As per rule | the rule that answers it |

- No status: whether an issue is fixed is the tool's [output](#output).
- The list only grows; no row is deleted.
- Similar comments share one issue. A problem not on the list is added first, with the next ID of this
  review.
- Same problem, same verdict: the same ID, even when an earlier review raised it. Same problem, a new
  verdict (a rule changed): a new ID.

---

## The review input file

One per review, built from the reviewers' sheet. Two sheets.

`Comments`, one row per comment:

| Review ID | Document | Section | Comment | Issue ID |
|---|---|---|---|---|
| V5_R1_01_P1 | Flash Core | UH | Struct `Page` is not in the table | SWE3-V4-08 |

`Scores`, one row per document and section:

| Document | Section | Review % |
|---|---|---|
| Flash Core | UH | 60 |

| Column | Values |
|---|---|
| Review ID | the reviewers' ID for the comment ([IDs](#ids)) |
| Document | the component whose document the comment is on |
| Section | where the reviewers made it: SD, UH, UI, FD or DB (below) |
| Comment | the reviewer's text |
| Issue ID | the issue the comment belongs to: one per comment |
| Review % | the reviewers' score for the section |

- No verdict column: the verdict comes from the issue list.
- A comment touching several rules takes the issue of the rule that decides it.
- A duplicate takes the Issue ID of the comment it repeats.

The five sections the reviewers score are SWE3_WIKI's rule tables of the same names:

| Section | Covers, in the document |
|---|---|
| SD | Static diagram: the component's container and file dependency diagrams, the Component/Unit table, each unit's architecture diagram |
| UH | Unit header: the unit header table |
| UI | Unit interface: the unit interface table |
| FD | Flow diagram: each public function's entry, its table and flowchart(s) |
| DB | Dynamic behaviour: each entry's table and sequence diagram |

A comment counts in the section where it was made, even when the rule it is about is a general one
(DOC or FX in SWE3_WIKI).

---

## Output

Five tables per review. Each repeats the texts it refers to, so it reads without the inputs beside it.

**Comments**: `Review ID | Document | Section | Comment | Issue ID | Issue | Verdict | Status`
- Review ID to Issue ID: from the review input file; Issue and Verdict: from the issue list.
- Status: **Fixed** when the newest documents no longer show what the comment points at, else **Open**;
  `—` for As per rule.

**Issues**: `Issue ID | Rule ID | Issue | Verdict | Comments | Fixed | Open | Status | Open comments`,
every issue the review raised.
- Status: **Fixed** when all its comments are Fixed, **Partly fixed** when some are, **Open** when none
  is; `—` for As per rule.
- Open comments: the Review IDs of the comments still open.
- A Partly fixed issue's open comments are looked at again. The fix missed a case: they keep the ID.
  It is another problem: it becomes a new issue, with the next ID of the review the comments came from,
  and they move to it. The verdict stays the same, so the review's Our % does not change.

  *Example:* `SWE3-V4-11`, a Return box with no arrow to End, has 8 comments, 5 fixed. The 3 open ones
  are all a `return` inside a `switch`: they move to a new issue.

  | Issue ID | Issue | Comments | Fixed | Open | Status |
  |---|---|---|---|---|---|
  | SWE3-V4-11 | Flowchart: a Return box has no arrow to End | 5 | 5 | 0 | Fixed |
  | SWE3-V5-04 | Flowchart: a `return` inside a `switch` has no arrow to End | 3 | 0 | 3 | Open |

**Totals**: `Verdict | Issues | Comments | Fixed | Open`, one row per verdict and a Total row; under
it, one line: how many issues are Fixed, Partly fixed and Open.

**Scores**: `Document | Section | Review % | Comments | Defect | Gap | As per rule | Our %`

```
share = (100 − review %) ÷ comments
our % = review % + share × as per rule
```

Each comment took the same share of the section's lost score; the As per rule ones get theirs back. If
the reviewers weighted their comments (major, minor, points), use each comment's weight instead of an
equal share. Under the table, one line: comments → issues, and how many issues are new in this review.
Scores are per section only: the reviewers give no total per document.

**Agenda**: `Rule ID | Rule | As per rule comments`, most first; Rule is the rule's name in SWE3_WIKI.
For the next talk with the reviewers: a rule that collects many As per rule comments is one they may
want changed.

---

## When a rule changes

A rule changes only when the teams agree it: it is in SWE3_WIKI's
[Planned changes](SWE3_WIKI.md#planned-changes) until the tool is built, then in the rule itself, with a
line in [Changes](SWE3_WIKI.md#changes). Rule IDs never change.

| Change | The issue list | The next review |
|---|---|---|
| A Gap gets a rule | same row, still Gap; its Rule ID is filled in | the document follows the rule: no comment, and the Gap shows Fixed; it breaks the rule: a Defect, with a new ID |
| An As per rule item's rule changes | same row, unchanged | until it is built: still As per rule, the same ID; once built, the document breaks the new rule: a Defect, with a new ID |

Each review is judged by SWE3_WIKI as it was for the documents it read, and no verdict changes
afterwards, so a review's Our % never changes.

---

## Example

Review `SWE3_V5` of the document Flash Core: two sections, ten comments. Four issues come from review
`SWE3_V4`; three are new.

**The issue list**, the rows this review uses:

| Issue ID | Rule ID | Issue | Verdict |
|---|---|---|---|
| SWE3-V4-08 | SWE3-UH-01 | Structs and classes are missing from the unit header | Defect |
| SWE3-V4-11 | SWE3-FD-02 | Flowchart: a Return box has no arrow to End | Defect |
| SWE3-V4-21 | SWE3-UH-01 | A global is in both the unit header and the interface table | As per rule |
| SWE3-V4-22 | SWE3-FD-01 | Private functions appear missing | As per rule |
| SWE3-V5-01 | | A function defined by a macro has no entry | Gap |
| SWE3-V5-02 | SWE3-UH-04 | A shared header's enum is listed in one unit only | As per rule |
| SWE3-V5-03 | SWE3-FD-03 | Input Name shows only the first parameter | As per rule |

**The review input file**, `Comments`:

| Review ID | Document | Section | Comment | Issue ID |
|---|---|---|---|---|
| V5_R1_01_P1 | Flash Core | UH | Struct `Page` is not in the table | SWE3-V4-08 |
| V5_R1_01_P2 | Flash Core | UH | Class `BlockMap` is not in the table | SWE3-V4-08 |
| V5_R1_02_P1 | Flash Core | UH | Global `g_count` is also in the interface table | SWE3-V4-21 |
| V5_R1_03_P1 | Flash Core | UH | Enum `Mode` is listed in one unit only | SWE3-V5-02 |
| V5_R1_04_P1 | Flash Core | UH | Same as V5_R1_03_P1 | SWE3-V5-02 |
| V5_R2_01_P1 | Flash Core | FD | `Read()`: Return has no arrow to End | SWE3-V4-11 |
| V5_R2_02_P1 | Flash Core | FD | `DEFINE_HANDLER(Erase)`: no entry for `Erase()` | SWE3-V5-01 |
| V5_R2_03_P1 | Flash Core | FD | Private function `Check()` is missing | SWE3-V4-22 |
| V5_R2_03_P2 | Flash Core | FD | `Write()`: Input Name shows only the first parameter | SWE3-V5-03 |
| V5_R2_04_P1 | Flash Core | FD | `Write()`: Return has no arrow to End | SWE3-V4-11 |

`Scores`:

| Document | Section | Review % |
|---|---|---|
| Flash Core | UH | 60 |
| Flash Core | FD | 70 |

**The output.** Comments:

| Review ID | Document | Section | Comment | Issue ID | Issue | Verdict | Status |
|---|---|---|---|---|---|---|---|
| V5_R1_01_P1 | Flash Core | UH | Struct `Page` is not in the table | SWE3-V4-08 | Structs and classes are missing from the unit header | Defect | Fixed |
| V5_R1_01_P2 | Flash Core | UH | Class `BlockMap` is not in the table | SWE3-V4-08 | Structs and classes are missing from the unit header | Defect | Fixed |
| V5_R1_02_P1 | Flash Core | UH | Global `g_count` is also in the interface table | SWE3-V4-21 | A global is in both the unit header and the interface table | As per rule | — |
| V5_R1_03_P1 | Flash Core | UH | Enum `Mode` is listed in one unit only | SWE3-V5-02 | A shared header's enum is listed in one unit only | As per rule | — |
| V5_R1_04_P1 | Flash Core | UH | Same as V5_R1_03_P1 | SWE3-V5-02 | A shared header's enum is listed in one unit only | As per rule | — |
| V5_R2_01_P1 | Flash Core | FD | `Read()`: Return has no arrow to End | SWE3-V4-11 | Flowchart: a Return box has no arrow to End | Defect | Fixed |
| V5_R2_02_P1 | Flash Core | FD | `DEFINE_HANDLER(Erase)`: no entry for `Erase()` | SWE3-V5-01 | A function defined by a macro has no entry | Gap | Open |
| V5_R2_03_P1 | Flash Core | FD | Private function `Check()` is missing | SWE3-V4-22 | Private functions appear missing | As per rule | — |
| V5_R2_03_P2 | Flash Core | FD | `Write()`: Input Name shows only the first parameter | SWE3-V5-03 | Input Name shows only the first parameter | As per rule | — |
| V5_R2_04_P1 | Flash Core | FD | `Write()`: Return has no arrow to End | SWE3-V4-11 | Flowchart: a Return box has no arrow to End | Defect | Open |

Issues:

| Issue ID | Rule ID | Issue | Verdict | Comments | Fixed | Open | Status | Open comments |
|---|---|---|---|---|---|---|---|---|
| SWE3-V4-08 | SWE3-UH-01 | Structs and classes are missing from the unit header | Defect | 2 | 2 | 0 | Fixed | |
| SWE3-V4-11 | SWE3-FD-02 | Flowchart: a Return box has no arrow to End | Defect | 2 | 1 | 1 | Partly fixed | V5_R2_04_P1 |
| SWE3-V5-01 | | A function defined by a macro has no entry | Gap | 1 | 0 | 1 | Open | V5_R2_02_P1 |
| SWE3-V5-02 | SWE3-UH-04 | A shared header's enum is listed in one unit only | As per rule | 2 | — | — | — | |
| SWE3-V4-21 | SWE3-UH-01 | A global is in both the unit header and the interface table | As per rule | 1 | — | — | — | |
| SWE3-V4-22 | SWE3-FD-01 | Private functions appear missing | As per rule | 1 | — | — | — | |
| SWE3-V5-03 | SWE3-FD-03 | Input Name shows only the first parameter | As per rule | 1 | — | — | — | |

Totals:

| Verdict | Issues | Comments | Fixed | Open |
|---|---|---|---|---|
| Defect | 2 | 4 | 3 | 1 |
| Gap | 1 | 1 | 0 | 1 |
| As per rule | 4 | 5 | — | — |
| **Total** | **7** | **10** | **3** | **2** |

Issues: 1 Fixed, 1 Partly fixed, 1 Open.

Scores:

| Document | Section | Review % | Comments | Defect | Gap | As per rule | Our % |
|---|---|---|---|---|---|---|---|
| Flash Core | UH | 60 | 5 | 2 | 0 | 3 | 84 |
| Flash Core | FD | 70 | 5 | 2 | 1 | 2 | 82 |

```
UH:  share = (100 − 60) ÷ 5 = 8    our % = 60 + 8 × 3 = 84
FD:  share = (100 − 70) ÷ 5 = 6    our % = 70 + 6 × 2 = 82
```

10 comments → 7 issues, 3 of them new in this review.

Agenda:

| Rule ID | Rule | As per rule comments |
|---|---|---|
| SWE3-UH-04 | Shared headers | 2 |
| SWE3-UH-01 | What is listed | 1 |
| SWE3-FD-01 | The entry | 1 |
| SWE3-FD-03 | Input Name and Output Name | 1 |

`SWE3-V4-11` came back from review `SWE3_V4`: one of its two flowcharts is fixed, so the issue is Partly
fixed, and its open comment, `V5_R2_04_P1`, is looked at again.
