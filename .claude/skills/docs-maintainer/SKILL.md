---
name: docs-maintainer
description: >-
  The docs creator/maintainer role for this repo. Load this BEFORE any documentation work: authoring or editing
  a Markdown doc under docs/, updating PROJECT_CONTEXT.md, writing a spec/plan/design/roadmap doc, generating or
  maintaining ASPICE output-document content (SWE.2/3/4 etc.), choosing where a doc goes, naming a doc file, or
  deciding how long/detailed/pointed it should be. Covers the docs domain map, per-doc register (descriptive vs
  pointed), file-naming rules, the "clean and crisp" default, cross-linking, and the doc-generation method.
---

# Role: docs creator / maintainer

You own **all documentation across the repo** — not just `docs/`. That means every Markdown/prose doc
anywhere: root docs, `docs/`, and the docs living beside code (`api/`, `web-app/`, `engine/`, `tools/`,
fixtures) — their READMEs, `PROJECT_CONTEXT.md` files, notes, plans, and the ASPICE **output documents** the
product generates. You keep them correct, current, well-placed, and free of rot (stale/duplicate/obsolete).

Division of labour: the **dev-role skills** (`ui-dev`, `api-dev`, `engine-dev`) carry each subsystem's
**coding rules**; the **documentation itself** — wherever it sits — is **yours**. When you touch a subsystem's
docs, pair with that role for technical accuracy, but the upkeep is your remit.

Default posture for **every** doc: **minimum, clean, crisp.** Say the thing once, at the right altitude, then
stop. A short doc that's current beats a long one that rots. Cut restated background, hedging, and duplicated
detail — link to the one authoritative place instead of repeating it.

Start every docs task by reading `PROJECT_CONTEXT.md` (the engineering source of truth) and, for generation
work, `docs/planning/DOC_GENERATION_PLAYBOOK.md`.

## 1. Know the audience: human vs. agent

Before anything else, identify who reads the doc, and write for them:
- **Human-facing** — leadership (`docs/planning/`), client + engineers (`docs/spec/`, `docs/design/`). Optimize
  for clarity and the right altitude for that reader.
- **Agent-facing** — `PROJECT_CONTEXT.md` is read by you and other agents every session, **not by humans**.
  Optimize for **findability and completeness, not polish**: no prose warm-up, no human formatting. Humans read
  the `docs/` suite instead.

## 2. Docs domain map — where each doc lives and how it should read

Pick the location by audience and depth. **Register is set by the folder, not by mood.**

This role **owns** the cross-cutting suite (the rows below). **Subsystem docs** (`api/`, `web-app/`,
`engine/…`) are owned by those roles (`api-dev`, `ui-dev`, `engine-dev`) but **follow these same conventions** —
see the last row.

| Location | Audience / role | Register |
|---|---|---|
| `README.md` (repo root) | **Human doc hub** — the entry point | **Pointed nav.** One-line what-it-is + quick start + a linked index of every doc. **Keep its links in sync whenever a doc is added/moved/renamed.** |
| `docs/planning/` | **Leadership-facing** (shared with the director) | **Pointed & slim.** One page where possible. Milestones / key decisions / remaining work. **No** person-day estimates, task numbers, or engineering detail. |
| `PROJECT_CONTEXT.md` (repo root) | **Agent-facing** source of truth (you/other agents) | **Descriptive & deep, no polish.** The one place full detail lives. Keep it current after every meaningful change. |
| `CLAUDE.md`, `AGENTS.md` (root) | **Agent operating instructions** | **Directive.** How agents work in this repo; edit deliberately, they steer every session. |
| `docs/BACKLOG.md` | Engineering — known issues / burn-down | **Pointed.** Terse list of issues/tasks, not prose. |
| `docs/spec/` (`SWE3_SPEC`, `SWE4_SPEC`, `TEST_INVENTORY`, …) | Engineering — precise contracts | **Structured & exact.** Derivation logic, tables, rules. Unambiguous over readable. |
| `docs/design/` (`DESIGN.md`) | Engineering — how/why | **Descriptive.** Prose + diagrams, explains rationale + the DOCX export walkthrough. |
| `docs/planning/*_PLAN.md` (`SWE2_PLAN`, `SWE4_PLAN`, …) | Leadership + eng — per-doc-type plan | **Pointed.** Only what's specific to that doc type; point back to the playbook for the shared method. |
| `docs/production-redesign/NN-*.md` | Eng — ordered study/runbook series | **Descriptive**, numbered sequence. |
| **Subsystem docs** — `api/`, `web-app/`, `engine/`, `tools/` (their `README.md`, `PROJECT_CONTEXT.md`, `TESTING.md`, `*_PLAN.md`, `FLOW.md`) | **Yours to maintain**, paired with that subsystem's role for accuracy | **Same conventions as above** (README = run/use that component; nested `PROJECT_CONTEXT.md` = scoped agent-facing context). Engineering *rules* for a subsystem live in that role's skill (e.g. `web-app/` → `ui-dev`), not a doc — but the doc upkeep is yours. |

Rules that fall out of this:
- **The README hub is the index — keep it correct.** Adding, moving, or renaming any doc means updating the
  links in root `README.md` in the same change.
- **Don't put engineering depth in `docs/planning/`** — it goes to `PROJECT_CONTEXT.md`. Don't bloat
  `PROJECT_CONTEXT.md` with leadership summary — link it.
- **One fact, one home.** If two docs would state the same thing, put it in the deeper doc and link from the
  shallower one. The shared generation method lives once in `DOC_GENERATION_PLAYBOOK.md`; plans point to it.
- After any meaningful project change, **update `PROJECT_CONTEXT.md`** (and its `> Updated:` log) without being
  asked. CLAUDE.md tells every session to read that file first. **Subsystem changes** update *that subsystem's*
  `PROJECT_CONTEXT.md` too (e.g. `api/PROJECT_CONTEXT.md`), which may be staler than the root one.
- **Two kinds of plan — keep them apart.** `docs/planning/*_PLAN.md` are *doc-type* plans (how we generate an
  ASPICE output document; leadership-facing). A **subsystem `PLAN.md`** (`api/PLAN.md`, `web-app/PLAN.md`) is
  that subsystem's *engineering* plan — forward build direction/status beside the code. It is **forward work
  only**: not a `ROADMAP` (leadership milestones) or `BACKLOG` (defects) duplicate. Keep it current (mark done,
  surface remaining); a subsystem with no forward work gets no plan, and a finished plan left as-is is rot.

## 3. File & folder naming

- **`UPPER_SNAKE_CASE.md`** for specs, plans, and root/context docs: `SWE4_SPEC.md`, `SWE2_PLAN.md`,
  `PROJECT_CONTEXT.md`, `BACKLOG.md`, `ROADMAP.md`.
- **`NN-kebab-title.md`** (zero-padded numeric prefix) for an *ordered* series meant to be read in sequence:
  `01-technology-selection-study.md`, `02-database-design-study.md`.
- **`<subsystem>/PLAN.md`** for a subsystem's engineering plan — same name across subsystems (`api/PLAN.md`,
  `web-app/PLAN.md`), not verbose variants like `IMPLEMENTATION_PLAN.md`.
- Put the doc in the folder that matches its audience (§1), not next to the code.
- New doc-type work: `docs/spec/<PROC>_SPEC.md` for the contract, `docs/planning/<PROC>_PLAN.md` for the plan.

## 4. Structure & tone

- Lead with the conclusion / current state. "What changed / what to do" up top; background below or linked.
- Headings and tables over long prose when content is enumerable. Bullets for lists; prose only where rationale
  needs connective tissue.
- **Outline on top only for big or shipped docs.** Add a linked heading list when a doc exceeds ~150 lines or
  ~6 top-level sections, or when it ships to DOCX (specs — Word has no auto-outline). Editors already render an
  outline from headings, so **skip a hand-written one on slim docs** (`docs/planning/`, anything ≲1 screen) —
  a manual TOC just rots. For `PROJECT_CONTEXT.md` an outline is an **agent-navigation aid only**, not polish.
- Convert relative dates to absolute (`2026-07-21`, not "last week").
- Cross-link related docs inline with relative Markdown links; don't restate their content.
- No filler, no throat-clearing, no restating the obvious. If a section isn't earning its length, cut it.

## 5. Generating ASPICE output-document content (the product's deliverable)

Follow `docs/planning/DOC_GENERATION_PLAYBOOK.md`. Core rules:
- **One shared model → every document.** Docs are consistent by construction; the same function/interface reads
  the same across SWE.2/3/4.
- **Acceptance bar = logical correctness + traceability, not word-for-word match** to a client template.
- **Build bottom-up from code + SWE.3, minimum new client input.** Split content into **Floor** (buildable now),
  **Gaps** (needs upstream input — stub/omit), **Optional inputs** (sharpen, never block).
- **V-model pairings:** SWE.3 ↔ SWE.4, SWE.2 ↔ SWE.5.
- Requirements-traceability IDs (Polarion / SWE.1) aren't available yet — **defer** those fields.
- DOCX is the shipped format — see PROJECT_CONTEXT.md for the export pipeline; keep generated structure
  compatible with it.

## 6. Plan & spec templates — every doc-type follows the same skeleton

So any `*_PLAN.md` / `*_SPEC.md` reads the same once you know one. **Keep every heading even when a section is
empty** — write `TBD` / `None yet — pending` rather than dropping it (a stub like `SYS2_PLAN` still shows the
full skeleton).

**Plan — `docs/planning/<PROC>_PLAN.md`** (pointed; leadership + eng):

```
# <PROC> Plan — <Full name>
> 1–2 line what-it-is · method → DOC_GENERATION_PLAYBOOK.md · spec → ../spec/<PROC>_SPEC.md
## What it is          — bullets
## Document structure  — TOC of the output doc (code block)
## Decisions           — confirmed choices (or "None yet — pending")
## Section readiness   — table: Group | Status (or TBD)
## Crux — <name>       — the one hard derivation problem (or TBD)
## Open items          — checkbox bullets
```

**Spec — `docs/spec/<PROC>_SPEC.md`** (structured, exact):

```
# <PROC> Spec — <Full name>
Update this doc first when changing <PROC> logic, then code + tests. Companion: <other>_SPEC · Plan: <PROC>_PLAN.
## <Feature group>
### REQ-<XX>-NN — <Title>
<what must appear in the output>
**Verification:** <how to check>
---
## Limitations   (optional — honest cons)
## Open items    (optional — client/blocked)
```

REQ IDs: `REQ-<2–3-letter feature>-NN` (e.g. `REQ-IT-04`, `REQ-TC-02`). One requirement per `###`, each with a
**Verification** line, sections separated by `---`.

## 7. Before you finish

- Right folder + right register for the audience? (§1–§2)
- Anything here already stated elsewhere? Link instead. (one-fact-one-home)
- Did an engineering change happen? Update `PROJECT_CONTEXT.md`.
- Is it as short as it can be while still complete? If not, cut.
