# Contributing

How we write code in this app so a team can move fast without stepping on each other. Read
[ARCHITECTURE.md](ARCHITECTURE.md) first for the layout; this doc is the rules.

These conventions are **enforced in review**. If something here is wrong or slowing us down,
change the doc in the same PR — don't just ignore it.

---

## Workflow

```bash
npm install
npm run dev                      # develop
npm run lint                     # before committing
npm run build                    # MUST be green before opening a PR (tsc -b + vite build)
```

- Branch off `main`: `feat/...`, `fix/...`, `docs/...`, `refactor/...`.
- Keep PRs small and single-purpose. A 400-line page rewrite and a token cleanup are two PRs.
- Never commit with a red `build`.

---

## Design principles

Six rules. Each exists because we already felt the pain of its absence.

### 1. Tokens, not literals
Colors, spacing, radii, and type come from the `@theme` tokens in
[`src/index.css`](src/index.css) — **never a raw hex/px in a component.** One source of truth
means a rebrand is a one-line change, not a 100-file find-and-replace.

### 2. Compose primitives, not inline styles
Build screens out of `components/ui/` primitives and Tailwind utilities. `style={{}}` is
reserved for genuinely **dynamic** values (a computed width, a progress %, a data-driven color) —
not for static layout you didn't feel like writing as a class.

### 3. Thin pages, fat features
A `pages/` file orchestrates: read params, call hooks, compose. Rendering lives in `features/`
or `ui/` components. Aim for **≤ ~150 lines** per component; if it's longer, it's doing too much.

### 4. One source of truth per widget
A status badge, process badge, or avatar is defined **once** and imported everywhere. Re-implementing
the same widget per page is how five subtly-different badges end up in the product.
(`ProcessBadge` / `RoleBadge` already live in `components/ui/Badge.tsx` — use them.)

### 5. Data behind the boundary
Components read data through `hooks/` only. No component imports `services/api.ts` or
`data/mock.ts`. This is what lets us swap mock → backend without touching the UI.

### 6. Typed contracts, no `any`
Domain shapes live in `src/types/`. Props are typed. `any` and non-null-assertion-by-reflex (`!`)
need a comment justifying them or they don't pass review.

---

## Styling

**Use token utilities.** Tailwind v4 turns each `@theme` token into utilities automatically.

| Token | Utilities |
|---|---|
| `--color-primary` (navy) | `text-primary` `bg-primary` `border-primary` |
| `--color-secondary` (blue) | `text-secondary` `bg-secondary` `border-secondary` |
| `--color-on-tertiary-container` (green) | `text-on-tertiary-container` … |
| `--color-error` | `text-error` `bg-error` … |
| `--color-surface` / `-container-low` / `-container` | `bg-surface` `bg-surface-container-low` … |
| `--color-on-surface` / `-variant` | `text-on-surface` `text-on-surface-variant` |
| `--color-outline-variant` | `border-outline-variant` |
| `--spacing-sidebar-width` (220px) | `w-sidebar-width` |
| `--font-mono` (JetBrains Mono) | `font-mono` |

```tsx
// ❌ Don't — raw literals, can't be themed or linted
<span style={{ color: '#0058be', padding: '4px 10px', fontFamily: "'JetBrains Mono'" }}>

// ✅ Do — token utilities
<span className="text-secondary px-2.5 py-1 font-mono">
```

**Need a value that isn't a token?** Add the token to `index.css` first, then use it. Don't
inline the hex "just this once."

**Combining classes:** use [`cn()`](src/lib/cn.ts) (`clsx` + `tailwind-merge`) for conditional
or merged class names — it dedupes conflicting Tailwind classes correctly.

```tsx
import { cn } from '../lib/cn'
<button className={cn('px-3 py-1.5 rounded-lg', active && 'bg-secondary text-on-secondary')} />
```

**Legitimate `style={{}}`:** dynamic-only.
```tsx
<div className="progress-fill bg-secondary" style={{ width: `${progress}%` }} />
```

---

## Components

- **Primitives** (`components/ui/`): presentational, domain-agnostic, token-driven. Export through
  the barrel [`components/ui/index.ts`](src/components/ui/index.ts). They must not know about
  `Document`, routes, or fetching.
- **Domain widgets** reused across pages: define once (in `ui/`, or a `components/domain/` folder
  if it grows), never copy-paste per page.
- **Feature components** (`features/<area>/`): compose primitives for one domain area.
- One component per file; filename matches the component (`DocumentRow.tsx` → `DocumentRow`).
- Props are an explicit typed interface. Prefer composition (`children`) over boolean prop sprawl.

---

## Files & folders

| You're adding… | Put it in… |
|---|---|
| A new screen | `pages/` (thin) + its `features/<area>/` parts |
| A reusable button/input/badge/etc. | `components/ui/` (+ barrel export) |
| A data read/write | a function in `services/api.ts` + a hook in `hooks/` |
| A cross-page client toggle/session | a `store/` slice |
| A domain type | `types/index.ts` |
| A pure helper | `lib/` |

Imports are ordered: external packages → internal absolute (`../store`, `../lib`) → relative.
Don't import from a layer above you (see [ARCHITECTURE.md](ARCHITECTURE.md#layering)).

---

## Commits

Short, lower-case, conventional prefix, present tense. No filler, no AI/co-author trailers.

```
feat: add document status filter
fix: correct compare pane alignment
refactor: extract DocumentRow from DocumentsPage
docs: document styling rules
```

One logical change per commit. If the message needs "and", it's probably two commits.

---

## Pull requests — Definition of Done

A PR is ready when:

- [ ] `npm run build` is green (type-check + build)
- [ ] `npm run lint` is clean
- [ ] No new raw hex / inline static styles (principles 1–2)
- [ ] No component imports `services/` or `data/mock.ts` directly (principle 5)
- [ ] Touched a big page? Left it **more** decomposed than you found it (principle 3)
- [ ] If you changed structure/conventions, updated the relevant doc in the same PR
- [ ] PR description says **what** changed and **why**, and links the design/issue if there is one

---

## Tooling status

| Guardrail | State |
|---|---|
| TypeScript strict + `tsc -b` in build | ✅ active |
| ESLint (react-hooks, react-refresh, typescript-eslint) | ✅ active (`npm run lint`) |
| Prettier (shared formatting) | ⏳ planned |
| Lint rule banning raw hex in `.tsx` | ⏳ planned (enforces principle 1) |
| Vitest + Testing Library | ⏳ planned |
| CI: typecheck + lint + test + build on PR | ⏳ planned |

The planned items turn the principles above from "agreed in review" into "enforced by the tool."
Until they land, **we enforce them in review.**
