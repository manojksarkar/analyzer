# Testing

Two layers, run independently:

| Suite | Command | Needs a backend? | What it proves |
|---|---|---|---|
| **Unit** (Tier 1) | `npm test` | **No** — MSW serves committed fixtures | Mappers, components, hooks behave |
| **API tests** (Tier 2) | `npm run test:api` | **Yes** — a live API on `VITE_API_URL` | The API's responses match what the UI expects |

```bash
npm test            # hermetic UI tests (jsdom + MSW), watch: npm run test:watch
npm run test:api        # validate the live API (auto-skips if none is reachable)
npm run test:capture    # refresh src/test/fixtures/captured/ from a running API
```

### See each test name (verbose)

By default Vitest prints only a summary. Pass the verbose reporter (after `--`) to print every test
name as it runs:

```bash
npm test -- --reporter=verbose          # unit: file > describe > it, one line each
npm run test:api -- --reporter=verbose  # api: each endpoint + each test case

# other useful filters:
npm test -- project.test.ts             # run one file
npm test -- -t "not_run"                # run only tests whose name matches text
npm run test:watch                      # interactive; prints names and reruns on save
```

A unit test's name is `<file> > <describe> > <it>` — e.g.
`project.test.ts > mapProject > maps the not_run status to the "never" page state`. The API suite
additionally prints its per-endpoint report (the `✓ [200] GET …` lines) regardless of reporter.

To make verbose the **default** for every run, add `reporters: ['verbose']` under each project's `test`
in [vitest.config.ts](vitest.config.ts).

## Tier 1 — UI unit tests (no backend)

`vitest` + Testing Library + **MSW** ([src/test/setup.ts](src/test/setup.ts),
[src/test/handlers.ts](src/test/handlers.ts)). MSW intercepts HTTP and answers from committed
fixtures, so this suite runs offline and **keeps working even if `mock-api/` is deleted**. Tests live
next to the code in `__tests__/` folders:

- `src/services/mappers/__tests__/*` — snake_case → camelCase, derived fields, edge cases.
- `src/components/ui/__tests__/*`, `src/hooks/__tests__/*` — render/data-flow smoke tests.

Add a page's endpoint to [src/test/handlers.ts](src/test/handlers.ts) (returning a fixture) and write
tests as you cover more screens. Unhandled requests fail loudly (`onUnhandledRequest: 'error'`).

## Tier 2 — API tests (the mock↔real safety net)

**The point:** the same suite is green against the mock today and tells you exactly what drifted when
you point it at the real API. It signs in and exercises **every endpoint the web-app calls** (~46 —
reads, writes, binary download, and the wizard endpoints), threading the ids it discovers (so it works
against any seed data), validating each **raw** response against the **zod schema the UI expects**. Those
schemas are the single source of truth: each mapper's `Api*` type is `z.infer<>` of its schema (e.g.
[services/mappers/project.ts](src/services/mappers/project.ts)), composed into response envelopes in
[src/test/api/registry.ts](src/test/api/registry.ts). Validation depth per endpoint:

- **reads** + writes whose response the UI consumes → full **schema** check.
- writes the UI ignores (approve, assign, mark-read, …) → **2xx** check (the endpoint exists & works).
- **SSE / asset / binary** → reachability + content-type (can't be JSON-schema'd).

### Data safety — the real API is never written to

Write requests (`POST`/`PATCH`/`DELETE`) are issued **only against a local target** (the mock, which
resets on restart). Pointed at a remote/real API (`API_TEST_URL` not localhost) the suite is strictly
**read-only**, so it can never persist or corrupt real data. So against the mock, a run creates+deletes a
throwaway project and touches the seed doc/notifications — restart the mock to reset. Slow/external
endpoints (git clone, the job runner, upload) additionally need `API_TEST_HEAVY=1` and are also
local-only.

> Want write coverage against the real API too, without the risk? Validate the write endpoints **statically**
> against the API's Swagger/OpenAPI spec (`/openapi.json`) — a read-only check, no requests issued. See
> "Swagger/OpenAPI check" below.

It reports two kinds of finding (see [validate.ts](src/test/api/validate.ts)):

- **Mismatch (fails the suite)** — a required field is missing or has the wrong type. This *would*
  break the UI.
- **New field (warning)** — the API returned a key the UI doesn't model yet. Non-breaking.

A per-endpoint report prints to stdout and is written to `api-test-report.txt` (gitignored):

```
✓ [200] GET /projects
✓ [200] GET …/commits
    + extra field: pagination
...
46 endpoints · 0 mismatch(es) · 4 new field(s)
```

It also asserts the two browser constraints a token can't satisfy: the **job-events SSE** route and the
**diagram asset** route must be reachable without a `Bearer` header, and a real diagram `image_url`
must load as an actual image (see "Diagram assets" below).

### Point it at the real API

No code change — it's all env (and read-only, per "Data safety" above):

```bash
API_TEST_URL=https://real-api.example.com/api/v1 \
API_TEST_EMAIL=you@org.com API_TEST_PASSWORD=… \
npm run test:api
```

Defaults: `VITE_API_URL` (or `http://localhost:8000/api/v1`), `alice@aspice.dev` / `secret`.

### Swagger/OpenAPI check (optional, fully read-only)

FastAPI auto-generates `/openapi.json`. A spec check fetches only that — **no endpoint calls, zero data
risk** — and verifies the real API still declares every path/method the web-app calls (and, where the API
declares response models, that their shapes match). It's the safe way to cover **write** endpoints against
a real API. *Not wired up yet* — it pays off once the `api/` team adds response models to their routes;
until then it can only check that endpoints exist. Ask to enable it.

### Diagram assets (relative path → asset endpoint)

The render payload returns `image_url` as a **relative path/key**, not a baked-in absolute link. The UI
builds the loadable URL in `resolveAssetUrl` ([services/mappers/document.ts](src/services/mappers/document.ts))
— the single place this lives — and lazy-loads it with `<img loading="lazy">`. Two shapes, selected by
**`VITE_ASSET_ENDPOINT`**:

- **unset (default)** — the ref is a path under the base: `${VITE_API_URL}/<path>` (the mock's REST
  asset route, e.g. `…/projects/p1/documents/doc1/assets/foo.png`).
- **set** (e.g. `VITE_ASSET_ENDPOINT=/assets`) — the path is handed to a dedicated endpoint as a query:
  `${VITE_API_URL}/assets?path=<path>` (the real-API model). An absolute/CDN URL always passes through.

Because an `<img>` sends **no** `Authorization` header, whichever endpoint serves the bytes must be
reachable without a Bearer (the `path` query carries the asset path, never a token). The API suite
builds the URL the same way (honouring `VITE_ASSET_ENDPOINT`), fetches a real `image_url`, and asserts
`200` + an `image/*` content-type — so a real API that returns a non-loadable link fails the suite. If
the asset endpoint *must* be authenticated, the inspector switches to a **blob fetch** (auth GET →
`URL.createObjectURL`) instead of `<img src>`.

## Fixtures

- `src/test/fixtures/*.json` — **curated**, trimmed snapshots the unit tests assert against (stable).
- `src/test/fixtures/captured/*.json` — **raw** snapshots from `npm run test:capture`; reference data and
  an optional MSW source. Refresh after a backend change.
