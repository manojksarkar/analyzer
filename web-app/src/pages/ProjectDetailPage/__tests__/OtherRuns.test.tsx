import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { OtherRuns } from '../components/OtherRuns'

/* The Overview showed the web job only: a run started from the command line (`analyzer.py export
   --detach`), or a Components → Generate, was invisible there. GET /projects/{pid}/runs lists every
   run at work or cut short; the Overview shows each one it does not show already. */

const run = (over: Record<string, unknown>) => ({
  version_id: 'ver1', version_tag: 'v1.0.0', command: 'export', alive: true, stopped: false, outcome: 'running',
  host: null, started_at: null, finished_at: null, stage: 'parser', done: 120, total: 216,
  stage_started_at: null, progress_at: null, ...over,
})

function setup(runs: object[], exceptVersionId: string | null = null) {
  server.use(http.get(`${API_BASE_URL}/projects/p1/runs`, () => HttpResponse.json({ runs })))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <OtherRuns projectId="p1" exceptVersionId={exceptVersionId} />
    </QueryClientProvider>,
  )
}

describe('OtherRuns (the Overview)', () => {
  it('a run at work: its command, version and stage progress', async () => {
    setup([run({})])
    expect(await screen.findByText(/Running export into v1\.0\.0/)).toBeInTheDocument()
    expect(screen.getByText(/stage parser 120\/216 \(55%\)/)).toBeInTheDocument()
  })

  it('a run cut short: says so, with the command that resumes it', async () => {
    setup([run({ version_id: 'ver2', version_tag: 'v0.9.0', command: 'generate', alive: false, stopped: true })])
    expect(await screen.findByText(/generate into v0\.9\.0 stopped/)).toBeInTheDocument()
    expect(screen.getByText('python analyzer.py resume --project-id p1 --version-id ver2 --detach')).toBeInTheDocument()
  })

  it('not the web job the Overview shows already', async () => {
    setup([run({ version_id: 'ver9', version_tag: 'v2', command: 'generate' }), run({})], 'ver9')
    expect(await screen.findByText(/Running export into v1\.0\.0/)).toBeInTheDocument()
    expect(screen.queryByText(/into v2/)).toBeNull()
  })
})
