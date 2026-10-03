import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import versions from '../../../test/fixtures/captured/versions.json'
import documents from '../../../test/fixtures/captured/documents.json'
import members from '../../../test/fixtures/captured/members.json'
import { DocumentsPage } from '..'

/* A failed read of the documents (or of the versions, which say what state the page is in) is
   shown as one, with Retry — it looked like "No documents found" / "No documents yet". */

function setup(fail: 'documents' | 'versions') {
  // Every read fails until the server is back (just before Retry).
  const api = { down: true }
  const failWhileDown = (ok: () => Response) => () => api.down
    ? HttpResponse.json({ detail: { code: 'INTERNAL', message: 'Database unavailable' } }, { status: 503 })
    : ok()
  const docs = () => HttpResponse.json({ ...documents, pagination: { page: 1, per_page: 100, total: documents.documents.length } })
  server.use(
    // A developer: no export-readiness read.
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json({ project: { ...project.project, my_role: 'developer' } })),
    http.get(`${API_BASE_URL}/projects/p1/versions`,
      fail === 'versions' ? failWhileDown(() => HttpResponse.json(versions)) : () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API_BASE_URL}/projects/p1/documents`, fail === 'documents' ? failWhileDown(docs) : docs),
    http.get(`${API_BASE_URL}/projects/p1/versions/:vid/components`, ({ params }) =>
      HttpResponse.json({ version_id: params.vid, components: [], counts: {}, run: null })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/documents']}>
        <Routes>
          <Route path="/projects/:projectId/documents" element={<DocumentsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { user: userEvent.setup(), recover: () => { api.down = false } }
}

describe('DocumentsPage: a failed load', { timeout: 30_000 }, () => {
  it.each(['documents', 'versions'] as const)('of the %s shows the error and Retry, then the documents', async (fail) => {
    const { user, recover } = setup(fail)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load the documents')
    expect(alert).toHaveTextContent('Database unavailable')
    expect(screen.queryByText('No documents found')).not.toBeInTheDocument()
    expect(screen.queryByText('No documents yet')).not.toBeInTheDocument()

    recover()
    await user.click(screen.getByRole('button', { name: /Retry/ }))
    expect(await screen.findByText(`Showing ${documents.documents.length} of ${documents.documents.length} documents`)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
