import { describe, expect, it } from 'vitest'
import {
  REVIEW_STATUSES, STATUS_META, approvalLabel, describeEvent, needsReviewer, pageStateStatus,
  reviewCounts, reviewStatusOf, versionStatusKey, versionStatusOf, wordFileOutOfDate, componentWordFileStale,
} from '../reviewStatus'
import { NEEDS_REVIEWER, buildReviewerOptions, matchesReviewer } from '../docTree'
import type { Document, ReviewEvent } from '../../types'

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }

describe('the shared status map', () => {
  it('has one word per state, everywhere', () => {
    expect(REVIEW_STATUSES.map((s) => STATUS_META[s].label))
      .toEqual(['In review', 'Ready for approval', 'Changes requested', 'Approved'])
  })
  it('says what a version or a page is', () => {
    expect(STATUS_META[pageStateStatus('complete')].label).toBe('Approved')
    expect(STATUS_META[pageStateStatus('never')].label).toBe('Not run')
    expect(versionStatusKey('draft', true)).toBe('running')
    expect(versionStatusKey('draft')).toBe('not_run')
  })
  it('reads the wire words', () => {
    expect(reviewStatusOf('submitted')).toBe('submitted')
    expect(reviewStatusOf('changes_requested')).toBe('changes_requested')
    expect(reviewStatusOf('complete')).toBe('approved')
    expect(reviewStatusOf('unchanged')).toBe('in_review')
    expect(versionStatusOf('complete')).toBe('approved')
    expect(versionStatusOf('draft')).toBe('draft')
  })
})

describe('reviewCounts', () => {
  const doc = (status: Document['status'], reviewer: typeof bob | null, carried = false) => ({
    status, reviewer, review: { carriedFrom: carried ? { versionId: 'v1', tag: 'v1.1.0' } : null },
  })
  it('counts each state, who needs a reviewer, and carried approvals', () => {
    const c = reviewCounts([
      doc('approved', bob, true), doc('approved', null), doc('submitted', bob),
      doc('in_review', null), doc('changes_requested', bob),
    ])
    expect(c).toEqual({
      total: 5, approved: 2, submitted: 1, in_review: 1, changes_requested: 1, needsReviewer: 1, carried: 1,
    })
  })
  it('does not count an approved document as needing a reviewer', () => {
    expect(needsReviewer({ status: 'approved', reviewer: null })).toBe(false)
    expect(needsReviewer({ status: 'in_review', reviewer: null })).toBe(true)
  })
})

describe('approvalLabel', () => {
  it('derives the version line', () => {
    expect(approvalLabel(3, 6)).toBe('In review · 3/6 approved')
    expect(approvalLabel(6, 6)).toBe('Approved')
    expect(approvalLabel(0, 0)).toBe('In review · 0/0 approved')
  })
})

describe('describeEvent', () => {
  const ev = (kind: ReviewEvent['kind'], payload: Record<string, unknown> = {}, actor = bob): ReviewEvent => ({
    id: 'e', documentId: 'd1', versionId: 'v2', kind, actor, at: '2026-10-01T09:40:00Z', comment: null, payload,
  })
  const nameOf = (id: string) => ({ u2: 'Bob Kumar', u3: 'Carol Singh' } as Record<string, string>)[id]
  it('says what happened to "it" on the document', () => {
    expect(describeEvent(ev('submitted'))).toEqual({ actor: 'Bob Kumar', text: 'submitted it for approval' })
    expect(describeEvent(ev('approved', { direct: true })).text).toBe('approved it directly, without a submitted review')
    expect(describeEvent(ev('assigned', { from_user_id: 'u2', to_user_id: 'u3' }), { nameOf }).text)
      .toBe('re-assigned it from Bob Kumar to Carol Singh')
    expect(describeEvent(ev('carried', { from_tag: 'v1.1.0' }, null as never))).toEqual({
      actor: null, text: 'Approved in v1.1.0. The content is unchanged, so the approval carries',
    })
  })
  it('names the document in the project feed, and "you" for me', () => {
    const admin = { userId: 'u9', name: 'Ada Admin', initials: 'AA' }
    expect(describeEvent(ev('assigned', { from_user_id: null, to_user_id: 'u2' }, admin), { doc: 'Util (SWE.3)', nameOf, meId: 'u2' }))
      .toEqual({ actor: 'Ada Admin', text: 'assigned you to Util (SWE.3)' })
    expect(describeEvent(ev('claimed'), { doc: 'Util (SWE.3)', meId: 'u2' })).toEqual({ actor: 'You', text: 'claimed Util (SWE.3)' })
    expect(describeEvent(ev('changes_requested'), { doc: 'Util (SWE.3)' }).text).toBe('requested changes to Util (SWE.3)')
  })
})

describe('wordFileOutOfDate (R9)', () => {
  it('one rule: stale. An owed picture is in it when the document embeds the flowcharts', () => {
    expect(wordFileOutOfDate({ stale: true })).toBe(true)
    // A picture owed for a flowchart the Word file does not embed: the server says not stale.
    expect(wordFileOutOfDate({ stale: false, pendingRenders: 2 } as { stale: boolean })).toBe(false)
    expect(wordFileOutOfDate({ stale: false })).toBe(false)
    expect(wordFileOutOfDate(undefined)).toBe(false)
  })
})

describe('componentWordFileStale (R9 staleComponents)', () => {
  it('marks only the components the answer names', () => {
    const r = { stale: true, staleComponents: ['Layer1.Math'] }
    expect(componentWordFileStale(r, 'Layer1.Math')).toBe(true)
    expect(componentWordFileStale(r, 'Layer1.Util')).toBe(false)
    expect(componentWordFileStale({ stale: false, staleComponents: [] }, 'Layer1.Math')).toBe(false)
  })
  it('an API that does not say which: every component of a stale version', () => {
    expect(componentWordFileStale({ stale: true }, 'Layer1.Util')).toBe(true)
    expect(componentWordFileStale(undefined, 'Layer1.Util')).toBe(false)
  })
})

describe('the reviewer filter (docTree)', () => {
  const docs = [{ reviewer: bob }, { reviewer: null }] as Document[]
  it('matches every one, those without a reviewer (`none`), or one reviewer', () => {
    expect(docs.filter((d) => matchesReviewer(d, ''))).toHaveLength(2)
    expect(docs.filter((d) => matchesReviewer(d, NEEDS_REVIEWER))).toEqual([docs[1]])
    expect(docs.filter((d) => matchesReviewer(d, 'u2'))).toEqual([docs[0]])
  })
  it('lists each reviewer once, by name', () => {
    expect(buildReviewerOptions([...docs, { reviewer: bob } as Document])).toEqual([{ value: 'u2', label: 'Bob Kumar' }])
  })
})
