import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { emptyReview } from '../../../test/factories'
import { useToastStore } from '../../../components/ui/Toast'
import { ApproveDialog } from '../components/ReviewDialogs'
import type { Document, ExportReadiness } from '../../../types'

/* Approve on an out-of-date Word file is no dead end (WORD_FILE_UPDATES D10, W4): the dialog
   says so and offers Update file — its link starts the update, no second dialog — and Approve
   turns on when the file is up to date. */

const UTIL = 'Layer1.Util'
const doc: Document = {
  id: 'd1', name: 'Util', process: 'SWE.3', status: 'submitted', version: 'v1.2.0', versionId: 'v1', group: UTIL,
  updatedAt: '', reviewer: { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }, review: { ...emptyReview, comment: 'Checked.' },
}
const base: ExportReadiness = {
  stale: false, explanation: null, overrideCount: 0, pendingRenders: 0, failedRenders: 0, reexport: null,
  outOfDate: [], approvedKept: [], writer: null,
}
const behind: ExportReadiness = { ...base, stale: true, outOfDate: [{
  documentId: 'd1', component: UTIL, name: 'Util', docType: 'SWE.3', why: ['corrections'], corrections: 2,
  pictures: 0, layer: null, updating: false,
}] }
const words = { versionTag: 'v1.2.0', nameOf: (c: string) => c.replace(/^Layer1\./, '') }

function setup(readiness: ExportReadiness | undefined, failed = false) {
  const sent: unknown[] = []
  server.use(
    http.post(`${API_BASE_URL}/projects/p1/versions/v1/reexport`, async ({ request }) => {
      sent.push(await request.json())
      return HttpResponse.json({ job_id: 'j1', status: 'queued', version_id: 'v1', scope: 'out_of_date', components: [UTIL], joined: false }, { status: 202 })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrap = (c: ReactNode) => <QueryClientProvider client={client}>{c}</QueryClientProvider>
  render(wrap(
    <ApproveDialog projectId="p1" versionId="v1" doc={doc} corrections={2} readiness={readiness} readinessFailed={failed} meId="u1"
      words={words} onClose={vi.fn()} />,
  ))
  return { sent, user: userEvent.setup(), approve: () => screen.getByRole('button', { name: /^Approve$/ }) }
}

afterEach(() => useToastStore.setState({ toasts: [] }))

describe('ApproveDialog — its Word file', () => {
  it('8: Approve stays off until A15 has answered: checking, then up to date', () => {
    const { approve } = setup(undefined)
    expect(screen.getByText('Checking its Word file…')).toBeInTheDocument()
    expect(approve()).toBeDisabled()
  })

  it("A15 failed closed: Can't tell, and Approve stays off — never up to date with Approve on", () => {
    const { approve } = setup(undefined, true)
    expect(screen.getByText('Can’t tell if its Word file is up to date.')).toBeInTheDocument()
    expect(screen.queryByText('Its Word file is up to date.')).toBeNull()
    expect(approve()).toBeDisabled()
  })

  it("8: an older server's A15 (stale, staleComponents []) is this document's: out of date, Approve off", () => {
    const { approve } = setup({ ...base, stale: true, staleComponents: [], outOfDate: undefined })
    expect(screen.getByText('Its Word file is out of date.')).toBeInTheDocument()
    expect(approve()).toBeDisabled()
  })

  it('out of date: Update file starts the update (no second dialog); Approve is off until it is done', async () => {
    const { sent, user, approve } = setup(behind)
    expect(screen.getByText('Its Word file is out of date.')).toBeInTheDocument()
    expect(approve()).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Update file' }))
    await waitFor(() => expect(sent).toEqual([{ scope: 'out_of_date', components: [UTIL], document_id: 'd1' }]))
    expect(screen.queryByRole('dialog', { name: /Update/ })).toBeNull()
  })

  it('updating: says so, and Approve stays off', () => {
    const { approve } = setup({ ...behind, reexport: {
      jobId: 'j1', status: 'running', startedAt: null, completedAt: null, errorMessage: null, components: [UTIL], componentsDone: 0,
    } })
    expect(screen.getByText('Updating its Word file…')).toBeInTheDocument()
    expect(approve()).toBeDisabled()
  })

  it('up to date: Approve is on', () => {
    const { approve } = setup(base)
    expect(screen.getByText('Its Word file is up to date.')).toBeInTheDocument()
    expect(approve()).toBeEnabled()
  })

  it('while a generation holds the version: no link, and when it can be updated', () => {
    setup({ ...behind, writer: { kind: 'generation', jobId: 'j5', command: 'generate', since: null, components: null,
      componentsDone: null, componentsTotal: null, startedBy: null } })
    expect(screen.queryByRole('button', { name: 'Update file' })).toBeNull()
    expect(screen.getByText('Update after the generation of v1.2.0 ends.')).toBeInTheDocument()
  })

  it('the update its starter saw fail: Update failed, Try again', () => {
    setup({ ...behind, reexport: {
      jobId: 'j1', status: 'failed', startedAt: null, completedAt: null, errorMessage: 'pictures could not be drawn',
      components: [UTIL], scope: 'out_of_date', startedBy: { userId: 'u1', name: 'A', initials: 'A' },
    } })
    expect(screen.getByText('Update failed.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('the server still finds it out of date (409 STALE_EXPORT): says why, in its words', async () => {
    server.use(http.post(`${API_BASE_URL}/projects/p1/documents/d1/approve`, () => HttpResponse.json({ detail: {
      code: 'STALE_EXPORT', message: 'stale', status: 409, why: ['layerAdded'], corrections: 0, pictures: 0, layer: 'HAL_LAYER',
    } }, { status: 409 })))
    const { user, approve } = setup(base)
    await user.click(approve())
    await waitFor(() => expect(useToastStore.getState().toasts[0])
      .toMatchObject({ title: 'Not approved', description: 'Its Word file is out of date. HAL_LAYER added since.' }))
  })
})
