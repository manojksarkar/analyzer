# Frontend conventions

Rules for `web-app/` — ESLint-enforced and surfaced to Claude via the
[`frontend-conventions` skill](../../.claude/skills/frontend-conventions/SKILL.md).

> TL;DR: **read data through `hooks/`**, **style with tokens + `ui/` primitives (never inline
> `style`)**, **keep pages thin**, **big pages get a folder**.

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
  sub-components and pure helpers move out. This also pre-shapes the eventual feature-folder move.
- **Global vs domain-local.** A hook/service is *global* (stays in `hooks/`, `lib/`, `services/`) if
  2+ domains use it (e.g. `useProjects`/`projectKeys`, `http`, `format`). Otherwise it's
  *domain-local* and conceptually belongs with its page.
- **Feature folders are deferred, not rejected.** We stay layered until the global-vs-local boundary
  settles; revisit `src/features/<domain>/` later. The "big page → folder" rule makes that move a
  drag-and-drop.

## 2. Design system — styling

Tokens live in [`index.css`](src/index.css) `@theme`. **Never hardcode** colours, font sizes, or
spacing inline — use the token utilities or a `ui/` primitive.

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
  14→`text-sm`, 15→`text-title`, 18→`text-lg`.
- **Colour:** use the semantic `@theme` colours — `text-on-surface`, `text-on-surface-variant`,
  `text-outline`, `text-secondary`, `bg-surface`, `bg-surface-container*`, `border-outline-variant`,
  `bg-amber`. A recurring colour with no token should *become* a token (add to `@theme`); a one-off
  may use an arbitrary utility `bg-[#hex]` — but **arbitrary ≠ inline style** (it's still a class).
- **Radius:** 4→`rounded-lg`, 8→`rounded-xl`, 12→`rounded-2xl`, pill→`rounded-full`; others arbitrary
  `rounded-[6px]`.

### The inline-style rule (lint-enforced)

`style={{}}` is a **warning** (`no-restricted-syntax`). The *only* legitimate uses are genuinely
dynamic values that can't be a class — data-driven colour, a computed width %, donut math. Mark each
with a reason:

```tsx
{/* eslint-disable-next-line no-restricted-syntax -- accent colour is data-driven */}
<div className="w-1 flex-shrink-0" style={{ background: accentColor(status) }} />
```

If a value is static, it has a token/utility — use it.

## 3. Data & state

**Server state → React Query. Client state → Zustand. Never mix them.**

- **Components read through `hooks/` only** — never import `services/` at runtime from a page or
  component (lint-enforced; type-only imports are fine). Mutations that call the API directly belong
  in a hook.
- **Query keys come from the `projectKeys` factory** in [`hooks/useProjects.ts`](src/hooks/useProjects.ts) —
  don't inline key arrays.
- **Mutation hooks** follow the standard shape: `useMutation` + `onSuccess` invalidate the relevant
  `projectKeys` + a `toast`; `onError` → `toast.error`. See [`useVersionMutations.ts`](src/hooks/useVersionMutations.ts).

### The store (Zustand, `store/`)

Zustand holds **client/UI/session state only** — never a copy of server data (that's React Query's job).

- **Small, focused stores**, one per concern ([`auth`](src/store/auth.ts), [`ui`](src/store/ui.ts)) —
  not one mega-store. A new client-state concern gets its own thin store.
- **Select narrow slices**: `useAuthStore((s) => s.user)`, not the whole store — avoids needless
  re-renders.
- **Persist only what should survive reload** via `persist` + `partialize`. Deliberately *not*
  persisted: `auth.bootstrapped` (must re-validate each load) and `ui.selectedRef` (ephemeral).

## 4. Verify before a PR

```bash
npm run build   # tsc -b + vite build — must be clean
npm run lint    # new code adds no warnings; pre-existing debt is tracked
npm test        # Vitest unit suite (mappers/components/hooks) — must be green
```

`npm run test:api` validates a **live** API's responses against the schemas the UI expects (run
the mock, or point `API_TEST_URL` at the real API — it's read-only against a real backend).
See [TESTING.md](TESTING.md).

Migrations must be **pixel-identical** — they swap *how* a value is expressed (token/primitive), not
the value. Spot-check against the mock in [`../docs/ui-mockups/`](../docs/ui-mockups/).

## 5. Commits

Short, prefixed (`feat:`, `fix:`, `docs:`, `refactor:`). No "Claude" mentions, no co-author trailer.
