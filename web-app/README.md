# Frontend App

Web client for the ASPICE doc-automation product. React 19 + Vite + TypeScript + Tailwind v4.
Wired to the real FastAPI server in [`../../api`](../../api) (see [INTEGRATION_NOTES.md](INTEGRATION_NOTES.md));
the design mockups it ports live in [`../docs/ui-mockups/`](../docs/ui-mockups/).

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
├── services/      api/ + mappers/ — per-domain HTTP calls + wire⇄FE mapping
├── store/         Zustand (auth, ui)
├── types/         shared types
└── index.css      Tailwind + design tokens (@theme)
```

## Conventions

Full rules — structure, the design-system primitives + token usage (no inline styles), and the
hooks-only data flow — are in [CONVENTIONS.md](CONVENTIONS.md) (ESLint-enforced). In short:

- **Style with tokens + `ui/` primitives** (`Icon`, `Text`, `Card`, …) — never inline `style={{}}`.
- **Read data through `hooks/`** — a component never imports `services/` at runtime.
- **Keep pages thin** — big pages live in `pages/<Name>/`.
- **Commits**: short and prefixed — `feat:`, `fix:`, `docs:`.

Product & design context: [`../docs/UI_CONTEXT.md`](../docs/UI_CONTEXT.md).
