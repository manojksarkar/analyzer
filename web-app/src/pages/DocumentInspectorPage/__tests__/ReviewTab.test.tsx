import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { emptyReview as EMPTY_REVIEW } from '../../../test/factories'
import { ReviewTab } from '../components/ReviewTab'
import type { ReviewCtx } from '../review'
import type { Document, ExportReadiness } from '../../../types'

/* The Review tab renders the one action for the role and state, and the record (A10). */

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }
const doc = (over: Partial<Document> = {}): Document => ({
  id: 'd1', name: 'Util', process: 'SWE.3', status: 'submitted', version: 'ver1', versionId: 'ver1', updatedAt: '',
  reviewer: bob, review: { ...EMPTY_REVIEW, comment: 'Checked every function.' }, ...over,
})
const upToDate: ExportReadiness = { stale: false, explanation: null, overrideCount: 0, pendingRenders: 0, failedRenders: 0, reexport: null }
const admin: ReviewCtx = { isAdmin: true, meId: 'u1', wordFileStale: false, reexporting: false }

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

function renderTab(d: Document, ctx: ReviewCtx, readiness: ExportReadiness = upToDate) {
  server.use(http.get(`${API_BASE_URL}/projects/p1/documents/d1/events`, () => HttpResponse.json({
    events: [{
      id: 'e1', document_id: 'd1', version_id: 'ver1', kind: 'submitted', actor: { user_id: 'u2', name: 'Bob Kumar', initials: 'BK' },
      at: '2026-10-01T09:40:00Z', comment: 'Checked every function.', payload: {},
    }],
  })))
  const noop = vi.fn()
  return render(wrap(
    <ReviewTab projectId="p1" versionId="ver1" doc={d} versionTag="v1.2.0" ctx={ctx} readiness={readiness}
      corrections={3} isSwe3 nameOf={() => undefined}
      onAssign={noop} onApprove={noop} onChanges={noop} onReopen={noop} onSubmitted={noop} />,
  ))
}

describe('ReviewTab', () => {
  it("admin, ready for approval: the reviewer's comment, Approve and Request changes, and the record", async () => {
    renderTab(doc(), admin)
    expect(screen.getByText('Ready for approval')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Approve…/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /Request changes…/ })).toBeInTheDocument()
    expect(screen.getByText('up to date')).toBeInTheDocument()
    expect(await screen.findByText(/submitted it for approval/)).toBeInTheDocument()
  })

  it('Approve is off while the Word file lacks corrections, and says why', () => {
    renderTab(doc(), { ...admin, wordFileStale: true }, { ...upToDate, stale: true })
    expect(screen.getByRole('button', { name: /Approve…/ })).toBeDisabled()
    expect(screen.getByText(/Re-export first/)).toBeInTheDocument()
    expect(screen.getByText('corrections missing')).toBeInTheDocument()
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
