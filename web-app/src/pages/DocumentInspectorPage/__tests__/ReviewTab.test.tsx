import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { emptyReview as EMPTY_REVIEW } from '../../../test/factories'
import documentFx from '../../../test/fixtures/captured/document.json'
import { useToastStore } from '../../../components/ui/Toast'
import { ReviewTab } from '../components/ReviewTab'
import type { ReviewCtx } from '../review'
import type { Document, ExportReadiness, OutOfDateFile } from '../../../types'

/* The Review tab renders the one action for the role and state, and the record (A10). */

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }
const doc = (over: Partial<Document> = {}): Document => ({
  id: 'd1', name: 'Util', process: 'SWE.3', status: 'submitted', version: 'ver1', versionId: 'ver1', updatedAt: '',
  reviewer: bob, review: { ...EMPTY_REVIEW, comment: 'Checked every function.' }, ...over,
})
const upToDate: ExportReadiness = { stale: false, explanation: null, overrideCount: 0, pendingRenders: 0, failedRenders: 0, reexport: null }
const admin: ReviewCtx = { isAdmin: true, meId: 'u1' }
const words = { versionTag: 'v1.2.0', nameOf: (c: string) => c.replace(/^Layer1\./, '') }

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

/** `readiness` null: A15 not answered (with `failed`, it answered an error). */
function renderTab(d: Document, ctx: ReviewCtx, readiness: ExportReadiness | null = upToDate, failed = false) {
  server.use(http.get(`${API_BASE_URL}/projects/p1/documents/d1/events`, () => HttpResponse.json({
    events: [{
      id: 'e1', document_id: 'd1', version_id: 'ver1', kind: 'submitted', actor: { user_id: 'u2', name: 'Bob Kumar', initials: 'BK' },
      at: '2026-10-01T09:40:00Z', comment: 'Checked every function.', payload: {},
    }],
  })))
  const noop = vi.fn()
  const onUpdate = vi.fn()
  render(wrap(
    <ReviewTab projectId="p1" doc={d} versionTag="v1.2.0" ctx={ctx} readiness={readiness ?? undefined} readinessFailed={failed}
      corrections={3} isSwe3 nameOf={() => undefined} words={words}
      onAssign={noop} onApprove={noop} onChanges={noop} onReopen={noop} onSubmitted={noop} onUpdate={onUpdate} />,
  ))
  return { onUpdate, user: userEvent.setup() }
}

const UTIL = 'Layer1.Util'
const outOfDate = (over: Partial<OutOfDateFile> = {}): OutOfDateFile => ({
  documentId: 'd1', component: UTIL, name: 'Util', docType: 'SWE.3', why: ['corrections'], corrections: 2,
  pictures: 0, layer: null, updating: false, ...over,
})
const behind: ExportReadiness = { ...upToDate, stale: true, outOfDate: [outOfDate()], approvedKept: [], writer: null }
const job = (over: Partial<NonNullable<ExportReadiness['reexport']>>): ExportReadiness['reexport'] => ({
  jobId: 'j1', status: 'running', startedAt: null, completedAt: null, errorMessage: null, scope: 'out_of_date',
  reason: 'update', components: [UTIL], componentsDone: 0, startedBy: { userId: 'u1', name: 'Alice Admin', initials: 'AA' },
  ...over,
})
/** The Word file row's value. */
const wordRow = () => screen.getByText('Word file').parentElement as HTMLElement

describe('ReviewTab — the Word file row', () => {
  it('out of date (why), and Update asks for its component', async () => {
    const { onUpdate, user } = renderTab(doc({ status: 'in_review', group: UTIL }), admin, behind)
    expect(within(wordRow()).getByText('Out of date (2 corrections)')).toHaveAttribute('title', '2 corrections not in it')
    await user.click(within(wordRow()).getByRole('button', { name: 'Update' }))
    expect(onUpdate).toHaveBeenCalledWith({ components: [UTIL] })
  })

  it('updating: Updating…, no action', () => {
    renderTab(doc({ group: UTIL }), admin, { ...behind, reexport: job({}) })
    expect(within(wordRow()).getByText('Updating…')).toBeInTheDocument()
    expect(within(wordRow()).queryByRole('button')).toBeNull()
  })

  it('failed, to its starter: Update failed (why in the tooltip), and Try again', async () => {
    const failed = { ...behind, reexport: job({ status: 'failed', errorMessage: 'flowchart pictures could not be drawn' }) }
    const { onUpdate, user } = renderTab(doc({ group: UTIL }), admin, failed)
    expect(within(wordRow()).getByText('Update failed')).toHaveAttribute('title', 'Flowchart pictures could not be drawn.')
    await user.click(within(wordRow()).getByRole('button', { name: 'Try again' }))
    expect(onUpdate).toHaveBeenCalledWith({ components: [UTIL], rebuild: false })
  })

  it('to anyone else a failed update is simply out of date', () => {
    const failed = { ...behind, reexport: job({ status: 'failed', startedBy: { userId: 'u9', name: 'X', initials: 'X' } }) }
    renderTab(doc({ group: UTIL }), admin, failed)
    expect(within(wordRow()).getByText('Out of date (2 corrections)')).toBeInTheDocument()
  })

  it('while a generation holds the version, Update is off and its tooltip says why', () => {
    renderTab(doc({ group: UTIL }), admin, { ...behind, writer: {
      kind: 'generation', jobId: 'j5', command: 'generate', since: null, components: null, componentsDone: null,
      componentsTotal: null, startedBy: null,
    } })
    expect(within(wordRow()).queryByRole('button', { name: 'Update' })).toBeNull()
    expect(within(wordRow()).getByText('Update')).toHaveAttribute('title', 'Update after the generation of v1.2.0 ends.')
  })

  it('approved: Approved — its kept file is not changed by a later correction', () => {
    renderTab(doc({ status: 'approved', group: UTIL }), admin,
      { ...upToDate, stale: false, outOfDate: [], approvedKept: [outOfDate()] })
    expect(within(wordRow()).getByText('Approved')).toHaveAttribute('title', 'A later correction is not in it. Reopen to take it.')
  })

  it('up to date', () => {
    renderTab(doc({ group: UTIL }), admin, { ...upToDate, outOfDate: [] })
    expect(within(wordRow()).getByText('Up to date')).toBeInTheDocument()
  })

  it("A15 failed closed: Can't tell — never Up to date", () => {
    renderTab(doc({ group: UTIL }), admin, null, true)
    expect(within(wordRow()).getByText('Can’t tell')).toBeInTheDocument()
    expect(within(wordRow()).queryByText('Up to date')).toBeNull()
  })

  it("8: an older server's A15 (stale, staleComponents []) is this document's: Out of date", () => {
    renderTab(doc({ group: UTIL }), admin, { ...upToDate, stale: true, staleComponents: [] })
    expect(within(wordRow()).getByText(/^Out of date/)).toBeInTheDocument()
  })
})

describe("ReviewTab — Submit says what it did to the Word file (A5's word_file)", () => {
  afterEach(() => useToastStore.setState({ toasts: [] }))

  async function submitWith(wordFile: unknown) {
    server.use(http.post(`${API_BASE_URL}/projects/p1/documents/d1/submit-review`, () => HttpResponse.json({
      document: { ...documentFx.document, id: 'd1', status: 'submitted' }, ...(wordFile === undefined ? {} : { word_file: wordFile }),
    })))
    const { user } = renderTab(doc({ status: 'in_review', group: UTIL }), { isAdmin: false, meId: 'u2' }, behind)
    await user.type(screen.getByLabelText('Your review'), 'Checked it.')
    await user.click(screen.getByRole('button', { name: /Submit for approval/ }))
    await waitFor(() => expect(useToastStore.getState().toasts.length).toBe(1))
    const [t] = useToastStore.getState().toasts
    return [t.title, t.description]
  }

  it('up to date: submitted for approval', async () => {
    expect(await submitWith({ state: 'up_to_date', job_id: null, blocked_by: null }))
      .toEqual(['Submitted for approval.', 'The admins are notified.'])
  })
  it('out of date: the server started its update — no second dialog', async () => {
    expect(await submitWith({ state: 'updating', job_id: 'j1', blocked_by: null }))
      .toEqual(['Submitted.', 'Its Word file is updating.'])
  })
  it('a generation holds the version: it goes through, and says when to update', async () => {
    expect(await submitWith({ state: 'out_of_date', job_id: null, blocked_by: { kind: 'generation', job_id: 'j5', components: null } }))
      .toEqual(['Submitted.', 'Update its Word file after the generation ends.'])
  })
  it('another update holds it: after which one', async () => {
    expect(await submitWith({ state: 'out_of_date', job_id: null, blocked_by: { kind: 'update', job_id: 'j6', components: ['Layer1.Math'] } }))
      .toEqual(['Submitted.', 'Update its Word file after the update of Math ends.'])
  })
  it('an older API (no word_file): as before', async () => {
    expect(await submitWith(undefined)).toEqual(['Submitted for approval.', 'The admins are notified.'])
  })
})

describe('ReviewTab', () => {
  it("admin, ready for approval: the reviewer's comment, Approve and Request changes, and the record", async () => {
    renderTab(doc(), admin)
    expect(screen.getByText('Ready for approval')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Approve…/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Request changes…/ })).toBeInTheDocument()
    expect(screen.getByText('Up to date')).toBeInTheDocument()
    expect(await screen.findByText(/submitted it for approval/)).toBeInTheDocument()
  })

  it('Approve… stays on while the Word file is out of date: its dialog offers the update', () => {
    renderTab(doc({ group: 'Layer1.Util' }), admin, {
      ...upToDate, stale: true,
      outOfDate: [{ documentId: 'd1', component: 'Layer1.Util', name: 'Util', docType: 'SWE.3', why: ['corrections'],
        corrections: 2, pictures: 0, layer: null, updating: false }],
    })
    expect(screen.getByRole('button', { name: /Approve…/ })).toBeEnabled()
    expect(screen.getByText('Out of date (2 corrections)')).toBeInTheDocument()
  })

  it('developer without a reviewer: Claim', () => {
    renderTab(doc({ status: 'in_review', reviewer: null }), { ...admin, isAdmin: false, meId: 'u3' })
    expect(screen.getByText('Needs a reviewer')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Claim/ })).toBeInTheDocument()
  })

  it('its reviewer, in review: the comment box and Submit for approval', () => {
    renderTab(doc({ status: 'in_review' }), { ...admin, isAdmin: false, meId: 'u2' })
    expect(screen.getByLabelText('Your review')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Submit for approval/ })).toBeInTheDocument()
  })

  it('approved: who approved it, the hash, locked, and Reopen for an admin', () => {
    renderTab(doc({
      status: 'approved',
      review: { ...EMPTY_REVIEW, approvedBy: { userId: 'u1', name: 'Alice Admin', initials: 'AA' }, docxSha256: '9f2c0011aabbccdd' },
    }), admin)
    expect(screen.getByText(/By Alice Admin/)).toBeInTheDocument()
    expect(screen.getByText(/Word file sha256 9f2c0011aabb/)).toBeInTheDocument()
    expect(screen.getByText(/Locked: no corrections/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Reopen…/ })).toBeInTheDocument()
  })
})
