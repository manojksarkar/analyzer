# Architecture

How this app is put together and **where new code belongs**. If you're about to add a file and
aren't sure where it goes, the answer is here. Pair this with [CONTRIBUTING.md](CONTRIBUTING.md)
(the rules) — this doc is the map, that one is the rulebook.

---

## Layering

Dependencies point **downward only**. A layer may import from layers below it, never above.

```
┌─────────────────────────────────────────────────────────────┐
│  pages/            Route screens. Orchestrate — fetch + compose.
│                    Thin. No business logic, minimal markup.
├─────────────────────────────────────────────────────────────┤
│  features/*        Domain UI for one area (documents, compare, …).   ← target
│                    Tables, rows, panels, domain badges. (see "Target" below)
├─────────────────────────────────────────────────────────────┤
│  components/shell  App chrome: ProjectLayout, Sidebar, Topbar, Subbar
│  components/ui     Design-system primitives: Button, Input, Modal, Badge…
├─────────────────────────────────────────────────────────────┤
│  hooks/            React Query hooks — the ONLY way UI reads data
├─────────────────────────────────────────────────────────────┤
│  services/         api.ts — data access. The mock↔backend seam.
├─────────────────────────────────────────────────────────────┤
│  store/  lib/  types/  data/   Cross-cutting: client state, utils, contracts
└─────────────────────────────────────────────────────────────┘
```

**The rule that keeps this honest:** a component never reaches past `hooks/` to grab data.
No page imports `services/api.ts` or `data/mock.ts` directly — it calls a hook.

---

## Layer responsibilities

| Layer | Owns | Must NOT |
|---|---|---|
| `pages/` | Read route params, call hooks, arrange feature/shell/ui pieces, handle page-level state | Contain table-row markup, fetch logic, or raw `fetch`/mock imports |
| `components/ui/` | Presentational, reusable primitives. Token-driven, domain-agnostic | Know about `Document`, `Project`, routes, or data fetching |
| `components/shell/` | The persistent frame around project pages | Render page-specific content |
| `hooks/` | Wrap `services/` calls in React Query; own query keys + cache config | Contain JSX |
| `services/api.ts` | Every read/write to the outside world. One function per endpoint | Be called from components directly (go through a hook) |
| `store/` | **Client** state only — auth session, `roleView`, `sidebarCollapsed` | Hold server data (that's React Query's job) |
| `lib/` | Pure, dependency-light helpers (`cn`, query client) | Import from `pages`/`components` |
| `types/` | Shared domain contracts | — |
| `data/mock.ts` | Fixtures, consumed **only** by `services/` | Be imported anywhere outside `services/` |

---

## Data flow

```
                    React Query                    props
services/api.ts ──────────────► hooks/ ──────────────► pages/ ──► ui & features
  (mock today)     queryFn        useQuery   data        render

  swap this …      … nothing below changes when the real backend lands
```

`services/api.ts` is deliberately shaped like a network client — every function is `async`,
returns a typed promise, and throws `Error` on failure. Today the bodies return `mock.ts`
fixtures after a fake delay. **When the backend is ready, only these function bodies change;**
hooks, pages, and components are untouched. That seam is the whole point — don't bypass it.

### Server state vs. client state

- **Server state** (projects, documents, versions, team, commits) → **React Query**, via `hooks/`.
  Query keys are centralized in [`hooks/useProjects.ts`](src/hooks/useProjects.ts) (`projectKeys`)
  so invalidation stays consistent.
- **Client state** (is the sidebar collapsed? Admin or Developer view? who's signed in?) → **Zustand**
  stores in `store/`. `auth` is persisted; `ui` holds `roleView` + `sidebarCollapsed`.

Don't put server data in Zustand, and don't manage UI toggles with React Query.

---

## Design tokens

All visual constants live in **one place**: the `@theme` block of
[`src/index.css`](src/index.css). Tailwind v4 generates utilities from them — `--color-secondary`
becomes `text-secondary` / `bg-secondary` / `border-secondary`, `--spacing-sidebar-width`
becomes `w-sidebar-width`, etc.

| Group | Tokens (excerpt) |
|---|---|
| Brand | `primary` (navy `#041627`), `secondary` (blue `#0058be`) |
| Status | `on-tertiary-container` (green `#00a572`), `error` (`#ba1a1a`), `amber` (`#f59e0b`) |
| Surfaces | `surface`, `surface-container-low/-/-high/-highest`, `surface-container-lowest` |
| Text | `on-surface`, `on-surface-variant` |
| Lines | `outline`, `outline-variant` |
| Layout | `sidebar-width` (220px), `sidebar-collapsed` (56px), `inspector-width` (400px) |
| Type | `font-sans` (Inter), `font-mono` (JetBrains Mono) |

**Need a new color/size?** Add a token here, then use its utility — never hardcode the hex in a
component. See the styling rules in [CONTRIBUTING.md](CONTRIBUTING.md#styling).

---

## Routing

[`App.tsx`](src/App.tsx) defines all routes. Everything except `/signin` is wrapped in
`ProtectedRoute` (redirects to `/signin` when unauthenticated). The four project-scoped pages
render inside `ProjectLayout` (Sidebar + Topbar + Subbar + `<Outlet/>`).

| Route | Page | Shell |
|---|---|---|
| `/signin` | `SignInPage` | none |
| `/projects` | `ProjectsPage` | none |
| `/projects/new` | `ProjectsEmptyPage` | none |
| `/projects/:projectId/overview` | `ProjectDetailPage` | `ProjectLayout` |
| `/projects/:projectId/documents` | `DocumentsPage` | `ProjectLayout` |
| `/projects/:projectId/compare` | `ComparePage` | `ProjectLayout` |
| `/projects/:projectId/versions` | `VersionsPage` | `ProjectLayout` |
| `/projects/:projectId/team` | `TeamPage` | `ProjectLayout` |

`/` and unmatched paths redirect to `/projects`.

---

## Target structure (where we're heading)

The layering above is the intent. **Today there's a known gap:** the pages are large and render
most markup inline instead of composing `features/` and `ui/`. We're closing it incrementally —
no big-bang rewrite. The target for each page:

```
pages/DocumentsPage.tsx          thin: useDocuments() + <DocumentsView/>
features/documents/
├── DocumentsView.tsx            layout, filter state, batch bar
├── DocumentTable.tsx            the table
├── DocumentRow.tsx              one row
└── (shared domain widgets live in components/ui or components/domain)
```

Guidelines while we converge:
- **New** screens/features follow the target shape from the start.
- **Touching** an existing page? Extract the part you change into a `features/` component rather
  than adding more inline markup. Leave it better than you found it.
- Domain widgets reused across pages (status badge, process badge, avatar) get defined **once**
  in `components/ui/` (note: `ProcessBadge`/`RoleBadge` already exist there — use them).

See the principles behind this in [CONTRIBUTING.md](CONTRIBUTING.md#design-principles).
