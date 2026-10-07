import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { useLogsPanel } from '../../../store/logsPanel'
import { RunCards } from '../components/RunCards'
import type { AnalysisJob } from '../../../types'

/* Under a running card: the documents as they are made (a component opens once it has them),
   what the run was asked for, what the code holds so far with the LLM's trouble -- and, for a
   superuser, the run's newest lines. */

const comp = (component: string, state: string, documents: object[] = []) => ({
  component, layer: component.split('.')[0], name: component.split('.')[1], state, in_model: true,
  layer_parsed: true, group: null, error: null, documents,
})
const job = {
  id: 'job1', status: 'running', versionId: 'ver9', versionTag: 'v1.2.0', shortSha: 'abc1234', branch: 'main',
  mode: 'auto', startedAt: new Date(Date.now() - 600_000).toISOString(), currentActivity: 'Deriving…',
} as unknown as AnalysisJob

function setup(superuser: boolean, facts: object) {
  useAuthStore.setState({ user: { id: 'u1', name: 'Admin', email: 'admin@company.com', initials: 'AD', isSuperuser: superuser } })
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/versions/ver9/components`, () => HttpResponse.json({
      version_id: 'ver9',
      components: [comp('Layer1.Lib', 'generated', [{ id: 'd1', process: 'SWE.3', status: 'in_review' }, { id: 'd2', process: 'SWE.4', status: 'in_review' }]),
        comp('Layer2.Gpio', 'generating'), comp('Layer1.Util', 'not_requested'), comp('Layer2.Uart', 'not_requested')],
      counts: { generated: 1, generating: 1, not_requested: 2 },
      run: { command: 'generate', alive: true, stopped: false, outcome: 'running', host: 'srv', started_at: null,
        finished_at: null, stage: 'LLM-description', done: 12, total: 38, stage_started_at: null, progress_at: null },
      job: { id: 'job1', mode: 'auto', status: 'running' }, resume_action: 'busy',
    })),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver9/run-facts`, () => HttpResponse.json({ version_id: 'ver9', ...facts })),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json({ versions: [{
      id: 'ver9', tag: 'v1.2.0', commit_sha: 'abc1234', branch: 'main', description: '', status: 'draft', docs_count: 0,
      created_by: 'u1', created_at: '2026-10-06T09:00:00+00:00',
      run: { made_by: 'web', scope: { type: 'component', names: ['Layer1.Lib', 'Layer2.Gpio'] }, doc_type: 'all', model_only: false },
    }] })),
    http.get(`${API_BASE_URL}/admin/logs`, () => HttpResponse.json({ records: [
      { seq: 7, ts: '2026-10-07T10:15:03.420+05:30', level: 'WARNING', source: 'engine', logger: 'llm_client',
        message: 'LLM HTTP 503 (attempt 1/2)', pid: 1, project: 'p1', version: 'ver9' },
    ], cursor: 7, lines: 3, level: 'INFO' })),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/projects/p1/overview']}>
        <Routes>
          <Route path="/projects/p1/overview" element={<RunCards projectId="p1" job={job} />} />
          <Route path="/projects/p1/documents/:docId" element={<p>document page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

const FACTS = {
  model: { functions: 1284, globals: 312, units: 41, components: 25 },
  llm: { failed_calls: 1, retries: 2, last_failure: { ts: '2026-10-07T10:15:03+05:30', message: 'LLM failed after 2 attempt(s): 503' } },
  parse: { warnings: 3 },
}

describe('Run cards', { timeout: 20_000 }, () => {
  afterEach(() => { useAuthStore.setState({ user: null }); useLogsPanel.setState({ open: false, scope: { kind: 'all' } }) })

  it('lists the documents as they are made, and one opens once it exists', async () => {
    const user = setup(false, FACTS)
    const docs = await screen.findByRole('region', { name: 'Documents' })
    await within(docs).findByText('1 of 2 ready')
    expect(within(docs).getByText('Gpio')).toBeInTheDocument()
    expect(within(docs).queryByText('Util')).not.toBeInTheDocument()       // not asked for
    await user.click(within(docs).getByRole('button', { name: 'SWE.3' }))
    expect(await screen.findByText('document page')).toBeInTheDocument()
  })

  it('says what was asked for, and what the code holds so far with the LLM\'s trouble', async () => {
    setup(false, FACTS)
    const run = await screen.findByRole('region', { name: 'This run' })
    await waitFor(() => expect(run).toHaveTextContent('Components: Layer1.Lib, Layer2.Gpio · 2 of 4 components'))
    expect(run).toHaveTextContent('abc1234 on main')
    expect(run).toHaveTextContent('SWE.3 and SWE.4')
    const found = screen.getByRole('region', { name: 'Found so far' })
    await waitFor(() => expect(found).toHaveTextContent('1,284 functions · 312 globals · 41 units · 25 components'))
    expect(found).toHaveTextContent('3 warnings')
    expect(found).toHaveTextContent('writing descriptions, 12 of 38')
    expect(found).toHaveTextContent('1 call failed · 2 retries')
    expect(found).toHaveTextContent('LLM failed after 2 attempt(s): 503')
  })

  it('an LLM with no trouble reads Answering; code not counted yet says when it will be', async () => {
    setup(false, { model: null, llm: { failed_calls: 0, retries: 0, last_failure: null }, parse: { warnings: 0 } })
    const found = await screen.findByRole('region', { name: 'Found so far' })
    await waitFor(() => expect(found).toHaveTextContent('Answering'))
    expect(found).toHaveTextContent('Counted once the parse is stored')
    expect(found).toHaveTextContent('No warnings')
  })

  it('a superuser gets the newest lines, and Open logs opens the panel on the run', async () => {
    const user = setup(true, FACTS)
    await screen.findByText('LLM HTTP 503 (attempt 1/2)')
    await user.click(screen.getByRole('button', { name: /Open logs/ }))
    expect(useLogsPanel.getState()).toMatchObject({ open: true, scope: { kind: 'version', project: 'p1', version: 'ver9' } })
  })

  it('anyone else does not', async () => {
    setup(false, FACTS)
    await screen.findByRole('region', { name: 'Documents' })
    expect(screen.queryByText('Latest lines')).not.toBeInTheDocument()
  })
})
