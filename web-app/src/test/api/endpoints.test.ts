import { writeFileSync } from 'node:fs'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import type { ZodType } from 'zod'
import { Envelopes } from './registry'
import { formatReport, validateResponse, type ReportRow } from './validate'

/**
 * Live API test suite (run by `npm run test:api`, NOT `npm test`).
 *
 * Covers every endpoint the web-app calls and validates each response against the
 * zod schema the UI expects. Reads (and responses the UI consumes from writes)
 * get a full schema check; writes the UI ignores get a 2xx check. It threads the
 * ids it discovers, so it works against any seed data. Green vs the mock today;
 * point it at the real API later (`API_TEST_URL=<url> npm run test:api`) and it
 * reports exactly which endpoint/field drifted. Auto-skips when no server is up.
 *
 * DATA SAFETY: write requests are issued ONLY against a local target (the mock,
 * which resets on restart). Pointed at a remote/real API the suite is strictly
 * READ-ONLY, so it can never persist or corrupt real data. Slow/external
 * endpoints (git clone, the job runner, upload) additionally need
 * `API_TEST_HEAVY=1` and are also local-only.
 */

const BASE = (
  process.env.API_TEST_URL ?? process.env.VITE_API_URL ?? 'http://localhost:8000/api/v1'
).replace(/\/+$/, '')
const EMAIL = process.env.API_TEST_EMAIL ?? 'alice@aspice.dev'
const PASSWORD = process.env.API_TEST_PASSWORD ?? 'secret'

const isLocal = /localhost|127\.0\.0\.1|\[::1\]/.test(BASE)
// Writes ONLY ever hit a local mock (resets on restart) — never a real API.
const MUTATE = isLocal
const HEAVY = isLocal && process.env.API_TEST_HEAVY === '1'

const rows: ReportRow[] = []
let serverUp = false
let token = ''
let refreshToken = ''
let sampleAssetRef: string | null = null

/* ── helpers ──────────────────────────────────────────────────────────── */

const ASSET_ENDPOINT = (process.env.VITE_ASSET_ENDPOINT ?? '').trim()
/** Mirror of the app's resolveAssetUrl (services/mappers/document.ts). */
function resolveRef(ref: string, base: string): string {
  if (/^(https?:)?\/\//i.test(ref)) return ref
  const path = ref.replace(/^\/+/, '')
  if (ASSET_ENDPOINT) {
    const ep = ASSET_ENDPOINT.startsWith('/') ? ASSET_ENDPOINT : `/${ASSET_ENDPOINT}`
    return `${base}${ep}?path=${encodeURIComponent(path)}`
  }
  return `${base}/${path}`
}

function pick(obj: unknown, ...path: (string | number)[]): unknown {
  let cur = obj
  for (const k of path) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string | number, unknown>)[k]
  }
  return cur
}
const pickStr = (obj: unknown, ...path: (string | number)[]): string | undefined => {
  const v = pick(obj, ...path)
  return typeof v === 'string' ? v : undefined
}
const firstId = (body: unknown, key: string): string | undefined => pickStr(body, key, 0, 'id')

/** Walk a render payload's section tree for the first diagram `image_url`. */
function findFirstImageUrl(body: unknown): string | null {
  const sections = pick(body, 'document', 'sections')
  const stack: unknown[] = Array.isArray(sections) ? [...sections] : []
  while (stack.length) {
    const s = stack.shift()
    const url = pickStr(s, 'image_url')
    if (url) return url
    const children = pick(s, 'children')
    if (Array.isArray(children)) stack.push(...children)
  }
  return null
}

interface CallOpts {
  schema?: ZodType
  body?: unknown
  optional?: boolean
  binary?: boolean
}
/** Hit an endpoint, validate, and record a report row. Never throws. */
async function call(
  name: string,
  method: string,
  path: string,
  opts: CallOpts = {},
): Promise<{ status: number | string; body: unknown }> {
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    })
  } catch (e) {
    rows.push({ name, status: 'ERR', result: null, note: `network: ${(e as Error).message}` })
    return { status: 'ERR', body: null }
  }
  let body: unknown = null
  if (!opts.binary) {
    try {
      body = await res.json()
    } catch {
      /* non-JSON body */
    }
  }
  if (!res.ok) {
    rows.push({
      name,
      status: res.status,
      result: null,
      note: opts.optional ? 'optional — skipped' : `HTTP ${res.status}`,
    })
    return { status: res.status, body }
  }
  if (opts.schema) {
    rows.push({ name, status: res.status, result: validateResponse(opts.schema, body) })
  } else {
    rows.push({
      name,
      status: res.status,
      result: null,
      note: opts.binary ? (res.headers.get('content-type') ?? 'binary') : 'ok',
    })
  }
  return { status: res.status, body }
}
const get = (name: string, path: string, schema: ZodType, opts: { optional?: boolean } = {}) =>
  call(name, 'GET', path, { schema, ...opts })

/* ── lifecycle ────────────────────────────────────────────────────────── */

beforeAll(async () => {
  try {
    const res = await fetch(`${BASE}/auth/signin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
    })
    serverUp = true
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      /* ignore */
    }
    rows.push({
      name: 'POST /auth/signin',
      status: res.status,
      result: res.ok ? validateResponse(Envelopes.signin, body) : null,
      note: res.ok ? undefined : `HTTP ${res.status}`,
    })
    token = pickStr(body, 'access_token') ?? ''
    refreshToken = pickStr(body, 'refresh_token') ?? ''
  } catch {
    serverUp = false
  }
})

afterAll(() => {
  if (!serverUp) {
    process.stdout.write(
      `\n[api-test] API not reachable at ${BASE} — suite skipped.\n` +
        `  Start the mock:          cd mock-api && python run.py\n` +
        `  Or target the real API:  API_TEST_URL=<url> npm run test:api\n\n`,
    )
    return
  }
  const report = formatReport(rows, BASE)
  process.stdout.write('\n' + report + '\n\n')
  try {
    writeFileSync('api-test-report.txt', report + '\n')
  } catch {
    /* report file is best-effort */
  }
})

/* ── the suite ────────────────────────────────────────────────────────── */

describe('API responses', () => {
  it('every endpoint the web-app calls returns the shape the UI expects', async (ctx) => {
    if (!serverUp) return ctx.skip()
    expect(token, 'sign-in failed — check API_TEST_EMAIL / API_TEST_PASSWORD').not.toBe('')

    /* ── auth ── */
    await get('GET /auth/me', '/auth/me', Envelopes.me)
    if (refreshToken) {
      await call('POST /auth/refresh', 'POST', '/auth/refresh', {
        schema: Envelopes.refresh,
        body: { refresh_token: refreshToken },
      })
    }

    /* ── top-level reads ── */
    const projects = await get('GET /projects', '/projects', Envelopes.projects)
    await get('GET /projects/search', '/projects/search?q=a', Envelopes.projectSearch, { optional: true })
    await get('GET /notifications', '/notifications', Envelopes.notifications)
    await get('GET /users/search', '/users/search?q=a', Envelopes.usersSearch, { optional: true })

    /* ── project-scoped reads ── */
    const projectId = firstId(projects.body, 'projects')
    let docId: string | undefined
    let versionId: string | undefined
    let sectionKey: string | undefined
    if (projectId) {
      const p = `/projects/${projectId}`
      await get('GET /projects/:id', p, Envelopes.project)
      await get('GET …/commits', `${p}/commits`, Envelopes.commits)
      const versions = await get('GET …/versions', `${p}/versions`, Envelopes.versions)
      versionId = firstId(versions.body, 'versions')
      if (versionId) {
        await get('GET …/versions/:id', `${p}/versions/${versionId}`, Envelopes.version, { optional: true })
      }
      await get('GET …/documents/stats', `${p}/documents/stats`, Envelopes.docStats)
      const documents = await get('GET …/documents', `${p}/documents`, Envelopes.documents)
      await get('GET …/members', `${p}/members`, Envelopes.members)
      await get('GET …/members/pending', `${p}/members/pending`, Envelopes.membersPending)
      const cur = await get('GET …/jobs/current', `${p}/jobs/current`, Envelopes.jobCurrent)

      const curJobId = pickStr(cur.body, 'job', 'id')
      if (curJobId) {
        await get('GET …/jobs/:id', `${p}/jobs/${curJobId}`, Envelopes.job, { optional: true })
        await get('GET …/jobs/:id/functions', `${p}/jobs/${curJobId}/functions`, Envelopes.jobFunctions, { optional: true })
      }

      docId = firstId(documents.body, 'documents')
      if (docId) {
        const detail = await get('GET …/documents/:id', `${p}/documents/${docId}`, Envelopes.document)
        sectionKey = pickStr(detail.body, 'document', 'sections', 0, 'key')
        const render = await get('GET …/documents/:id/render', `${p}/documents/${docId}/render`, Envelopes.documentRender)
        sampleAssetRef = findFirstImageUrl(render.body)
        await call('GET …/documents/:id/download', 'GET', `${p}/documents/${docId}/download`, { binary: true, optional: true })
      }

      if (versionId) {
        const cmp = `current=${versionId}&baseline=`
        await get('GET …/compare', `${p}/compare?${cmp}`, Envelopes.compareSummary, { optional: true })
        await get('GET …/compare/documents', `${p}/compare/documents?${cmp}`, Envelopes.compareDocuments, { optional: true })
        if (docId) {
          await get('GET …/compare/documents/:id', `${p}/compare/documents/${docId}?${cmp}`, Envelopes.compareDetail, { optional: true })
        }
      }
    }

    /* ── writes: LOCAL MOCK ONLY (never a real API) ── */
    if (MUTATE) {
      // self-owned lifecycle: create → update → delete
      const created = await call('POST /projects', 'POST', '/projects', {
        schema: Envelopes.project,
        body: {
          name: 'API Test Probe', client: 'API Test', compliance_standard: 'ISO_26262',
          repo_url: 'https://example.com/api-test/probe.git', default_branch: 'main',
        },
      })
      const newPid = pickStr(created.body, 'project', 'id')
      if (newPid) {
        const np = `/projects/${newPid}`
        await call('PATCH /projects/:id', 'PATCH', np, {
          schema: Envelopes.project, body: { name: 'API Test Probe (renamed)' },
        })
        await call('POST …/access-requests', 'POST', `${np}/access-requests`, { optional: true })

        const v = await call('POST …/versions', 'POST', `${np}/versions`, {
          schema: Envelopes.version, optional: true,
          body: { tag: 'v0.0.1-apitest', commit_sha: '0000000', branch: 'main', description: 'probe' },
        })
        const newVid = pickStr(v.body, 'version', 'id')
        if (newVid) {
          await call('PATCH …/versions/:id', 'PATCH', `${np}/versions/${newVid}`, {
            schema: Envelopes.version, body: { description: 'updated' }, optional: true,
          })
          await call('DELETE …/versions/:id', 'DELETE', `${np}/versions/${newVid}`, { optional: true })
        }

        await call('POST …/members/invite', 'POST', `${np}/members/invite`, {
          body: { email: 'api.test.probe@aspice.dev', role: 'developer' }, optional: true,
        })
        const pend = await call('GET …/members/pending', 'GET', `${np}/members/pending`, {
          schema: Envelopes.membersPending, optional: true,
        })
        const inviteId = firstId(pend.body, 'pending')
        if (inviteId) {
          await call('DELETE …/members/pending/:id', 'DELETE', `${np}/members/pending/${inviteId}`, { optional: true })
        }

        await call('DELETE /projects/:id', 'DELETE', np) // cleanup — must succeed
      }

      // seed-affecting writes (safe: local mock resets on restart)
      if (projectId) {
        const p = `/projects/${projectId}`
        if (docId) {
          await call('POST …/documents/:id/assignments/self', 'POST', `${p}/documents/${docId}/assignments/self`, { optional: true })
          await call('POST …/documents/:id/assignments', 'POST', `${p}/documents/${docId}/assignments`, { body: { user_ids: [] }, optional: true })
          await call('PATCH …/documents/:id', 'PATCH', `${p}/documents/${docId}`, { body: { status: 'in_review' }, optional: true })
          if (sectionKey) {
            await call('PATCH …/documents/:id/sections/:key', 'PATCH', `${p}/documents/${docId}/sections/${sectionKey}`, { body: { review_state: 'accepted' }, optional: true })
          }
          await call('POST …/documents/:id/submit-review', 'POST', `${p}/documents/${docId}/submit-review`, { optional: true })
          await call('POST …/documents/:id/request-changes', 'POST', `${p}/documents/${docId}/request-changes`, { optional: true })
          await call('POST …/documents/:id/approve', 'POST', `${p}/documents/${docId}/approve`, { optional: true })
        }
        if (versionId) {
          await call('POST …/documents/approve-all', 'POST', `${p}/documents/approve-all`, { schema: Envelopes.approvedCount, body: { version_id: versionId }, optional: true })
          await call('POST …/documents/export-all', 'POST', `${p}/documents/export-all`, { schema: Envelopes.downloadUrl, body: { version_id: versionId }, optional: true })
        }
        const notifs = await call('GET /notifications', 'GET', '/notifications', { schema: Envelopes.notifications })
        const nId = firstId(notifs.body, 'notifications')
        if (nId) await call('PATCH /notifications/:id/read', 'PATCH', `/notifications/${nId}/read`, { optional: true })
        await call('POST /notifications/read-all', 'POST', '/notifications/read-all', { optional: true })
      }
    }

    /* ── heavy / external (local mock only; opt-in: API_TEST_HEAVY=1) ── */
    if (HEAVY && projectId) {
      const repo = 'https://github.com/githubtraining/hellogitworld.git'
      await call('POST /repositories/test-connection', 'POST', '/repositories/test-connection', { schema: Envelopes.repoTest, body: { repo_url: repo }, optional: true })
      await call('GET /repositories/browse', 'GET', `/repositories/browse?repo_url=${encodeURIComponent(repo)}`, { schema: Envelopes.repoEntries, optional: true })
      const started = await call('POST …/jobs', 'POST', `/projects/${projectId}/jobs`, { schema: Envelopes.jobStart, body: { commit_sha: 'HEAD' }, optional: true })
      const jid = pickStr(started.body, 'job_id')
      if (jid) {
        await call('POST …/jobs/:id/cancel', 'POST', `/projects/${projectId}/jobs/${jid}/cancel`, { schema: Envelopes.job, optional: true })
        await call('POST …/jobs/:id/reexport', 'POST', `/projects/${projectId}/jobs/${jid}/reexport`, { optional: true })
      }
    }

    /* ── auth: signout last (no-op server-side; local only) ── */
    if (MUTATE) await call('POST /auth/signout', 'POST', '/auth/signout', { optional: true })

    /* ── assert: no hard mismatches ── */
    const failures = rows.filter(
      (r) =>
        (r.result && !r.result.ok) ||
        (typeof r.note === 'string' && (r.note.startsWith('HTTP') || r.note.startsWith('network'))),
    )
    const detail = failures.map((r) => {
      const probs = r.result?.problems.map((p) => `${p.path}: ${p.message}`).join('; ')
      return `${r.name} [${String(r.status)}]${probs ? ` — ${probs}` : r.note ? ` — ${r.note}` : ''}`
    })
    expect(detail, 'API response mismatches (see the printed report above)').toEqual([])
  })

  // The two routes a browser must reach WITHOUT an Authorization header (an
  // <img>/EventSource can't send one). A 404 for the probe ids is fine — the
  // contract is only that they're not auth-gated. See INTEGRATION_NOTES.
  it('job-events SSE route is not Bearer-gated', async (ctx) => {
    if (!serverUp) return ctx.skip()
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 5000)
    try {
      const res = await fetch(`${BASE}/projects/probe/jobs/probe/events`, { signal: controller.signal })
      expect([401, 403]).not.toContain(res.status)
    } finally {
      clearTimeout(timer)
      controller.abort()
    }
  })

  it('document asset route is not Bearer-gated', async (ctx) => {
    if (!serverUp) return ctx.skip()
    const res = await fetch(resolveRef('projects/probe/documents/probe/assets/probe.png', BASE))
    expect([401, 403]).not.toContain(res.status)
  })

  // A relative `image_url` from the render payload must resolve to a tokenless,
  // image-serving GET (an <img> sends no Authorization).
  it('a real diagram asset loads tokenless as an image', async (ctx) => {
    if (!serverUp || !sampleAssetRef) return ctx.skip()
    const res = await fetch(resolveRef(sampleAssetRef, BASE))
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type') ?? '').toMatch(/^image\//)
  })
})
