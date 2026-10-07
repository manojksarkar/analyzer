import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { useLogsPanel } from '../../../store/logsPanel'
import { LogsButton } from '../LogsButton'
import { LogsPanel } from '../LogsPanel'
import { useLogsTakeThePage } from '../useLogRuns'

/* The Logs panel: docked on the page, opened by the top bar's button on the project's run at work,
   one line per log line, the Showing button switching what it shows, Esc closing it -- and nothing
   at all for anyone but a superuser. */

class FakeEventSource {
  addEventListener() {}
  close() {}
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
}

const records = [
  { seq: 1, ts: '2026-10-06T10:15:03.420+05:30', level: 'INFO', source: 'engine', logger: 'parser',
    message: 'Parsed 214 of 214 files', pid: 7832, project: 'p1', version: 'ver9', job: 'job1', run: 'generate', step: 'Parse' },
  { seq: 2, ts: '2026-10-06T10:15:04.100+05:30', level: 'WARNING', source: 'engine', logger: 'llm_client',
    message: 'LLM HTTP 503 (attempt 1/2)', pid: 7832, project: 'p1', version: 'ver9', job: 'job1', run: 'generate', step: 'Derive' },
]

function Page() {
  const full = useLogsTakeThePage()
  return <><LogsButton /><p>{full ? 'page hidden' : 'the page'}</p><LogsPanel projectId="p1" /></>
}

function setup(superuser = true) {
  useAuthStore.setState({ user: { id: 'u1', name: 'Admin', email: 'admin@company.com', initials: 'AD', isSuperuser: superuser } })
  const tails: URLSearchParams[] = []
  server.use(
    http.get(`${API_BASE_URL}/admin/logs`, ({ request }) => {
      tails.push(new URL(request.url).searchParams)
      return HttpResponse.json({ records, cursor: 2, lines: 500, level: 'INFO' })
    }),
    http.post(`${API_BASE_URL}/admin/logs/ticket`, () => HttpResponse.json({ ticket: 't1', expiresIn: 60 })),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json({ versions: [{
      id: 'ver9', tag: 'v1.2.0', commit_sha: 'abc1234', branch: 'main', description: '', status: 'draft',
      docs_count: 0, created_by: 'u1', created_at: '2026-10-06T09:00:00+00:00' }] })),
    http.get(`${API_BASE_URL}/projects/p1/runs`, () => HttpResponse.json({ runs: [
      { version_id: 'ver9', version_tag: 'v1.2.0', command: 'generate', pid: 7832, host: 'srv', outcome: 'running',
        log_path: null, started_at: new Date(Date.now() - 3600_000).toISOString(), finished_at: null, stage: 'LLM-description',
        done: 12, total: 38, stage_started_at: null, progress_at: new Date(Date.now() - 30_000).toISOString(), alive: true, stopped: false },
      { version_id: 'ver7', version_tag: 'v1.1.0', command: 'export', pid: 6610, host: 'srv', outcome: 'running',
        log_path: null, started_at: '2026-10-05T16:00:00+00:00', finished_at: null, stage: 'flowcharts', done: 41,
        total: 112, stage_started_at: null, progress_at: new Date(Date.now() - 17 * 3600_000).toISOString(), alive: true, stopped: false },
    ] })),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/projects/p1/overview']}>
        <Routes><Route path="/projects/:projectId/overview" element={<Page />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { tails, user: userEvent.setup() }
}

describe('Logs panel', { timeout: 20_000 }, () => {
  beforeEach(() => vi.stubGlobal('EventSource', FakeEventSource))
  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.setState({ user: null })
    useLogsPanel.setState({ open: false, maximized: false, scope: { kind: 'all' } })
  })

  it('the top bar button opens it on the project\'s run at work, below the page', async () => {
    const { tails, user } = setup()
    const button = await screen.findByRole('button', { name: 'Logs' })
    await waitFor(() => expect(button.querySelector('.bg-warn')).not.toBeNull())   // a run is quiet: the dot
    await user.click(button)
    const panel = await screen.findByRole('region', { name: 'Logs' })
    expect(screen.getByText('the page')).toBeInTheDocument()
    await within(panel).findByText('LLM HTTP 503 (attempt 1/2)')
    expect(within(panel).getByText(/Run:/).parentElement).toHaveTextContent('Brake Control Unit · v1.2.0 · Generate')
    expect(tails.at(-1)?.get('version')).toBe('ver9')
    expect(within(panel).getByText('Derive', { selector: 'div' })).toBeInTheDocument()   // one run: steps as dividers
  })

  it('Showing switches to every project; Esc closes it', async () => {
    const { tails, user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Logs' }))
    const panel = await screen.findByRole('region', { name: 'Logs' })
    await user.click(within(panel).getByText(/Run:/).closest('button')!)
    const list = within(panel).getByRole('listbox', { name: 'Show' })
    expect(within(list).getByText(/Quiet for 17 h/)).toBeInTheDocument()
    await user.click(within(list).getByText('Every project, and the API'))
    await waitFor(() => expect(tails.at(-1)?.get('version')).toBeNull())
    expect(tails.at(-1)?.get('project')).toBeNull()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Logs' })).not.toBeInTheDocument())
  })

  it('at full height it takes the page\'s place', async () => {
    const { user } = setup()
    await user.click(await screen.findByRole('button', { name: 'Logs' }))
    await user.click(await screen.findByRole('button', { name: 'Full height' }))
    expect(screen.getByText('page hidden')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Back to its size' }))
    expect(screen.getByText('the page')).toBeInTheDocument()
  })

  it('anyone else has no button and no panel', async () => {
    setup(false)
    useLogsPanel.setState({ open: true })
    expect(await screen.findByText('the page')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Logs' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Logs' })).not.toBeInTheDocument()
  })
})
