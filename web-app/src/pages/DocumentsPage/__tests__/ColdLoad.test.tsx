import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { SubbarCtaProvider } from '../../../components/shell/SubbarCta'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import versions from '../../../test/fixtures/captured/versions.json'
import documents from '../../../test/fixtures/captured/documents.json'
import members from '../../../test/fixtures/captured/members.json'
import { DocumentsPage } from '..'

/* #16: on a cold load the page said "No documents yet" (the view state's default) until the
   project was read. #37: its process tabs offered SYS.1, SYS.2, SWE.1 and SWE.2, which nothing
   generates — always empty. */

function setup({ docs = documents.documents, holdProject = false } = {}) {
  let release = () => {}
  const held = new Promise<void>((r) => { release = r })
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, async () => {
      if (holdProject) await held
      return HttpResponse.json(project)
    }),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: docs, pagination: { page: 1, per_page: 100, total: docs.length } })),
    http.get(`${API_BASE_URL}/projects/p1/versions/:vid/components`, ({ params }) =>
      HttpResponse.json({ version_id: params.vid, components: [], counts: {}, run: null })),
    http.get(`${API_BASE_URL}/projects/p1/versions/:vid/export-readiness`, () => HttpResponse.json({
      stale: false, reason: 'up to date', explanation: '', overrideCount: 0, pendingRenders: 0,
      failedRenders: 0, newestOverrideAt: null, oldestDerivationAt: null, reexport: null })),
  )
  const slot = document.createElement('div')
  document.body.appendChild(slot)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <SubbarCtaProvider slot={slot}>
        <MemoryRouter initialEntries={['/projects/p1/documents']}>
          <Routes>
            <Route path="/projects/:projectId/documents" element={<DocumentsPage />} />
          </Routes>
        </MemoryRouter>
      </SubbarCtaProvider>
    </QueryClientProvider>,
  )
  return { release }
}

const tabs = () => within(screen.getByRole('tablist', { name: 'Filter by process' }))
  .getAllByRole('tab').map((t) => t.textContent)

describe('DocumentsPage: first load and process tabs', { timeout: 30_000 }, () => {
  it('shows the loading state, not "No documents yet", until the project is read', async () => {
    const { release } = setup({ holdProject: true })
    expect(await screen.findByLabelText('Loading documents')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 200))
    expect(screen.queryByText('No documents yet')).not.toBeInTheDocument()
    expect(screen.queryByText('No documents found')).not.toBeInTheDocument()
    release()
    expect(await screen.findByRole('tablist', { name: 'Filter by process' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Loading documents')).not.toBeInTheDocument()
  })

  it('offers the processes the app makes, and no empty placeholder tab', async () => {
    setup({ docs: documents.documents.filter((d) => d.process === 'SWE.3') })
    await screen.findByRole('tablist', { name: 'Filter by process' })
    await waitFor(() => expect(tabs()).toEqual(['All', 'SWE.3', 'SWE.4']))
  })

  it('a process the app does not make is offered when a document of it exists', async () => {
    setup()
    await screen.findByRole('tablist', { name: 'Filter by process' })
    await waitFor(() => expect(tabs()).toEqual(['All', 'SYS.2', 'SWE.1', 'SWE.2', 'SWE.3', 'SWE.4']))
  })
})
