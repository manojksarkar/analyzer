import { useState, type ReactNode } from 'react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
import documentFx from '../../../test/fixtures/captured/document.json'
import { SubbarCtaProvider } from '../../../components/shell/SubbarCta'
import { useToastStore } from '../../../components/ui/Toast'
import { useAuthStore } from '../../../store/auth'
import { useUIStore } from '../../../store/ui'
import { DocumentInspectorPage } from '..'

/* Word files in the reader (WORD_FILE_UPDATES W2, W6): corrections wait only while an update
   writes this document's component (the edit hold), a save refused for it says so, and Done
   editing suggests the update — a suggestion, never one started on its own. */

vi.mock('../components/FlowchartFigure', () => ({ FlowchartFigure: () => null, ImageViewer: () => null }))

const API = API_BASE_URL
const V = `${API}/projects/p1/versions/ver2`
const slot = (key: string, text: string) => ({
  slotKind: 'description', slotKey: key, text, llmText: text, humanText: null,
  isOverridden: false, isOrphaned: false, canUndo: false, updatedBy: null, updatedAt: null,
})
const render9 = {
  document: {
    cover: { project_name: 'VCU', subtitle: 'Detailed Design', version: 'v1.1.0', layer: 'Layer1', group: 'Full' },
    toc: [],
    sections: [{
      id: 'fn-alpha', number: '2.1', title: 'alpha()', level: 3, type: 'flowchart_table', content: null, table: null, children: [],
      flowchart_table: {
        description: 'Adds.', risk: 'Low', capacity: '-', input_name: 'x', output_name: 'y',
        description_slot: slot('C|U|alpha|int', 'Adds.'), flowcharts: [],
      },
    }],
    meta: { pipeline_data_available: true, model_data_available: true, source: 'pipeline', layers: ['Layer1'],
      components: ['Full'], units_total: 1, functions_total: 1, globals_total: 0 },
  },
}
const outOfDate = (over: object = {}) => ({
  documentId: 'doc1', component: 'Full', name: 'Full', docType: 'SWE.3', why: ['corrections'], corrections: 1,
  pictures: 0, layer: null, updating: false, ...over,
})
const r9 = (over: object = {}) => ({
  stale: true, reason: '', explanation: '', overrideCount: 1, pendingRenders: 0, failedRenders: 0,
  newestOverrideAt: null, oldestDerivationAt: null, reexport: null, outOfDate: [outOfDate()], approvedKept: [],
  writer: null, ...over,
})
const running = (components: string[]) => ({
  jobId: 'job1', status: 'running', startedAt: null, completedAt: null, errorMessage: null, scope: 'out_of_date',
  reason: 'update', components, componentsDone: 0, startedBy: { userId: 'u1', name: 'Admin', initials: 'AD' },
})

function setup(readiness: object | (() => object), save?: () => Response) {
  const doc = { ...documentFx.document, version_id: 'ver2' }
  server.use(
    http.get(`${API}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: [doc], pagination: { page: 1, per_page: 100, total: 1 } })),
    http.get(`${API}/projects/p1/documents/doc1`, () => HttpResponse.json({ document: doc })),
    http.get(`${API}/projects/p1/documents/doc1/render`, () => HttpResponse.json(render9)),
    http.get(`${API}/projects/p1/documents/doc1/events`, () => HttpResponse.json({ events: [] })),
    http.get(`${V}/export-readiness`, () => HttpResponse.json(typeof readiness === 'function' ? readiness() : readiness)),
    http.get(`${V}/overrides`, () => HttpResponse.json({ overrides: [], total: 0, limit: 1000, offset: 0 })),
    http.get(`${V}/regeneration-queue`, () => HttpResponse.json({ pending: [], total: 0 })),
    ...(save ? [http.put(`${V}/overrides/slot`, save)] : []),
  )
  function Layout({ children }: { children: ReactNode }) {
    const [cta, setCta] = useState<HTMLDivElement | null>(null)
    return <><div ref={setCta} data-testid="subbar-cta" /><SubbarCtaProvider slot={cta}>{children}</SubbarCtaProvider></>
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/documents/doc1']}>
        <Routes>
          <Route path="/projects/:projectId/documents/:docId" element={<Layout><DocumentInspectorPage /></Layout>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const user = userEvent.setup()
  const edit = async () => {
    const cta = await screen.findByTestId('subbar-cta')
    await user.click(await within(cta).findByRole('button', { name: /EDIT/ }))
  }
  return { user, edit }
}

beforeAll(() => {
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {}
})
afterEach(() => {
  useToastStore.setState({ toasts: [] })
  useUIStore.setState({ selectedRef: {}, inspectorPanelCollapsed: false })
  useAuthStore.setState({ user: null })
})

describe('Word files in the reader', { timeout: 60_000 }, () => {
  it("an update writing this document's component holds its corrections, and says so", async () => {
    const { edit } = setup(r9({ outOfDate: [outOfDate({ updating: true })], reexport: running(['Full', 'Other']) }))
    expect(await screen.findByText(/Updating Word files…/)).toBeInTheDocument()
    await edit()
    expect(await screen.findByText('Updating this document’s Word file.')).toBeInTheDocument()
    expect(screen.getByText(/Corrections wait until it is done\./)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Correct this text' })).toHaveAttribute('readonly')
  })

  it("an update of another component leaves this document editable", async () => {
    const { edit } = setup(r9({ reexport: running(['Other']) }))
    expect(await screen.findByText('This Word file is out of date')).toBeInTheDocument()
    await edit()
    const box = await screen.findByRole('textbox', { name: 'Correct this text' })
    expect(box).not.toHaveAttribute('readonly')
    expect(screen.queryByText('Updating this document’s Word file.')).toBeNull()
  })

  it('a save the server refuses while an update writes its component (409 WORD_FILE_UPDATING) says why', async () => {
    const { edit } = setup(r9(), () => HttpResponse.json({ detail: {
      code: 'WORD_FILE_UPDATING', message: 'An update is writing it.', status: 409, job_id: 'job1', components: ['Full'],
    } }, { status: 409 }))
    await edit()
    const box = await screen.findByRole('textbox', { name: 'Correct this text' })
    fireEvent.change(box, { target: { value: 'Adds two numbers.' } })
    fireEvent.blur(box)
    expect(await screen.findByText('Corrections wait until the update is done. Your text is still here.')).toBeInTheDocument()
  })

  it('Done editing on an out-of-date file suggests the update; its Update asks first', async () => {
    const { user, edit } = setup(r9())
    expect(await screen.findByText('This Word file is out of date')).toBeInTheDocument()
    await edit()
    await user.click(within(screen.getByTestId('subbar-cta')).getByRole('button', { name: /DONE/ }))
    const [t] = useToastStore.getState().toasts
    expect(t).toMatchObject({ title: 'Word file out of date.', action: { label: 'Update' } })
    t.action?.onClick()
    expect(await screen.findByText('Update 1 Word file')).toBeInTheDocument()
    expect(screen.getByText('Corrections to Full wait until it is done.')).toBeInTheDocument()
  })

  it('10: Done right after the last correction: the suggestion waits for its save and R9 read again', async () => {
    // Up to date until the correction is saved; then R9 lists this document.
    let saved = false
    const { user, edit } = setup(() => (saved ? r9() : r9({ stale: false, outOfDate: [] })), () => {
      saved = true
      return HttpResponse.json({ ...slot('C|U|alpha|int', 'Adds two numbers.'), humanText: 'Adds two numbers.',
        isOverridden: true, canUndo: true, previousText: 'Adds.', firstEdit: true, queuedForRegeneration: [] })
    })
    await edit()
    const box = await screen.findByRole('textbox', { name: 'Correct this text' })
    await user.clear(box)
    await user.type(box, 'Adds two numbers.')
    // Done straight from the box: the click blurs it, which saves.
    await user.click(within(screen.getByTestId('subbar-cta')).getByRole('button', { name: /DONE/ }))
    await waitFor(() => expect(saved).toBe(true))
    await waitFor(() => expect(useToastStore.getState().toasts.map((x) => x.title)).toContain('Word file out of date.'))
  })

  it('the banner’s Update asks first, then sends this component and the document open', async () => {
    let sent: unknown = null
    server.use(http.post(`${V}/reexport`, async ({ request }) => {
      sent = await request.json()
      return HttpResponse.json({ job_id: 'job1', status: 'queued', version_id: 'ver2', scope: 'out_of_date', components: ['Full'], joined: false }, { status: 202 })
    }))
    const { user } = setup(r9())
    const banner = await screen.findByRole('status', { name: 'Word file' })
    await user.click(within(banner).getByRole('button', { name: /^Update$/ }))
    const dialog = await screen.findByRole('dialog')
    await user.click(within(dialog).getByRole('button', { name: /^Update$/ }))
    await waitFor(() => expect(sent).toEqual({ scope: 'out_of_date', components: ['Full'], document_id: 'doc1' }))
  })
})
