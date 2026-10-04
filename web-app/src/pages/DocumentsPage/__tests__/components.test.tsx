import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { emptyReview as EMPTY_REVIEW } from '../../../test/factories'
import { DocRow } from '../components/DocRow'
import { VersionApprovalBar } from '../components/VersionApprovalBar'
import type { Document } from '../../../types'

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }
const mk = (id: string, status: Document['status'], over: Partial<Document> = {}): Document => ({
  id, name: `Doc ${id}`, process: 'SWE.3', status, version: 'v1.2.0', versionId: 'ver1', updatedAt: '',
  reviewer: bob, review: EMPTY_REVIEW, ...over,
})

function row(doc: Document, role: { isAdmin: boolean; meId: string }, wordFileStale = false) {
  const handlers = {
    onToggle: vi.fn(), onOpen: vi.fn(), onReview: vi.fn(), onCompare: vi.fn(), onDownload: vi.fn(),
    onAssign: vi.fn(), onClaim: vi.fn(),
  }
  render(
    <table><tbody>
      <DocRow doc={doc} selected={false} isAdmin={role.isAdmin} isDeveloper={!role.isAdmin} meId={role.meId}
        nameOf={() => undefined} claimPending={false} wordFileStale={wordFileStale} {...handlers} />
    </tbody></table>,
  )
  return handlers
}

describe('DocRow', () => {
  it('admin: Review for a document ready for approval', async () => {
    const h = row(mk('a', 'submitted'), { isAdmin: true, meId: 'u1' })
    await userEvent.click(screen.getByRole('button', { name: 'Review and approve' }))
    expect(h.onReview).toHaveBeenCalled()
  })
  it('admin: Re-assign one in review, nothing on an approved one', () => {
    row(mk('a', 'in_review'), { isAdmin: true, meId: 'u1' })
    expect(screen.getByRole('button', { name: 'Re-assign (now Bob Kumar)' })).toBeInTheDocument()
  })
  it('admin: no assign on an approved document', () => {
    row(mk('a', 'approved'), { isAdmin: true, meId: 'u1' })
    expect(screen.queryByRole('button', { name: /assign/i })).toBeNull()
  })
  it('developer: Claim a document without a reviewer, which reads "Needs a reviewer"', async () => {
    const h = row(mk('a', 'in_review', { reviewer: null }), { isAdmin: false, meId: 'u3' })
    expect(screen.getByText('Needs a reviewer')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Claim: become its reviewer' }))
    expect(h.onClaim).toHaveBeenCalled()
  })
  it('Download says it gives the previous Word file while the corrections are not in it (R9 stale)', async () => {
    const h = row(mk('a', 'in_review'), { isAdmin: false, meId: 'u2' }, true)
    const dl = screen.getByRole('button', { name: /Download DOCX/ })
    expect(dl).toHaveAttribute('title', 'Download DOCX: Previous Word file — the corrections are not in it yet')
    await userEvent.click(dl)
    expect(h.onDownload).toHaveBeenCalled()
  })
  it('Download is plain when the Word files are up to date, and for an approved document (its approved file)', () => {
    row(mk('a', 'in_review'), { isAdmin: false, meId: 'u2' })
    row(mk('b', 'approved'), { isAdmin: false, meId: 'u2' }, true)
    expect(screen.getAllByRole('button', { name: 'Download DOCX' })).toHaveLength(2)
  })
  it('shows where a carried approval came from, and nothing to compare', () => {
    row(mk('a', 'approved', { review: { ...EMPTY_REVIEW, carriedFrom: { versionId: 'ver0', tag: 'v1.1.0' } } }), { isAdmin: true, meId: 'u1' })
    expect(screen.getByText('from v1.1.0')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Compare vs reference' })).toBeNull()
  })
})

describe('VersionApprovalBar', () => {
  const docs = [mk('a', 'approved'), mk('b', 'submitted'), mk('c', 'in_review', { reviewer: null })]
  it('says how many are approved and filters by a state or by "Needs a reviewer"', async () => {
    const onOnly = vi.fn()
    const onNeeds = vi.fn()
    render(<VersionApprovalBar docs={docs} onOnlyStatus={onOnly} onNeedsReviewer={onNeeds} />)
    expect(screen.getByText(/1 of 3 documents approved/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Ready for approval 1/ }))
    expect(onOnly).toHaveBeenCalledWith('submitted')
    await userEvent.click(screen.getByRole('button', { name: /Needs a reviewer 1/ }))
    expect(onNeeds).toHaveBeenCalled()
  })
  it('says the version is approved when every document is', () => {
    render(<VersionApprovalBar docs={[mk('a', 'approved')]} onOnlyStatus={vi.fn()} onNeedsReviewer={vi.fn()} />)
    expect(screen.getByText(/is approved/)).toBeInTheDocument()
  })
})
