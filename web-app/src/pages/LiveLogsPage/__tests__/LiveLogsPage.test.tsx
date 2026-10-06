import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { SuperuserRoute } from '../../../routes/SuperuserRoute'
import { UserMenu } from '../../../components/shell/UserMenu'
import { LiveLogsPage } from '..'

/* The Live logs page: lines by name, not id; a click on a name narrows the page (the address
   changes); the Runs list shows a quiet run in amber; a traceback folds; only superusers get in. */

class FakeEventSource {
  addEventListener() {}
  close() {}
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
}

const TRACE = ['Flowchart failed', 'Traceback (most recent call last):', '  File "a.py", line 1', '    x()',
  '  File "b.py", line 2', '    y()', 'CfgError: no cursor'].join('\n')
const records = [
  { seq: 1, ts: '2026-10-06T10:15:03.420+05:30', level: 'INFO', source: 'server', logger: 'api.request',
    message: 'POST /api/v1/projects/p1/jobs -> 202 (41 ms)', pid: 4120, project: 'p1', job: 'job1' },
  { seq: 2, ts: '2026-10-06T10:15:04.100+05:30', level: 'WARNING', source: 'engine', logger: 'llm_client',
    message: 'LLM HTTP 503 (attempt 1/2)', pid: 7832, project: 'p1', version: 'ver9', job: 'job1', run: 'generate', step: 'Derive' },
  { seq: 3, ts: '2026-10-06T10:15:05.000+05:30', level: 'ERROR', source: 'engine', logger: 'flowchart_engine',
    message: TRACE, pid: 7832, project: 'p1', version: 'ver9', job: 'job1', run: 'generate', step: 'Views' },
]

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function setup(entry = '/admin/logs', superuser = true) {
  useAuthStore.setState({ user: { id: 'u1', name: 'Admin', email: 'admin@company.com', initials: 'AD', isSuperuser: superuser } })
  const tails: URLSearchParams[] = []
  server.use(
    http.get(`${API_BASE_URL}/admin/logs`, ({ request }) => {
      tails.push(new URL(request.url).searchParams)
      return HttpResponse.json({ records, cursor: 3, lines: 500, level: 'INFO' })
    }),
    http.post(`${API_BASE_URL}/admin/logs/ticket`, () => HttpResponse.json({ ticket: 't1', expiresIn: 60 })),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json({ versions: [{
      id: 'ver9', tag: 'v1.2.0', commit_sha: 'abc1234', branch: 'main', description: '', status: 'draft',
      docs_count: 0, created_by: 'u1', created_at: '2026-10-06T09:00:00+00:00' }] })),
    http.get(`${API_BASE_URL}/projects/p1/runs`, () => HttpResponse.json({ runs: [{
      version_id: 'ver9', version_tag: 'v1.2.0', command: 'generate', pid: 7832, host: 'srv', outcome: 'running',
      log_path: null, started_at: '2026-10-05T16:00:00+00:00', finished_at: null, stage: 'LLM-global', done: 268,
      total: 268, stage_started_at: null, progress_at: '2026-10-05T17:00:00+00:00', alive: true, stopped: false }] })),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/admin/logs" element={<SuperuserRoute><LiveLogsPage /><Where /></SuperuserRoute>} />
          <Route path="/projects" element={<><p>Projects page</p><UserMenu /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { tails, user: userEvent.setup() }
}

describe('Live logs page', { timeout: 20_000 }, () => {
  beforeEach(() => vi.stubGlobal('EventSource', FakeEventSource))
  afterEach(() => { vi.unstubAllGlobals(); useAuthStore.setState({ user: null }) })

  it('shows the lines by name, and a click on a run narrows the page to it', async () => {
    const { tails, user } = setup()
    const warn = await screen.findByText('LLM HTTP 503 (attempt 1/2)')
    const row = warn.closest('div.grid') as HTMLElement
    expect(within(row).getByText('WARNING')).toBeInTheDocument()
    expect(within(row).getByText('10:15:04.100')).toHaveAttribute('title', '2026-10-06 10:15:04.100+05:30')
    await waitFor(() => expect(within(row).getByRole('button', { name: 'Brake Control Unit' })).toBeInTheDocument())
    await waitFor(() => expect(within(row).getByRole('button', { name: 'v1.2.0' })).toBeInTheDocument())
    await user.click(within(row).getByRole('button', { name: 'Generate' }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/admin/logs?project=p1&version=ver9&job=job1'))
    await waitFor(() => expect(tails.at(-1)?.get('job')).toBe('job1'))
    expect(tails.at(-1)?.get('version')).toBeNull()       // a run by its job alone
    // One run: its steps become dividers.
    expect(await screen.findByText('Views', { selector: 'div' })).toBeInTheDocument()
  })

  it('folds a traceback past five lines', async () => {
    const { user } = setup()
    expect(await screen.findByText('Show 2 more lines')).toBeInTheDocument()
    expect(screen.queryByText(/CfgError: no cursor/)).not.toBeInTheDocument()
    await user.click(screen.getByText('Show 2 more lines'))
    expect(screen.getByText(/CfgError: no cursor/)).toBeInTheDocument()
  })

  it('a run with no progress for 10 minutes reads quiet in Runs', async () => {
    setup()
    const runs = await screen.findByRole('complementary', { name: 'Runs' })
    await waitFor(() => expect(within(runs).getByText(/Quiet for \d+ (h|d)/)).toBeInTheDocument())
    expect(within(runs).getByText('describing globals, 268 of 268')).toBeInTheDocument()
  })

  it('a search keeps the matching loaded lines', async () => {
    const { user } = setup()
    await screen.findByText('LLM HTTP 503 (attempt 1/2)')
    await user.type(screen.getByRole('searchbox', { name: 'Search the loaded lines' }), 'upstream-none')
    expect(await screen.findByText('No lines match. New ones appear here as they arrive.')).toBeInTheDocument()
  })

  it('anyone else lands on Projects, and their menu has no Live logs', async () => {
    const { user } = setup('/admin/logs', false)
    expect(await screen.findByText('Projects page')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /User menu/ }))
    expect(await screen.findByText('Sign out')).toBeInTheDocument()
    expect(screen.queryByText('Live logs')).not.toBeInTheDocument()
  })

  it('a superuser\'s menu leads to Live logs', async () => {
    const { user } = setup('/projects')
    await user.click(await screen.findByRole('button', { name: /User menu/ }))
    await user.click(await screen.findByText('Live logs'))
    expect(await screen.findByRole('heading', { name: 'Live logs' })).toBeInTheDocument()
  })
})
