import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import members from '../../../test/fixtures/captured/members.json'
import { ProjectDetailPage } from '..'

/* The Overview's Cancel Job asks first: one click used to stop the run and delete its version. */

const RUNNING_JOB = {
  id: 'job9', status: 'running', phase: 2, phase_pct: 40, current_activity: 'Deriving', activity_detail: '',
  elapsed_seconds: 60, eta_seconds: null,
  phases: [
    { number: 1, name: 'Parse C++', status: 'done', duration_seconds: 10 },
    { number: 2, name: 'Derive Model', status: 'running', duration_seconds: null },
  ],
  commit_sha: 'b2e8d45', branch: 'main', version_id: 'ver9', version_tag: 'v2', mode: 'auto',
  started_at: '2026-10-01T09:00:00Z', completed_at: null, error_message: null,
}

class FakeEventSource {
  addEventListener() {}
  close() {}
  onerror: (() => void) | null = null
}

function setup() {
  const cancelled: string[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json({ versions: [] })),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: [], pagination: { page: 1, per_page: 100, total: 0 } })),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () =>
      HttpResponse.json({ job: cancelled.length ? null : RUNNING_JOB })),
    http.post(`${API_BASE_URL}/projects/p1/jobs/job9/cancel`, () => {
      cancelled.push('job9')
      // The runner was not alive: the draft went with the cancel, so the job names no version.
      return HttpResponse.json({ job: { ...RUNNING_JOB, status: 'cancelled', version_id: null } })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1']}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { cancelled, user: userEvent.setup() }
}

// The whole page renders: its first render is slow on a loaded machine.
describe('Overview: Cancel Job', { timeout: 30_000 }, () => {
  beforeEach(() => vi.stubGlobal('EventSource', FakeEventSource))
  afterEach(() => vi.unstubAllGlobals())

  it('asks before cancelling, and Keep running cancels nothing', async () => {
    const { cancelled, user } = setup()
    await user.click(await screen.findByRole('button', { name: /Cancel Job/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel this generation?' })
    expect(within(dialog).getByText(/this version is removed/)).toBeInTheDocument()
    expect(within(dialog).getByText('Job job9 · version v2')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Keep running' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(cancelled).toEqual([])
  })

  it('cancels once confirmed, and the running card goes', async () => {
    const { cancelled, user } = setup()
    await user.click(await screen.findByRole('button', { name: /Cancel Job/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel this generation?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel generation' }))
    await waitFor(() => expect(cancelled).toEqual(['job9']))
    await waitFor(() => expect(screen.queryByText('Analysis Running')).not.toBeInTheDocument())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
