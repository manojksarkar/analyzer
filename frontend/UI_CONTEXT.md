# Frontend UI Design Context

> Last updated: 2026-06-17
> Active branch: `feat/product-ui-redesign`
> Read this file before doing any UI design work in this repo.

---

## What this product is

**[PRODUCT NAME]** (name TBD) is an ASPICE compliance automation tool for automotive Tier 1 suppliers (Bosch, Continental, etc.). It takes a C++ firmware codebase, parses it, and auto-generates ASPICE-compliant engineering documents — starting with **SWE.3 Software Detailed Design**.

The goal: point it at a repo, configure your architecture layers, and get the full ASPICE documentation trail without manual effort.

---

## What is already built (backend)

> **Important for UI design**: The current backend is a CLI pipeline — do not design the UI around it. Design for the ultimate product vision. The backend will evolve to match the UI, not the other way around.

| Capability | Detail |
|---|---|
| SWE.3 document generation | Parses C++ source, derives model, generates Software Detailed Design |
| Architecture config | `layers → groups → components` hierarchy |
| Macro input | CSV-based macro definitions |
| Data dictionary | CSV merged into model |
| Include path management | Per-layer include directory configuration |
| LLM enrichment | Function descriptions, behavior names, CFG flowcharts (Ollama / OpenAI) |

**What is NOT built yet** (showcase in UI, backend will follow): GitHub/repo integration, SYS.1, SYS.2, SWE.1, SWE.2 process pages, auth/RBAC, versioning system, web-based project management.

---

## Reference designs

6 HTML mockups are in `frontend/reference/`. Read these before designing any page.

| File | What it shows |
|---|---|
| `signin.html` | Login page — SSO + credentials + registration |
| `overview.html` | Compliance dashboard — stats, process status cards, traceability matrix |
| `config.html` | Project configuration — repo, data dictionary, Clang config, architecture mapping |
| `SWE.3.html` | SWE.3 document viewer + right inspector panel (traceability, unresolved edits) |
| `SWE.3 empty.html` | SWE.3 empty state + document generation flow with live log console |
| `SWE.3 compare.html` | SWE.3 commit comparison — side-by-side diff view |

---

## Design system

| Token | Value |
|---|---|
| CSS framework | Tailwind CSS (CDN, with `forms` + `container-queries` plugins) |
| Icons | Material Symbols Outlined (Google Fonts) |
| Body / headlines | Inter |
| Labels / code | JetBrains Mono |
| Sidebar width | 280px (`sidebar-width`) |
| Inspector width | 400px (`inspector-width`) |
| Gutter | 16px |
| Container padding | 24px |

### Color tokens

| Name | Hex |
|---|---|
| `primary` | `#041627` (deep navy) |
| `secondary` | `#0058be` (blue) |
| `secondary-container` | `#2170e4` |
| `on-tertiary-container` | `#00a572` (green — success/verified) |
| `error` | `#ba1a1a` |
| `surface` | `#f8f9ff` |
| `surface-container-low` | `#eff4ff` |
| `outline-variant` | `#c4c6cd` |

### Layout pattern (3-panel)

```
[ 280px Sidebar ] [ Top bar (56px) ]
                  [ Context selectors bar (optional, 48px) ]
                  [ Main content canvas ] [ 400px Inspector (optional) ]
```

---

## RBAC model (2 roles for now)

| Role | Capabilities |
|---|---|
| **Admin** | Creates project, owns configuration (onboarding), manages layers/groups/components, uploads data dictionary and macros |
| **Developer** | Loads existing project + configuration, runs analysis, views and exports documents, reviews generated content |

---

## Stakeholder review feedback (must incorporate)

1. **Product name** — not decided yet, use `[PRODUCT NAME]` as placeholder
2. **Help icons** — add `?` icons on sections; use icon buttons instead of verbose text labels
3. **Macro/Makefile upload** — support file upload (Makefile or CSV) instead of manual text entry
4. **Rename "Clang Static Analysis Config"** → **"Build Configuration"**
5. **Rename "Macros & Definitions"** → **"Preprocessor Definitions"** (or "Defines")
6. **Rename + rework "System Architecture Mapping"** — split into two distinct areas:
   - External libraries / include path management
   - Project architecture tree (layers → groups → components)
7. **RBAC** — Admin vs Developer role views (see RBAC model above)
8. **Project Configuration → Onboarding page** — guided setup flow for Admins, not just a settings form
9. **Versioning** — not decided; design git-commit-tied first (each doc version maps to a commit hash), keep flexible for internal versioning layer later
10. **Comparison view** — GitHub / Beyond Compare level: line-level diffs, side-by-side panels, inline comments, accept/reject per chunk

---

## Pages to design (priority order)

1. **Shared shell** — sidebar navigation, top bar, design tokens, responsive layout
2. **Onboarding / Project Configuration** — Admin role, guided setup flow
3. **SWE.3 document view** — document canvas + inspector panel
4. **SWE.3 empty state + generation flow** — progress, live log console
5. **SWE.3 comparison view** — GitHub-level diff
6. **Overview dashboard** — compliance metrics, process status
7. **Sign-in** — SSO + credentials

---

## Open decisions

| Decision | Status |
|---|---|
| Product name | TBD |
| Versioning model | TBD — design for git-commit-tied first |
| "Build Configuration" as final name | Proposed, not confirmed |
| "Preprocessor Definitions" as final name | Proposed, not confirmed |
| SYS.1 / SYS.2 / SWE.1 / SWE.2 page designs | Not started |
| Auth provider for SSO | TBD |

---

## Navigation structure (from reference designs)

```
Sidebar:
  Overview
  ── System Engineering ──
  SYS.1 Requirement Elicitation
  SYS.2 System Requirements
  ── Software Engineering ──
  SWE.1 Software Requirements
  SWE.2 Software Architecture
  SWE.3 Detailed Design          ← primary built feature
  ── Settings ──
  Project Configuration / Onboarding
```
