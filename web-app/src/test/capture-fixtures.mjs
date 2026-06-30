// Capture raw API responses from a running backend into src/test/fixtures/.
// These feed the MSW handlers (offline UI tests) and keep the zod schemas honest.
//
//   1. start the mock:  cd mock-api && python run.py
//   2. from web-app/:    npm run test:capture
//
// Re-run after a backend change to refresh the snapshots. Plain ESM — no build.
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = (process.env.API_TEST_URL ?? process.env.VITE_API_URL ?? 'http://localhost:8000/api/v1').replace(/\/+$/, '')
const EMAIL = process.env.API_TEST_EMAIL ?? 'alice@aspice.dev'
const PASSWORD = process.env.API_TEST_PASSWORD ?? 'secret'
// Raw snapshots land in fixtures/captured/ so they never clobber the curated,
// trimmed fixtures the unit tests assert against (e.g. fixtures/projects.json).
const OUT = join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'captured')

let token = ''
async function get(path) {
  const res = await fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json()
}
async function save(name, data) {
  await writeFile(join(OUT, `${name}.json`), JSON.stringify(data, null, 2) + '\n')
  console.log(`  saved fixtures/${name}.json`)
}

async function main() {
  await mkdir(OUT, { recursive: true })
  const signin = await fetch(`${BASE}/auth/signin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  })
  if (!signin.ok) throw new Error(`sign-in failed (${signin.status}) — check creds / server`)
  token = (await signin.json()).access_token

  const projects = await get('/projects')
  await save('projects', projects)
  await save('notifications', await get('/notifications'))

  const id = projects.projects?.[0]?.id
  if (id) {
    await save('project', await get(`/projects/${id}`))
    await save('commits', await get(`/projects/${id}/commits`))
    const versions = await get(`/projects/${id}/versions`)
    await save('versions', versions)
    await save('documents', await get(`/projects/${id}/documents`))
    await save('members', await get(`/projects/${id}/members`))
    const docs = await get(`/projects/${id}/documents`)
    const docId = docs.documents?.[0]?.id
    if (docId) {
      await save('document', await get(`/projects/${id}/documents/${docId}`))
      await save('documentRender', await get(`/projects/${id}/documents/${docId}/render`))
    }
  }
  console.log(`\nDone — captured from ${BASE}`)
}

main().catch((e) => {
  console.error(`\ncapture failed: ${e.message}`)
  console.error('  is the backend running?  cd mock-api && python run.py')
  process.exit(1)
})
