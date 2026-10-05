import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
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

/* Download serves the stored Word file as it is (REVIEW_UPDATE_API_SPEC §14): after corrections
   and before a re-export it is the previous one. The Documents page says so — for every role, as
   the reader does: on a row's Download when R9 names its component (`staleComponents`), on
   Download All when the version is behind at all. */

function setup(stale: boolean, staleComponents?: string[]) {
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json({ project: { ...project.project, my_role: 'developer' } })),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ ...documents, pagination: { page: 1, per_page: 100, total: documents.documents.length } })),
    http.get(`${API_BASE_URL}/projects/p1/versions/:vid/components`, ({ params }) =>
      HttpResponse.json({ version_id: params.vid, components: [], counts: {}, run: null })),
    http.get(`${API_BASE_URL}/projects/p1/versions/:vid/export-readiness`, () => HttpResponse.json({
      stale, reason: stale ? 'a correction is newer than the derived output' : 'up to date', explanation: '',
      overrideCount: stale ? 2 : 0, pendingRenders: 0, failedRenders: 0, newestOverrideAt: null,
      oldestDerivationAt: null, reexport: null, ...(staleComponents ? { staleComponents } : {}) })),
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
  return slot
}

const STALE_ROW = 'Download DOCX: Previous Word file — the corrections are not in it yet'
const all = documents.documents.length

describe('DocumentsPage: Download while the Word files lack corrections', { timeout: 30_000 }, () => {
  it('marks only the rows of the components R9 names — not an approved one — and Download All', async () => {
    // `Full` has an in-review SWE.3 (doc1) and an approved one (doc7, its approved file).
    const slot = setup(true, ['Full'])
    const stale = await screen.findAllByRole('button', { name: STALE_ROW })
    expect(stale).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Download DOCX' })).toHaveLength(all - 1)
    const downloadAll = within(slot).getByRole('button', { name: /DOWNLOAD ALL/ })
    expect(downloadAll).toHaveAttribute('title', 'Download all: Previous Word files — the corrections are not in them yet')
    // Said to a screen reader as text, not as a label on a plain span.
    expect(within(downloadAll).getByText('Previous Word files — the corrections are not in them yet')).toHaveClass('sr-only')
  })

  it('Download All is not marked when R9 names only components whose documents are all approved', async () => {
    // `Global`'s two documents are approved: their Word files are the approved ones.
    const slot = setup(true, ['Global'])
    expect(await screen.findAllByRole('button', { name: 'Download DOCX' })).toHaveLength(all)
    expect(within(slot).getByRole('button', { name: /DOWNLOAD ALL/ })).not.toHaveAttribute('title')
  })

  it('an API that does not say which components: every row but the approved ones', async () => {
    setup(true)
    const approved = documents.documents.filter((d) => d.status === 'approved').length
    expect(await screen.findAllByRole('button', { name: STALE_ROW })).toHaveLength(all - approved)
  })

  it('says nothing when the Word files are up to date', async () => {
    const slot = setup(false)
    expect(await screen.findAllByRole('button', { name: 'Download DOCX' })).toHaveLength(documents.documents.length)
    expect(within(slot).getByRole('button', { name: /DOWNLOAD ALL/ })).not.toHaveAttribute('title')
  })
})
