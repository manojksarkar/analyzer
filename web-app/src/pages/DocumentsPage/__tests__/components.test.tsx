import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { emptyReview as EMPTY_REVIEW } from '../../../test/factories'
import { DocRow } from '../components/DocRow'
import { VersionApprovalBar } from '../components/VersionApprovalBar'
import { BulkApproveDialog } from '../components/BulkApproveDialog'
import type { Document, OutOfDateFile } from '../../../types'

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }
const mk = (id: string, status: Document['status'], over: Partial<Document> = {}): Document => ({
  id, name: `Doc ${id}`, process: 'SWE.3', status, version: 'v1.2.0', versionId: 'ver1', updatedAt: '',
  reviewer: bob, review: EMPTY_REVIEW, ...over,
})

/** Its Word file out of date: 2 corrections not in it. */
const BEHIND: OutOfDateFile = {
  documentId: 'a', component: 'L1.A', name: 'Doc a', docType: 'SWE.3', why: ['corrections'], corrections: 2,
  pictures: 0, layer: null, updating: false,
}

function row(doc: Document, role: { isAdmin: boolean; meId: string }, word: {
  file?: OutOfDateFile; updating?: boolean; blocked?: string
} = {}) {
  const handlers = {
    onToggle: vi.fn(), onOpen: vi.fn(), onReview: vi.fn(), onCompare: vi.fn(), onDownload: vi.fn(),
    onCorrected: vi.fn(), onAssign: vi.fn(), onClaim: vi.fn(),
  }
  render(
    <table><tbody>
      <DocRow doc={doc} selected={false} isAdmin={role.isAdmin} isDeveloper={!role.isAdmin} meId={role.meId}
        nameOf={() => undefined} claimPending={false} wordFile={word.file} updating={word.updating}
        correctedBlocked={word.blocked} {...handlers} />
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
  it('out of date: a menu — the corrected file (updated first) or the current file (why in its line)', async () => {
    const user = userEvent.setup()
    const h = row(mk('a', 'in_review'), { isAdmin: false, meId: 'u2' }, { file: BEHIND })
    const dl = screen.getByRole('button', { name: /Download DOCX \(out of date/ })
    expect(dl).toHaveAttribute('title', 'Out of date: 2 corrections not in it')
    await user.click(dl)
    expect(await screen.findByRole('menuitem', { name: /Corrected file Updated first/ })).toBeInTheDocument()
    await user.click(screen.getByRole('menuitem', { name: /Current file 2 corrections not in it/ }))
    expect(h.onDownload).toHaveBeenCalled()
    await user.click(dl)
    await user.click(await screen.findByRole('menuitem', { name: /Corrected file/ }))
    expect(h.onCorrected).toHaveBeenCalled()
  })
  it('the corrected file is off while nothing can start, and its line says why', async () => {
    const user = userEvent.setup()
    row(mk('a', 'in_review'), { isAdmin: false, meId: 'u2' }, { file: BEHIND, blocked: 'Update after the generation of v1.2.0 ends.' })
    await user.click(screen.getByRole('button', { name: /Download DOCX \(out of date/ }))
    const item = await screen.findByRole('menuitem', { name: /Corrected file Update after the generation of v1\.2\.0 ends\./ })
    expect(item).toHaveAttribute('data-disabled')
  })
  it('updating: a spinner in its place', () => {
    row(mk('a', 'in_review'), { isAdmin: false, meId: 'u2' }, { file: BEHIND, updating: true })
    expect(screen.getByRole('img', { name: 'Updating…' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Download DOCX/ })).toBeNull()
  })
  it('Download is plain when the Word file is up to date, and for an approved document (its approved file)', () => {
    row(mk('a', 'in_review'), { isAdmin: false, meId: 'u2' })
    row(mk('b', 'approved'), { isAdmin: false, meId: 'u2' }, { file: { ...BEHIND, documentId: 'b' } })
    expect(screen.getAllByRole('button', { name: 'Download DOCX' })).toHaveLength(2)
  })
  it('shows where a carried approval came from, and nothing to compare', () => {
    row(mk('a', 'approved', { review: { ...EMPTY_REVIEW, carriedFrom: { versionId: 'ver0', tag: 'v1.1.0' } } }), { isAdmin: true, meId: 'u1' })
    expect(screen.getByText('from v1.1.0')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Compare vs reference' })).toBeNull()
  })
})

describe('BulkApproveDialog — Word files out of date (D10, W7)', () => {
  const plan = {
    ready: [mk('a', 'submitted')], checking: [],
    behind: [mk('b', 'submitted'), mk('c', 'submitted')],
    skipped: [{ doc: mk('d', 'in_review'), reason: 'not ready for approval' }],
  }
  const show = (update: { going: boolean; blocked: string }) => {
    const onUpdate = vi.fn()
    render(<BulkApproveDialog plan={plan} busy={false} onConfirm={vi.fn()} onClose={vi.fn()} update={{ ...update, onUpdate }} />)
    return onUpdate
  }
  it('names the out-of-date ones with Update them — this dialog starts it, no second dialog', async () => {
    const onUpdate = show({ going: false, blocked: '' })
    expect(screen.getByText(/^2 Word files are out of date\./)).toBeInTheDocument()
    expect(screen.getByText('1 other selected document is not ready for approval.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve 1' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Update them' }))
    expect(onUpdate).toHaveBeenCalled()
  })
  it('updating already: says so', () => {
    show({ going: true, blocked: '' })
    expect(screen.getByText(/2 Word files are out of date\. Updating…/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Update them' })).toBeNull()
  })
  it('while a run holds the version: when it can be updated, instead of the link', () => {
    show({ going: false, blocked: 'Update after the generation of v1.2.0 ends.' })
    expect(screen.getByText(/Update after the generation of v1\.2\.0 ends\./)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Update them' })).toBeNull()
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
  it('in review, says how many it waits for -- "It is approved when every one is" read as nonsense', () => {
    render(<VersionApprovalBar docs={[mk('a', 'approved'), mk('b', 'in_review')]} onOnlyStatus={vi.fn()} onNeedsReviewer={vi.fn()} />)
    expect(screen.getByText(/1 of 2 documents approved\. The version is approved once all 2 are\./)).toBeInTheDocument()
  })
})
