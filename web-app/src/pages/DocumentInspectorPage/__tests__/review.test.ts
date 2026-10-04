import { describe, expect, it } from 'vitest'
import { reviewAction, whyNot, type ReviewCtx } from '../review'
import type { Document } from '../../../types'

/* The Review tab's one action, for each role and state (REVIEW_APPROVE_DESIGN "Rules"). */

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }
const doc = (status: Document['status'], reviewer: typeof bob | null = bob) => ({ status, reviewer })

const admin: ReviewCtx = { isAdmin: true, meId: 'u1', wordFileStale: false, reexporting: false }
const dev: ReviewCtx = { isAdmin: false, meId: 'u2', wordFileStale: false, reexporting: false }   // Bob
const otherDev: ReviewCtx = { ...dev, meId: 'u3' }

describe('reviewAction — admin', () => {
  it('approved: the approval, and Reopen', () => {
    const a = reviewAction(doc('approved'), admin)
    expect(a.kind).toBe('approved')
    expect(a.canReopen).toBe(true)
  })
  it('no reviewer: Assign', () => {
    expect(reviewAction(doc('in_review', null), admin).kind).toBe('assign')
  })
  it('ready for approval: Approve and Request changes', () => {
    const a = reviewAction(doc('submitted'), admin)
    expect(a.kind).toBe('decide')
    expect(a.approveBlocked).toBeNull()
  })
  it('ready, but the Word file lacks corrections: Approve is off, and says why', () => {
    expect(reviewAction(doc('submitted'), { ...admin, wordFileStale: true }).approveBlocked)
      .toBe('Re-export first: the approved Word file must have every correction')
    expect(reviewAction(doc('submitted'), { ...admin, reexporting: true }).approveBlocked)
      .toBe('Wait for the re-export to finish')
  })
  it('in review: submit for its reviewer, or approve directly', () => {
    const a = reviewAction(doc('in_review'), admin)
    expect(a.kind).toBe('submit')
    expect(a.directApprove).toBe(true)
    expect(a.submitHeading).toBe('Submit for Bob')
  })
  it('changes requested: submit again, no direct approval', () => {
    const a = reviewAction(doc('changes_requested'), admin)
    expect(a.kind).toBe('submit')
    expect(a.directApprove).toBe(false)
    // Said to the reviewer, "Fix it, then submit again"; an admin is not the one asked to fix it.
    expect(a.submitHeading).toBe('Changes requested — submit again for Bob')
  })
})

describe('reviewAction — developer', () => {
  it('no reviewer: Claim', () => {
    expect(reviewAction(doc('in_review', null), dev).kind).toBe('claim')
  })
  it('my document in review: my review and Submit', () => {
    const a = reviewAction(doc('in_review'), dev)
    expect(a.kind).toBe('submit')
    expect(a.submitHeading).toBe('Your review')
    expect(a.directApprove).toBe(false)
  })
  it('my document sent back: fix it, then submit again', () => {
    expect(reviewAction(doc('changes_requested'), dev).submitHeading).toBe('Fix it, then submit again')
  })
  it('ready for approval: waiting for an admin', () => {
    expect(reviewAction(doc('submitted'), dev).kind).toBe('wait')
  })
  it("someone else's document: read only", () => {
    expect(reviewAction(doc('in_review'), otherDev).kind).toBe('read')
    expect(reviewAction(doc('changes_requested'), otherDev).kind).toBe('read')
  })
  it('approved: the approval, no Reopen', () => {
    const a = reviewAction(doc('approved'), dev)
    expect(a.kind).toBe('approved')
    expect(a.canReopen).toBe(false)
  })
})

describe('whyNot', () => {
  it('keeps each step to its role and state', () => {
    expect(whyNot('assign', doc('approved'), admin)).toBe('Approved: reopen it first')
    expect(whyNot('assign', doc('in_review'), dev)).toBe('Only an admin assigns reviewers')
    expect(whyNot('claim', doc('in_review'), dev)).toBe('It has a reviewer')
    expect(whyNot('claim', doc('in_review', null), dev)).toBeNull()
    expect(whyNot('submit', doc('submitted'), dev)).toBe('It is not in review')
    expect(whyNot('submit', doc('in_review'), otherDev)).toBe('Only its reviewer submits it')
    expect(whyNot('submit', doc('in_review', null), admin)).toBe('It needs a reviewer first')
    expect(whyNot('approve', doc('changes_requested'), admin)).toBe('It is not waiting for approval')
    expect(whyNot('approve', doc('submitted'), dev)).toBe('Only an admin approves')
    expect(whyNot('changes', doc('in_review'), admin)).toBe('Only a document ready for approval')
    expect(whyNot('reopen', doc('submitted'), admin)).toBe('It is not approved')
  })
})
