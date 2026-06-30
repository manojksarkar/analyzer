# Frontend UI Design Context

> Last updated: 2026-06-22
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

## Design files

8 HTML mockups live in `docs/ui-mockups/`. Read these before implementing any page in React.

| File | Sidebar | Subbar | What it shows |
|---|---|---|---|
| `signin.html` | none | no | Two-panel auth: left = product branding + feature bullets; right = SSO button, email/password form, remember-me, sign-up link |
| `projects.html` | 220px | yes | All-projects table — project name, standard (ISO 26262/ASPICE level), latest version, docs in review, progress bar, last run, team avatars, row kebab menu (Settings / Archive / Delete) |
| `projects-empty.html` | 220px | yes | Empty state → 5-step new-project wizard (Project & Repo → Build Config → Architecture → Team & Access → Review & Init); plus "Request Project Access" modal |
| `project-detail.html` | 220px | yes | Project overview: KPI cards, live generation progress (phases), documents table, team list, review queue, function-visibility slide-over, Admin/Developer role switcher, Run Analysis modal, version/commit picker |
| `documents.html` | 56px collapsed | yes | Document list with process filter tabs (All / SYS.1 / SYS.2 / SWE.1 / SWE.2 / SWE.3), status + assignee filters, batch actions (Download / Assign / Approve), edit-section modal, assign-reviewers slide panel |
| `compare.html` | 56px collapsed | yes | Split diff view: left = reference version, right = current version; per-section Accept / Decline / Edit controls; section progress dots; approve/submit footer |
| `team.html` | 220px | yes | Team table: member, role dropdown (Admin/Developer), last active, row actions; pending-invite rows with Resend / Revoke; Invite Member modal; permission legend card |
| `versions.html` | 56px collapsed | yes | Tagged version cards (status: In Review / Approved, commit hash, doc count, View Docs + Compare buttons); untagged commits timeline below; filter tabs (All / In Review / Complete) |

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

## Pages — implementation order

All pages are designed as HTML mockups in `docs/ui-mockups/`. Build in React in this order:

1. **Shared shell** — sidebar (220px / 56px collapsed), top bar, subbar, design tokens (`signin.html`, `projects.html`)
2. **Sign-in** — `signin.html`
3. **Projects list** — `projects.html` + empty state / onboarding wizard (`projects-empty.html`)
4. **Project detail / overview** — `project-detail.html` (covers KPIs, generation progress, run analysis, function visibility)
5. **Documents** — `documents.html` (list view, filters, batch actions, edit modal)
6. **Compare** — `compare.html` (split diff, review controls)
7. **Versions** — `versions.html`
8. **Team** — `team.html`

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

## Navigation structure (from designs)

**Global (no project selected):**
- Top bar: `[⬡ PRODUCT NAME]` left; notifications · help · user avatar right
- `projects.html` — full-width, no sidebar; logo top-left links home

**Project-scoped sidebar (220px expanded / 56px collapsed):**
```
← All Projects
[Project Name]          ← 10px uppercase label

Overview                → project-detail.html
Documents               → documents.html
Compare                 → compare.html
Versions                → versions.html
Team                    → team.html
─────────────────
Settings                (bottom, below border-t)
```

**Subbar (all project-scoped pages):**
```
[ 📁 VCU Engine Firmware ▾ ]  ·  [ v1.2.0 ▾ ]  ·  ⑂ main @ d9a0c55  ·  Jun 15    [CTA]
```
- Project switcher → version/commit picker (Versions / Commits tabs) → read-only commit chip → page CTA
- CTAs: Overview `[▶ RUN ANALYSIS]`, Documents `[↓ Download All]`, Compare `[✓ Accept All] [✗ Reject All]`, Versions — none, Team `[+ Invite]`

**Breadcrumbs** — always start with `[⬡]` home icon (→ projects.html):
- Overview:   `[⬡] / VCU Engine Firmware / Overview`
- Documents:  `[⬡] / VCU Engine Firmware / Documents`
- Compare:    `[⬡] / VCU Engine Firmware / Documents / Compare`
- Versions:   `[⬡] / VCU Engine Firmware / Versions`
- Team:       `[⬡] / VCU Engine Firmware / Team`
