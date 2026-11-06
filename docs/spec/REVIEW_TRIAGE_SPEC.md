# Review triage — verdicts and scores

How a review of a generated SWE.3 document is triaged, and how its per-section scores are recomputed.
The reviewers score each section and count every comment against it; many comments ask for something
the document does on purpose. A verdict on every comment separates the two, and the summary shows what
the score is when only the real problems count.

The rules the document follows: [SWE3_WIKI.md](SWE3_WIKI.md). Open work: [BACKLOG](../BACKLOG.md) S3-12.

Inputs: the review sheet (every comment, its section, each section's score in %), the issue list (the
known issues, each with its ID) and the generated documents (what the document shows where a comment
points).

---

## The review file

One row per comment.

| No. | Section | Comment | Verdict | Reference |
|---|---|---|---|---|
| 12 | UI | Private functions missing | As per rule | SWE3-UI-01 |
| 13 | FD | Inline function, no flowchart | Defect | R-04 |
| 14 | UH | Macro off, function missing | Gap | R-07 |
| 15 | UI | Description is vague | Defect | R-09 |
| 16 | UI | Same as 12 | As per rule | SWE3-UI-01 |

| Column | Values |
|---|---|
| No. | the comment's number in the review sheet |
| Section | where the reviewers made it: SD, UH, UI, FD or DB (below) |
| Comment | the reviewer's text |
| Verdict | one of the four [verdicts](#verdict) |
| Reference | one ID, by the verdict: see [Reference](#reference) |

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

## Verdict

| Verdict | Means | What happens |
|---|---|---|
| **Defect** | the document is wrong, its LLM wording included | the tool is fixed, or the text is corrected in the app |
| **Gap** | no rule covers the case | a rule is written, then the tool follows it |
| **Change** | the document is as designed, but the reviewers want another design | the rule is agreed again, then the tool changes |
| **As per rule** | the document is right; the reader expected something else | the answer names the rule |

- A misread or a question the rules answer is **As per rule**; a question they do not answer is a **Gap**.
- A duplicate takes the verdict and reference of the comment it repeats.

---

## Reference

**The reference decides the count: an issue ID counts against the document, a rule ID does not.**

| Verdict | Reference | Counted against |
|---|---|---|
| Defect | the issue's ID in the issue list | yes |
| Gap | the issue's ID in the issue list | yes |
| Change | the rule ID they want changed, `SWE3-<code>-NN` | no |
| As per rule | the rule ID that answers the comment | no |

- The issue list holds only what counts against the document: Defects and Gaps.
- One ID per comment. A comment touching several rules takes the one that decides it.
- Similar comments share one issue, so they share its ID. A problem not in the list is added to it
  first, with the next free ID; a Defect's entry names the rule it breaks.
- The prefix tells the two apart: `SWE3-…` is a rule, anything else an issue.

---

## Summary

One row per section:

| Section | Review % | Comments | Defect | Gap | Change | As per rule | Adjusted % | Defects only % |
|---|---|---|---|---|---|---|---|---|

Each comment took the same share of the section's lost score, so the comments that are not counted
against are given back:

```
share          = (100 − review %) ÷ comments
adjusted %     = review % + share × (change + as per rule)
defects only % = review % + share × (comments − defect)
```

*Example:* Unit header, review 62%, 30 comments: 4 defect, 2 gap, 6 change, 18 as per rule.
share = 38 ÷ 30 = 1.27. Adjusted = 62 + 1.27 × 24 = **92.4%**. Defects only = 62 + 1.27 × 26 = **94.9%**.

**Adjusted %** is the number to stand behind: what a reader really ran into. **Defects only %** is what
the tool alone is answerable for. If the reviewers weighted their comments (major, minor, points), use
each comment's weight instead of an equal share.

Under the table, one line: comments → issues, and how many of the issues are new in this review.

A second table, by reference, most comments first — `Reference | Comments | Verdict` — is the agenda
for the next talk with the reviewers: its Change rows are the rules they want changed.
