import { describe, expect, it } from 'vitest'
import { concernsMe, foldRunEvents, myReviews, reviewQueues } from '../helpers'
import { emptyReview as EMPTY_REVIEW } from '../../../test/factories'
import type { Document, ReviewEvent } from '../../../types'

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }
const mk = (id: string, status: Document['status'], reviewer: typeof bob | null = bob): Document => ({
  id, name: id, process: 'SWE.3', status, version: 'v1', versionId: 'ver1', updatedAt: '',
  reviewer, review: EMPTY_REVIEW,
})
const ev = (id: string, kind: ReviewEvent['kind'], extra: Partial<ReviewEvent> = {}): ReviewEvent => ({
  id, documentId: 'd1', versionId: 'v2', kind, actor: null, at: '2026-10-01T09:00:00Z', comment: null, payload: {}, ...extra,
})

describe('reviewQueues', () => {
  it("splits the admin's work: ready, needs a reviewer, changes requested", () => {
    const q = reviewQueues([mk('a', 'submitted'), mk('b', 'in_review', null), mk('c', 'changes_requested'),
      mk('d', 'approved', null), mk('e', 'in_review')])
    expect(q.ready.map((d) => d.id)).toEqual(['a'])
    expect(q.needsReviewer.map((d) => d.id)).toEqual(['b'])
    expect(q.changes.map((d) => d.id)).toEqual(['c'])
  })
})

describe('myReviews', () => {
  it('lists my documents, what needs me first, and counts what needs me now', () => {
    const r = myReviews([mk('a', 'approved'), mk('b', 'submitted'), mk('c', 'in_review'),
      mk('d', 'changes_requested'), mk('e', 'in_review', null)], 'u2')
    expect(r.docs.map((d) => d.id)).toEqual(['d', 'c', 'b', 'a'])
    expect(r.toDo).toBe(2)
  })
  it('is nobody without a user', () => {
    expect(myReviews([mk('a', 'in_review')], '').docs).toEqual([])
  })
})

describe('foldRunEvents', () => {
  it("reads a run's per-document events as one line", () => {
    const lines = foldRunEvents([
      ev('1', 'approved'), ev('2', 'generated'), ev('3', 'generated'), ev('4', 'generated'),
      ev('5', 'carried'), ev('6', 'carried'), ev('7', 'generated', { versionId: 'v1' }),
    ])
    expect(lines.map((l) => [l.event.id, l.count])).toEqual([['1', 1], ['2', 3], ['5', 2], ['7', 1]])
  })
  it('never folds review steps', () => {
    expect(foldRunEvents([ev('1', 'submitted'), ev('2', 'submitted')])).toHaveLength(2)
  })
})

describe('concernsMe', () => {
  const mine = new Set(['d1'])
  it("shows a developer their steps and their documents' steps", () => {
    expect(concernsMe(ev('1', 'approved', { documentId: 'd1' }), mine, 'u2')).toBe(true)
    expect(concernsMe(ev('2', 'approved', { documentId: 'd9' }), mine, 'u2')).toBe(false)
    expect(concernsMe(ev('3', 'claimed', { documentId: 'd9', actor: bob }), mine, 'u2')).toBe(true)
    expect(concernsMe(ev('4', 'assigned', { documentId: 'd9', payload: { from_user_id: 'u2', to_user_id: 'u3' } }), mine, 'u2')).toBe(true)
    expect(concernsMe(ev('5', 'generated', { documentId: 'd9' }), mine, 'u2')).toBe(true)
  })
})
