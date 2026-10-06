---
name: ui-dev
description: >-
  The UI/frontend developer role for web-app/ (React 19 + Vite + TypeScript + Tailwind v4). Load this BEFORE
  writing or editing any web-app/ code: pages, components, hooks, services/mappers, stores, styling, or tests.
  Carries the ESLint-enforced conventions — layered structure, design-system tokens + ui/ primitives (never inline
  style), hooks-only data flow, React Query vs Zustand split, the pre-PR verify steps, and commit style. Points to
  the deep web-app reference docs (TESTING, INTEGRATION_NOTES, PROJECT_CONTEXT).
---

# Role: UI / frontend developer (`web-app/`)

Rules for `web-app/` — **ESLint-enforced**. This skill is the single source of truth for them.

> TL;DR: **read data through `hooks/`**, **style with tokens + `ui/` primitives (never inline `style`)**,
> **keep pages thin**, **big pages get a folder**.

Start context (read as needed, don't duplicate here):
- **Product/design what & why** → [web-app/PROJECT_CONTEXT.md](web-app/PROJECT_CONTEXT.md) (agent-facing).
- **API wiring, wire-format mappers, per-page gaps** → [web-app/INTEGRATION_NOTES.md](web-app/INTEGRATION_NOTES.md).
- **Testing (unit + live-API contract suite)** → [web-app/TESTING.md](web-app/TESTING.md).
- **Review & update (reviewers correct LLM text)** → the HTTP contract
  [docs/spec/REVIEW_UPDATE_API_SPEC.md](docs/spec/REVIEW_UPDATE_API_SPEC.md); the screen is the
  document reader's edit mode (§6 below).

## 1. Structure (layered)

```
src/
├── pages/         one screen each; a big screen is a folder (see below)
├── components/
│   ├── ui/        design-system primitives (Icon, Text, Card, Button, Badge, …)
│   └── shell/     Sidebar, Topbar, Subbar, ProjectLayout
├── hooks/         React Query read + mutation hooks — the ONLY way the UI gets data
├── services/      api/ (HTTP calls) + mappers/ (wire ⇄ FE types) — one file per domain
├── store/         Zustand (auth, ui)
├── lib/           cross-cutting helpers (http, cn, format, queryClient)
├── types/         shared types
└── index.css      Tailwind + @theme design tokens
```

- **Big page → folder.** When a page grows past ~250 lines, convert it to
  `pages/<Name>/{index.tsx, components/, helpers.ts}`. `index.tsx` owns data + layout; presentational
  sub-components and pure helpers move out. This pre-shapes the eventual feature-folder move.
- **Global vs domain-local.** A hook/service is *global* (stays in `hooks/`, `lib/`, `services/`) if
  2+ domains use it (e.g. `useProjects`/`projectKeys`, `http`, `format`). Otherwise it's *domain-local*
  and conceptually belongs with its page.
- **Feature folders are deferred, not rejected.** Stay layered until the global-vs-local boundary settles;
  revisit `src/features/<domain>/` later. The "big page → folder" rule makes that move a drag-and-drop.

## 2. Design system — styling

Tokens live in [web-app/src/index.css](web-app/src/index.css) `@theme`. **Never hardcode** colours, font
sizes, or spacing inline — use the token utilities or a `ui/` primitive.

### Primitives (prefer these)

| Primitive | Use for | Replaces |
|---|---|---|
| `Icon` | Material Symbols icons | `<span className="material-symbols-outlined" style={{ fontSize }}>` — pass `size` / `fill` |
| `Text` | typographic text | mono/label/body `<span>`/`<p>` with inline font props; `variant` + `className` overrides |
| `Card` | standard white panel chrome | `bg-white border border-outline-variant rounded-xl` |
| `Row` / `Stack` | flex row / column | `flex items-center` / `flex flex-col` |
| `Button`, `Badge`, `Input`, `Modal`, `Select`, `Checkbox`, … | their obvious roles | bespoke markup |

`Text` variants: `label` (mono 10px caps), `caption` (11px muted), `mono` (12px), `body` (13px),
`title` (15px semibold), `heading` (18px semibold). Compose, don't fork — mono-11px is
`<Text variant="caption" className="font-mono">`.

### Token cheatsheet (inline value → utility)

- **Font size:** 9→`text-micro`, 10→`text-label`, 11→`text-caption`, 12→`text-xs`, 13→`text-body`,
  14→`text-sm`, 15→`text-title`, 18→`text-lg`. A new `--text-*` token goes into `lib/cn.ts` too, or
  `cn()` takes it for a colour and drops it beside `text-<colour>`.
- **Colour:** use the semantic `@theme` colours — `text-on-surface`, `text-on-surface-variant`,
  `text-outline`, `text-secondary`, `bg-surface`, `bg-surface-container*`, `border-outline-variant`,
  `bg-amber`, and the status ones: `success`, `warn`, `caution`, `violet`, `muted`, `faint`, `track`,
  `tint`, `info-line`, `highlight`, `page`, `inverse`, `selected`, `hero`. A recurring colour with no
  token should *become* a token (add to `@theme` **and** to the dark block); a one-off may use an
  arbitrary utility — but **arbitrary ≠ inline style** (it's still a class).
- **Two themes (2026-10-06):** light is `@theme`, dark redefines the same variables under
  `:root[data-theme="dark"]` in `index.css` (dark mockups' palette, `docs/ui-mockups/dark/`). So **no
  hex in a component, and no `bg-white`** (use `bg-surface-container-lowest`): a hard-coded colour does
  not switch. A data-driven colour reads `var(--color-…)`. "Primary" flips to near-white in dark — a
  dark fill under white text is `bg-inverse` (or `bg-selected` for the active nav item). No red for a
  state: "Changes requested" is violet, a failure amber; red is for genuine errors only. The toggle:
  `components/shell/ThemeToggle.tsx`, `store/theme.ts` (`localStorage.theme`, default dark), set
  before paint by the inline script in `index.html`.
- **Radius:** 4→`rounded-lg`, 8→`rounded-xl`, 12→`rounded-2xl`, pill→`rounded-full`; others arbitrary
  `rounded-[6px]`.

### The inline-style rule (lint-enforced)

`style={{}}` is a **warning** (`no-restricted-syntax`). The *only* legitimate uses are genuinely dynamic
values that can't be a class — data-driven colour, a computed width %, donut math. Mark each with a reason:

```tsx
{/* eslint-disable-next-line no-restricted-syntax -- accent colour is data-driven */}
<div className="w-1 flex-shrink-0" style={{ background: accentColor(status) }} />
```

If a value is static, it has a token/utility — use it.

## 3. Data & state

**Server state → React Query. Client state → Zustand. Never mix them.**

- **Components read through `hooks/` only** — never import `services/` at runtime from a page or component
  (lint-enforced; type-only imports are fine). Mutations that call the API directly belong in a hook.
- **Query keys come from the `projectKeys` factory** in [web-app/src/hooks/useProjects.ts](web-app/src/hooks/useProjects.ts) —
  don't inline key arrays.
- **Mutation hooks** follow the standard shape: `useMutation` + `onSuccess` invalidate the relevant
  `projectKeys` + a `toast`; `onError` → `toast.error`. See [web-app/src/hooks/useVersionMutations.ts](web-app/src/hooks/useVersionMutations.ts).

### The store (Zustand, `store/`)

Zustand holds **client/UI/session state only** — never a copy of server data (that's React Query's job).

- **Small, focused stores**, one per concern ([auth](web-app/src/store/auth.ts), [ui](web-app/src/store/ui.ts)) —
  not one mega-store. A new client-state concern gets its own thin store.
- **Select narrow slices**: `useAuthStore((s) => s.user)`, not the whole store — avoids needless re-renders.
- **Persist only what should survive reload** via `persist` + `partialize`. Deliberately *not* persisted:
  `auth.bootstrapped` (must re-validate each load) and `ui.selectedRef` (ephemeral).

## 4. Verify before a PR

```bash
npm run build   # tsc -b + vite build — must be clean
npm run lint    # new code adds no warnings; pre-existing debt is tracked
npm test        # Vitest unit suite (mappers/components/hooks) — must be green
```

`npm run test:api` validates a **live** API's responses against the schemas the UI expects (run the mock,
or point `API_TEST_URL` at the real API — it's read-only against a real backend). See
[web-app/TESTING.md](web-app/TESTING.md).

Migrations must be **pixel-identical** — they swap *how* a value is expressed (token/primitive), not the
value. Spot-check against the mock in [docs/ui-mockups/](docs/ui-mockups/).

## 5. Commits

Short, prefixed (`feat:`, `fix:`, `docs:`, `refactor:`). No "Claude" mentions, no co-author trailer.

## 6. Review & update (reviewers correct LLM text)

A reviewer corrects the LLM's wording in a generated document: **Edit** (Subbar) turns the SWE.3
reader into edit mode — `pages/DocumentInspectorPage/` (`components/SlotText.tsx` per text,
`FlowchartLabelDialog.tsx` per chart, `ReviewBars.tsx` for the R9 banner + Re-export, the right
panel's Outline/Corrections tabs). Data: `services/api/review.ts`, `services/mappers/review.ts`,
`hooks/useReview.ts`. Contract: [REVIEW_UPDATE_API_SPEC](docs/spec/REVIEW_UPDATE_API_SPEC.md) — §3a
lists the calls per screen. Rules the spec's tests cannot enforce on the client:

- **Never build a slot key.** Take it from a read — the render payload carries each text's `Slot`
  (`cell_slots`, `*_slot`, `content_slot`), R7 each flowchart node's, R11 any — and send it back
  unchanged.
- **A flowchart is named by its `flowchart_id`** (render payload, R11 `flowchartId`) — in R7's query
  and R8's body. It is not a node's `slotKey` (that is the flowchart id, a separator and the node
  id); the server answers 400 if one is sent.
- **One shape for a slot, from every route** (API spec §5 `Slot`): `text` is what the document
  prints; `isOverridden` means a correction is in force; an orphaned one (`isOrphaned`) is not, and
  its `humanText` is not on the page; `llmText` is what the LLM wrote. Render a slot from these
  names whichever call returned it. **Offer Undo exactly where `canUndo` is `true`.**
- **`shownIn: []` means no document prints that text** (in this scope the function is not published).
  Say so next to the field rather than hide it.
- **A save answers with the slot as it now is** (R8: each saved node, and the rebuilt `dot`) — show
  that; no refetch is needed for the edited item. Nothing is pushed, so another reviewer's saves
  appear on the next read; two saves of one slot: the later wins, and its `previousText` says what
  it replaced. Before offering an export, read R9: `stale` or `pendingRenders` means the Word file
  does not match the corrections yet.
- **A slot's `text` is its own, not always what the page prints**: an empty slot shows a stand-in
  ("X input", the interface descriptions' join). Edit the slot's text; show the stand-in as a hint.
- **Flowcharts are server-drawn SVGs**, redrawn by the label save itself; the mapper adds
  `?v=<source_hash>` so the `<img>` reloads. A save changes the page, not the Word file (R9).

## 7. Review and approval (assign, submit, approve, reopen)

Contract: [REVIEW_APPROVE_API_SPEC](docs/spec/REVIEW_APPROVE_API_SPEC.md) (A1–A19). Data:
`services/api/approval.ts`, `services/mappers/approval.ts`, `hooks/useApproval.ts`. Screens: the reader's
`ReviewTab.tsx` / `ReviewDialogs.tsx` / banners in `ReviewBars.tsx`, `components/review/AssignReviewerDialog.tsx`,
`pages/DocumentsPage/`, `pages/ProjectDetailPage/` (queues). The rules live in the API — the client never
decides them:

- **One status vocabulary**: `lib/reviewStatus.ts` + `ui/StatusBadge`. Never add a local status map.
- **Ask, don't infer, who may act**: a 409 (`WRONG_STATE`, `STALE_EXPORT`, `DOCUMENT_APPROVED`,
  `HAS_REVIEWER`, `NO_REVIEWER`) is the authority; show its message and refetch. Approve is gated on R9 for
  the document (A15), but the server's `STALE_EXPORT` is the real guard.
- **"Me" is a user id**, never a display name. A version's status is the API's (derived) — never computed
  on the client from a partial list.
- **Tests**: `npm test`. A bare `npx vitest run` also runs the live API suite, which WRITES to whatever
  `localhost:8000` is; run `npm run test:api` only with `API_TEST_URL` at a throwaway API.
