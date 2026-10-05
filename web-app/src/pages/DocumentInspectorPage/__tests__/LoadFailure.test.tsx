import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import versions from '../../../test/fixtures/captured/versions.json'
import members from '../../../test/fixtures/captured/members.json'
import documentRender from '../../../test/fixtures/captured/documentRender.json'
import { DocumentInspectorPage } from '..'

/* The reader: a failed read of the document is shown as one, with Retry; only the API's 404 is
   "Document not found" (every failure used to be). */

function setup(status: number) {
  let reads = 0
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: [], pagination: { page: 1, per_page: 100, total: 0 } })),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc1/render`, () => HttpResponse.json(documentRender)),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc1`, () => {
      reads += 1
      return status === 404
        ? HttpResponse.json({ detail: { code: 'NOT_FOUND', message: 'Document doc1 not found' } }, { status: 404 })
        : HttpResponse.json({ detail: { code: 'INTERNAL', message: 'Database unavailable' } }, { status })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/documents/doc1']}>
        <Routes>
          <Route path="/projects/:projectId/documents/:docId" element={<DocumentInspectorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { reads: () => reads, user: userEvent.setup() }
}

describe('DocumentInspectorPage: a failed load', { timeout: 30_000 }, () => {
  it('shows the error and Retry, which reads the document again', async () => {
    const { reads, user } = setup(503)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load the document')
    expect(alert).toHaveTextContent('Database unavailable')
    expect(screen.queryByText('Document not found')).not.toBeInTheDocument()
    expect(reads()).toBe(1)
    await user.click(screen.getByRole('button', { name: /Retry/ }))
    await waitFor(() => expect(reads()).toBe(2))
  })

  it('a 404 is "Document not found", with no Retry', async () => {
    setup(404)
    expect(await screen.findByText('Document not found')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Retry/ })).not.toBeInTheDocument()
  })
})
