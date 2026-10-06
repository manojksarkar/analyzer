import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { SubbarCtaProvider } from '../../../components/shell/SubbarCta'
import { useAuthStore } from '../../../store/auth'
import { useWordFilesStore } from '../../../store/wordFiles'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import versions from '../../../test/fixtures/captured/versions.json'
import documents from '../../../test/fixtures/captured/documents.json'
import members from '../../../test/fixtures/captured/members.json'
import { DocumentsPage } from '..'

/* Download serves the stored Word file as it is (REVIEW_UPDATE_API_SPEC §14): when R9 lists a
   document's file as out of date (WORD_FILE_UPDATES W3), its row's download offers the corrected
   file (updated first) or the current one; Download all, the corrected files or the files as they
   are. An approved document's file is the approved one: never marked. */

const rows = documents.documents.length
const behind = (documentId: string, component: string, name: string) => ({
  documentId, component, name, docType: 'SWE.3', why: ['corrections'], corrections: 2, pictures: 0, layer: null, updating: false,
})

function setup(opts: { role?: 'admin' | 'developer'; outOfDate?: object[]; writer?: object | null } = {}) {
  const { role = 'developer', outOfDate = [], writer = null } = opts
  const sent: unknown[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json({ project: { ...project.project, my_role: role } })),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ ...documents, pagination: { page: 1, per_page: 100, total: documents.documents.length } })),
    http.get(`${API_BASE_URL}/projects/p1/versions/:vid/components`, ({ params }) =>
      HttpResponse.json({ version_id: params.vid, components: [], counts: {}, run: null })),
    http.get(`${API_BASE_URL}/projects/p1/versions/:vid/export-readiness`, () => HttpResponse.json({
      stale: outOfDate.length > 0, reason: '', explanation: '', overrideCount: 2, pendingRenders: 0, failedRenders: 0,
      newestOverrideAt: null, oldestDerivationAt: null, reexport: null, outOfDate, approvedKept: [], writer })),
    // A download waiting for an update follows its job (still running here).
    http.get(`${API_BASE_URL}/projects/p1/jobs/:jobId`, ({ params }) => HttpResponse.json({ job: {
      id: params.jobId, status: 'running', phase: 4, phase_pct: 10, current_activity: '', activity_detail: '',
      elapsed_seconds: 1, eta_seconds: null, phases: [], commit_sha: 'abc1234', branch: 'main', version_id: 'ver3',
      mode: 'reexport', started_at: null, completed_at: null, error_message: null,
    } })),
    http.post(`${API_BASE_URL}/projects/p1/versions/:vid/reexport`, async ({ request }) => {
      sent.push(await request.json())
      return HttpResponse.json({ job_id: 'job1', status: 'queued', version_id: 'ver3', scope: 'out_of_date', components: [], joined: false }, { status: 202 })
    }),
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
  return { slot, sent, user: userEvent.setup() }
}

afterEach(() => {
  useAuthStore.setState({ user: null })
  useWordFilesStore.setState({ pending: {}, justUpdated: {} })
})

describe('DocumentsPage: Word files out of date', { timeout: 60_000 }, () => {
  it("marks only the rows R9 lists; a row's Corrected file asks first, then updates its component", async () => {
    const { sent, user } = setup({ outOfDate: [behind('doc1', 'Full', 'Full')] })
    const dl = await screen.findByRole('button', { name: /Download DOCX \(out of date: 2 corrections not in it\)/ })
    expect(screen.getAllByRole('button', { name: 'Download DOCX' })).toHaveLength(rows - 1)
    await user.click(dl)
    await user.click(await screen.findByRole('menuitem', { name: /Corrected file/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Update 1 Word file' })
    expect(within(dialog).getByText('The download starts when it is done.')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: /^Update$/ }))
    // The document in hand counts as the one open: a developer may update it.
    await waitFor(() => expect(sent).toEqual([{ scope: 'out_of_date', components: ['Full'], document_id: 'doc1' }]))
    await waitFor(() => expect(useWordFilesStore.getState().pending.job1?.[0]).toMatchObject({ docId: 'doc1' }))
  })

  it("Download all: the files as they are, or the corrected ones — a developer's reach is the ones they review", async () => {
    useAuthStore.setState({ user: { id: 'u2', email: 'developer@company.com', name: 'Bob' } as never })
    const { slot, sent, user } = setup({ outOfDate: [behind('doc1', 'Full', 'Full'), behind('doc2', 'Access', 'Access')] })
    const all = await within(slot).findByRole('button', { name: /DOWNLOAD ALL/ })
    await waitFor(() => expect(all).toHaveAttribute('title', '2 files are out of date'))
    await user.click(all)
    const dialog = await screen.findByRole('dialog', { name: 'Download all Word files' })
    expect(within(dialog).getByText('2 files are out of date.')).toBeInTheDocument()
    expect(within(dialog).getByText('You can update the 1 you review.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'As they are' })).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: /Corrected files/ }))
    await waitFor(() => expect(sent).toEqual([{ scope: 'out_of_date', components: ['Full'] }]))
    await waitFor(() => expect(useWordFilesStore.getState().pending.job1?.[0]).toMatchObject({ versionId: 'ver3' }))
  })

  it('while a generation holds the version, Corrected files is off and the dialog says when', async () => {
    const { slot, user } = setup({ role: 'admin', outOfDate: [behind('doc1', 'Full', 'Full')], writer: {
      kind: 'generation', jobId: 'j5', command: 'generate', since: null, components: null, componentsDone: null,
      componentsTotal: null, startedBy: null } })
    const all = await within(slot).findByRole('button', { name: /DOWNLOAD ALL/ })
    await waitFor(() => expect(all).toHaveAttribute('title', '1 file is out of date'))
    await user.click(all)
    const dialog = await screen.findByRole('dialog', { name: 'Download all Word files' })
    expect(within(dialog).getByText('Update after the generation of v1.2.0 ends.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Corrected files/ })).toBeDisabled()
  })

  it('says nothing when the Word files are up to date', async () => {
    const { slot } = setup()
    expect(await screen.findAllByRole('button', { name: 'Download DOCX' })).toHaveLength(rows)
    expect(await within(slot).findByRole('button', { name: /DOWNLOAD ALL/ })).not.toHaveAttribute('title')
  })
})
