# Review triage — verdicts and scores

How a review of a generated SWE.3 document is triaged, and how its per-section scores are recomputed.
The reviewers score each section and count every comment against it; many comments ask for something
the document does on purpose. A verdict on every comment separates the two, and the summary shows what
the score is when only the real problems count.

The rules the document follows: [SWE3_WIKI.md](SWE3_WIKI.md). Open work: [BACKLOG](../BACKLOG.md) S3-12.

| Step | When | What |
|---|---|---|
| 1 | **now** | every comment gets a section and a verdict; the summary per section |
| 2 | later, when the rules are agreed | every comment gets the rule id it is about; a summary by rule |

---

## Input

| Input | What is taken from it |
|---|---|
| the review sheet | every comment, its section, each section's score (%) |
| the known defect list | to mark an issue as already known |
| the generated documents | what the document shows where the comment points |

---

## Comments and issues

The **comments** are what is counted. An **issue** groups similar comments, so each is looked at and
fixed once. Every comment is in exactly one issue.

**A comment has one section, one verdict and at most one rule**, so nothing is counted twice. The
comments of one issue may differ in any of the three: an issue can hold comments of several rules,
and one rule can collect several issues.

**Comments**

| Column | Values | Note |
|---|---|---|
| Comment | its number in the review sheet | |
| Section | one of the five [sections](#sections) | where the reviewers made it |
| Issue | `R-01`, `R-02`, … | the issue it is grouped in |
| Verdict | one of the six [verdicts](#verdicts) | the issue's, unless this comment differs |
| Rule | **empty in step 1**; in step 2 one rule id, `SWE3-UI-05` | the issue's, unless this comment differs; a `gap` has none |

**Issues**

| Column | Values | Note |
|---|---|---|
| Issue | `R-01`, `R-02`, … | |
| Comments | the comment numbers, and their count | |
| Verdict | one of the six [verdicts](#verdicts) | set once here; it applies to every comment of the issue that has none of its own |
| Rule | **empty in step 1**; in step 2 one rule id | the same: set here, changed on a comment that differs |
| Known defect | the defect's number in the known list, or `new` | |
| Confirmed | empty, or who checked it | a verdict is a proposal until confirmed; the summary counts the comments of confirmed issues only |

---

## Sections

The five sections the reviewers score. They are SWE3_WIKI's rule tables of the same names.

| Section | Code | Covers, in the document |
|---|---|---|
| Static diagram | SD | the component's container and file dependency diagrams, the Component/Unit table, each unit's architecture diagram |
| Unit header | UH | the unit header table |
| Unit interface | UI | the unit interface table |
| Flow diagram | FD | each public function's entry: its table and flowchart(s) |
| Dynamic behaviour | DB | Dynamic Behaviour: each entry's table and sequence diagram |

A comment counts in the section where it was made, even when the rule it is about is a general one
(DOC or FX in SWE3_WIKI).

---

## Verdicts

| Verdict | Means | What happens | Counted against |
|---|---|---|---|
| **defect** | the document is wrong: it breaks a rule | the tool is fixed | yes |
| **gap** | no rule covers the case | a rule is written, then the tool follows it | yes |
| **wording** | an LLM-written text is badly worded | the text is corrected in the app; no code change | yes |
| **as per rule** | the document does this on purpose; the reader expected something else | the answer names the rule | no |
| **change request** | the output is as designed, but the reviewers want another design | the rule is agreed again, then the tool changes | no |
| **not an issue** | a duplicate, a misread, or a question | answered; nothing changes | no |

| Example comment | Verdict |
|---|---|
| "a function another unit calls has no row in the interface table" | defect |
| "a private global is listed in the unit header" | as per rule (the table lists everything the unit declares) |
| "show the macro value worked out, `64`, not `(1<<6)`" | change request |
| "the description of `FtlRead` is vague" | wording |
| a case the rules do not mention | gap |

---

## The summary

One row per section:

| Section | Review % | Comments | Defect | Gap | Wording | As per rule | Change request | Not an issue | Adjusted % | Defects only % |
|---|---|---|---|---|---|---|---|---|---|---|

Each comment took the same share of the section's lost score, so the comments that are not counted
against are given back:

```
share         = (100 − review %) ÷ comments
adjusted %    = review % + share × (as per rule + change request + not an issue)
defects only %= review % + share × (comments − defect)
```

*Example:* Unit header, review 62%, 30 comments: 4 defect, 2 gap, 0 wording, 18 as per rule, 6 change
request. share = 38 ÷ 30 = 1.27. Adjusted = 62 + 1.27 × 24 = **92.4%**. Defects only = 62 + 1.27 × 26
= **94.9%**.

**Adjusted %** is the number to stand behind: what a reader really ran into. **Defects only %** is what
the tool alone is answerable for. If the reviewers weighted their comments (major, minor, points), use
each comment's weight instead of an equal share.

Under the table, one line in total: comments → issues; how many issues hold a defect, and how many of
them were already known.

---

## Step 2 — by rule (later)

When the rules are agreed, every comment gets its rule id from [SWE3_WIKI.md](SWE3_WIKI.md):
`SWE3-<code>-NN`, for example `SWE3-UH-03`. Then:

- a second summary, by rule, most comments first: `Rule | Comments | Issues | Verdicts (count of each)
  | Next step`; this is the agenda for the next talk with the reviewers;
- every **as per rule** names the rule that says so;
- every **gap** becomes a new rule, with the next free number of its section;
- a rule marked ⚠ in SWE3_WIKI is still open: comments on it are a question for the reviewers.
