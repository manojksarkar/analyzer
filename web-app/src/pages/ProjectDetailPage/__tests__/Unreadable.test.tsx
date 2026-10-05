import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { ProjectDetailPage } from '..'

/* Smoke test of 2026-10-05: a project the Overview cannot read (not a member: 403; no such
   project: 404) showed "No documents generated yet" and a disabled RUN ANALYSIS, as if it had
   never run. It says why it cannot show the project. */

function setup(status: number, code: string, message: string) {
  const refused = () => HttpResponse.json({ detail: { code, message } }, { status })
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, refused),
    http.get(`${API_BASE_URL}/projects/p1/versions`, refused),
    http.get(`${API_BASE_URL}/projects/p1/commits`, refused),
    http.get(`${API_BASE_URL}/projects/p1/runs`, refused),
    http.get(`${API_BASE_URL}/projects/p1/members`, refused),
    http.get(`${API_BASE_URL}/projects/p1/documents`, refused),
    http.get(`${API_BASE_URL}/projects/p1/review-events`, refused),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, refused),
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

describe('Overview of a project it cannot read', { timeout: 30_000 }, () => {
  it('not a member: says so, not "never run"', async () => {
    setup(403, 'FORBIDDEN', 'Project membership required')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load the project')
    expect(alert).toHaveTextContent('Project membership required')
    expect(screen.queryByText(/No documents generated yet/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /RUN ANALYSIS/ })).not.toBeInTheDocument()
  })

  it('no such project: says so', async () => {
    setup(404, 'NOT_FOUND', 'Project p1 not found')
    expect(await screen.findByRole('alert')).toHaveTextContent('Project p1 not found')
    expect(screen.queryByText(/No documents generated yet/)).not.toBeInTheDocument()
  })
})
