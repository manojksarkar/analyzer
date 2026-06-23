# Frontend App

The web client for the ASPICE compliance-automation product — point it at a C++ firmware
repo and manage the auto-generated engineering documents (SWE.3 Software Detailed Design today,
more processes to follow).

This is the **working React application**. The pixel-reference HTML mockups it ports live in
[`../designs/`](../designs/).

> **Status:** Pre-backend. The app runs entirely on mock data (see [`src/data/mock.ts`](src/data/mock.ts))
> behind a real service boundary, so swapping in the API later touches one layer, not the UI.
> Currently on branch `feat/frontend-app`, not yet merged to `main`.

---

## Tech stack

| Concern | Choice |
|---|---|
| Build / dev server | **Vite 8** |
| Language | **TypeScript 6** (strict) |
| UI | **React 19** |
| Styling | **Tailwind CSS v4** (`@theme` tokens in [`src/index.css`](src/index.css), no config file) |
| Routing | **react-router-dom 7** |
| Server state | **@tanstack/react-query 5** |
| Client state | **Zustand 5** (`src/store/`) |
| Accessible primitives | **Radix UI** (dialog, select, dropdown, checkbox, toast, tooltip…) |
| Forms + validation | **react-hook-form 7** + **zod 4** |
| Class composition | `clsx` + `tailwind-merge` → [`cn()`](src/lib/cn.ts) |
| Fonts | Inter + JetBrains Mono (`@fontsource`), Material Symbols (Google CDN) |

---

## Quick start

```bash
# from frontend/app/
npm install
npm run dev      # http://localhost:5173
```

| Script | What it does |
|---|---|
| `npm run dev` | Start Vite dev server with HMR |
| `npm run build` | Type-check (`tsc -b`) **and** production build. Run before every PR. |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | ESLint over the whole project |

> `npm run build` runs `tsc -b` (build mode), which catches errors `tsc --noEmit` misses —
> e.g. non-exhaustive `Record<Union, …>` maps. **Green `build` is the bar for merge.**

---

## Project structure

```
src/
├── main.tsx              Entry — mounts <App/>
├── App.tsx               Providers (QueryClient, Toast) + <Routes>
├── index.css             Tailwind import + @theme design tokens + base styles
│
├── pages/                Route components (one per screen)
├── components/
│   ├── ui/               Design-system primitives — Button, Input, Select, Modal,
│   │                     Badge, Dropdown, Checkbox, Skeleton, Toast (barrel: index.ts)
│   └── shell/            App chrome — ProjectLayout, Sidebar, Topbar, Subbar
│
├── hooks/                React Query hooks (useProjects, useDocuments, …)
├── services/             Data access layer (api.ts) — the mock→backend seam
├── store/                Zustand stores — auth, ui (roleView, sidebarCollapsed)
├── routes/               ProtectedRoute guard
├── lib/                  Pure utilities (cn, queryClient)
├── types/                Shared domain types
└── data/                 mock.ts — fixture data (temporary; lives behind services/)
```

---

## Documentation

Read these before contributing — **they are the source of truth, not tribal knowledge:**

| Doc | Read it for |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the app is layered, how data flows, where new code goes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Design principles, styling rules, component/commit/PR conventions |
| [../UI_CONTEXT.md](../UI_CONTEXT.md) | Product vision, design files, RBAC model, page intent (the *what & why*) |
| [../designs/](../designs/) | The HTML mockups each page ports 1:1 |
| [../../PROJECT_CONTEXT.md](../../PROJECT_CONTEXT.md) | Whole-repo context (backend pipeline + frontend), §24 = frontend |

**New to the codebase?** README → ARCHITECTURE → CONTRIBUTING, then open the design HTML for the
page you're touching next to its `src/pages/*.tsx`.
