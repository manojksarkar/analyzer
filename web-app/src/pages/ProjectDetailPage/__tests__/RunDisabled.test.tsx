import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import members from '../../../test/fixtures/captured/members.json'
import versions from '../../../test/fixtures/captured/versions.json'
import { ProjectDetailPage } from '..'

/* A developer cannot run analysis: the Run / Re-run buttons are disabled, and say why on hover. */

function setup(status: string, role: string, withVersions: boolean) {
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () =>
      HttpResponse.json({ project: { ...project.project, status, my_role: role } })),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () =>
      HttpResponse.json(withVersions ? versions : { versions: [] })),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/runs`, () => HttpResponse.json({ runs: [] })),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: [], pagination: { page: 1, per_page: 100, total: 0 } })),
    http.get(`${API_BASE_URL}/projects/p1/review-events`, () => HttpResponse.json({ events: [] })),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
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
}

const WHY = 'Only a project admin can run analysis.'

// The whole page renders: its first render is slow on a loaded machine.
describe('Overview: Run disabled for a developer', { timeout: 30_000 }, () => {
  it('the empty state says why Run is disabled', async () => {
    setup('not_run', 'developer', false)
    const run = await screen.findByRole('button', { name: /RUN ANALYSIS/ })
    expect(run).toBeDisabled()
    expect(run).toHaveAttribute('title', WHY)
  })

  it('the stale banner says why Re-run is disabled', async () => {
    setup('stale', 'developer', true)
    const rerun = await screen.findByRole('button', { name: /Re-run/ })
    expect(rerun).toBeDisabled()
    expect(rerun).toHaveAttribute('title', WHY)
  })

  it('an admin gets no such title', async () => {
    setup('not_run', 'admin', false)
    const runs = await screen.findAllByRole('button', { name: /RUN ANALYSIS/ })
    for (const run of runs) {
      expect(run).toBeEnabled()
      expect(run).not.toHaveAttribute('title')
    }
  })
})
