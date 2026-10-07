import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { useRunModal } from '../../../store/runModal'
import { useToastStore } from '../../ui/Toast'
import project from '../../../test/fixtures/captured/project.json'
import versions from '../../../test/fixtures/captured/versions.json'
import commits from '../../../test/fixtures/captured/commits.json'
import { AttentionChip } from '../AttentionChip'

/* At the office the Overview stacked a banner per thing: a failed run, one box per other run, the
   warnings. Now one chip beside the version opens a drawer with each of them; a failed analysis
   that a later run of its version made good is not among them. */

const failedJob = {
  id: 'jobF', status: 'failed', phase: 1, phase_pct: 0, current_activity: '', activity_detail: '', elapsed_seconds: 60,
  eta_seconds: null, phases: [], commit_sha: 'abc1234', branch: 'main', version_id: 'ver9', version_tag: 'v2.0.0',
  mode: 'auto', started_at: '2026-10-07T09:00:00Z', completed_at: '2026-10-07T09:05:00Z',
  error_message: 'Checkout failed: the commit is not on the remote',
}
const run = (over: Record<string, unknown>) => ({
  version_id: 'ver1', version_tag: 'v1.0.0', command: 'export', alive: true, stopped: false, outcome: 'running',
  host: null, started_at: '2026-10-07T10:00:00Z', finished_at: null, stage: 'parser', done: 1, total: 4,
  stage_started_at: null, progress_at: null, ...over,
})
const noComponents = (vid: string, runOf: object | null = null, job: object | null = null) => HttpResponse.json({
  version_id: vid, components: [], counts: {}, run: runOf, job, resume_action: 'nothing',
})

function mount({ job = failedJob, runs = [] as object[], ver9Run = null as object | null, warnings = [] as string[] } = {}) {
  useAuthStore.setState({ user: { id: 'u1', name: 'Admin', email: 'admin@company.com', initials: 'AD', isSuperuser: false } })
  const vs = { versions: versions.versions.map((v, i) => (i === 0 ? { ...v, warnings } : v)) }
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(vs)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job })),
    http.get(`${API_BASE_URL}/projects/p1/runs`, () => HttpResponse.json({ runs })),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver3/components`, () => noComponents('ver3')),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver9/components`, () => noComponents('ver9', ver9Run)),
  )
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/projects/p1/documents']}>
        <Routes>
          <Route path="/projects/:projectId/documents" element={<AttentionChip />} />
          <Route path="/projects/:projectId/overview" element={<p>the overview</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('Needs attention', { timeout: 20_000 }, () => {
  afterEach(() => {
    useAuthStore.setState({ user: null })
    useRunModal.setState({ open: false })
    useToastStore.setState({ toasts: [] })
    try { sessionStorage.clear(); localStorage.clear() } catch { /* none */ }
  })

  it('one chip for a failed run, a run cut short, one at work and the warnings; the drawer holds each', async () => {
    const user = mount({
      runs: [run({}), run({ version_id: 'ver2', version_tag: 'v1.1.0', alive: false, stopped: true })],
      warnings: ['Component Layer1.Math: path src/math not in the checkout'],
    })
    const chip = await screen.findByRole('button', { name: /Run failed · \+3/ })
    await user.click(chip)
    const drawer = await screen.findByRole('dialog', { name: 'Needs attention' })
    expect(within(drawer).getByText(/Last analysis failed — v2\.0\.0/)).toBeInTheDocument()
    expect(within(drawer).getByText(/Running export into v1\.0\.0/)).toBeInTheDocument()
    expect(within(drawer).getByText(/into v1\.1\.0 stopped/)).toBeInTheDocument()
    expect(within(drawer).getByText(/reported 1 warning/)).toBeInTheDocument()
  })

  it("a failed run's Re-run goes to the Overview with the Run dialog open", async () => {
    const user = mount()
    await user.click(await screen.findByRole('button', { name: /Run failed/ }))
    await user.click(within(await screen.findByRole('dialog')).getByRole('button', { name: /Re-run/ }))
    expect(await screen.findByText('the overview')).toBeInTheDocument()
    expect(useRunModal.getState().open).toBe(true)
  })

  it('a failure a later run of its version made good is not said again (task: the banner stayed)', async () => {
    mount({ ver9Run: run({ version_id: 'ver9', command: 'resume', alive: false, outcome: 'complete', started_at: '2026-10-07T10:00:00Z' }) })
    await waitFor(() => expect(screen.queryByRole('button', { name: /Run failed/ })).not.toBeInTheDocument())
    // nothing else needs attention: no chip at all
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('a toast says a run failed, once', async () => {
    mount()
    await screen.findByRole('button', { name: /Run failed/ })
    await waitFor(() => expect(useToastStore.getState().toasts.map((t) => t.title)).toContain('Analysis failed — v2.0.0'))
  })

  it('nothing to say: no chip', async () => {
    mount({ job: { ...failedJob, status: 'complete', error_message: null } })
    await new Promise((r) => setTimeout(r, 100))
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
