# Frontend App

Web client for the ASPICE doc-automation product. React 19 + Vite + TypeScript + Tailwind v4.
Runs on mock data for now (`src/data/mock.ts`); the design mockups it ports live in [`../designs/`](../designs/).

## Run

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build — run before a PR
npm run lint
```

## Structure

```
src/
├── pages/         one component per screen
├── components/
│   ├── ui/        reusable primitives (Button, Badge, Modal, …)
│   └── shell/     Sidebar, Topbar, Subbar, layout
├── hooks/         React Query hooks — how the UI reads data
├── services/      api.ts — swap mock → real backend here
├── store/         Zustand (auth, ui)
├── types/         shared types
└── index.css      Tailwind + design tokens (@theme)
```

## Conventions

- **Use tokens, not raw hex** — colors/spacing live in `index.css`, e.g. `text-secondary`, `bg-surface`.
- **Read data through `hooks/`** — a component never imports `services/` or `mock.ts` directly.
- **Keep pages thin** — reuse `components/ui/` instead of re-styling inline.
- **Commits**: short and prefixed — `feat:`, `fix:`, `docs:`.

Product & design context: [`../UI_CONTEXT.md`](../UI_CONTEXT.md).
