import { describe, expect, it } from 'vitest'
import { bulkApprovePlan, filterDocuments } from '../helpers'
import { emptyReview as EMPTY_REVIEW } from '../../../test/factories'
import type { Document, ExportReadiness } from '../../../types'

const bob = { userId: 'u2', name: 'Bob Kumar', initials: 'BK' }
const mk = (id: string, status: Document['status'], extra: Partial<Document> = {}): Document => ({
  id, name: id, process: 'SWE.3', status, version: 'v1', versionId: 'ver1', updatedAt: '',
  reviewer: bob, review: EMPTY_REVIEW, ...extra,
})
const r9 = (stale: boolean, pendingRenders = 0): ExportReadiness => ({
  stale, explanation: null, overrideCount: 0, pendingRenders, failedRenders: 0, reexport: null,
})

describe('bulkApprovePlan', () => {
  const ready = mk('a', 'submitted')
  const ready2 = mk('b', 'submitted')
  const inReview = mk('c', 'in_review')
  const approved = mk('d', 'approved')

  it('takes only Ready for approval when the version is up to date; skips the rest, saying why', () => {
    const plan = bulkApprovePlan([ready, inReview, approved, ready2], {
      versionReadiness: r9(false), readinessById: {}, reexporting: false,
    })
    expect(plan.ready.map((d) => d.id)).toEqual(['a', 'b'])
    expect(plan.skipped.map((s) => [s.doc.id, s.reason])).toEqual([
      ['c', 'not ready for approval'], ['d', 'already approved'],
    ])
    expect(plan.checking).toEqual([])
  })

  it('checks each document when the version is stale: one with missing corrections is skipped', () => {
    const plan = bulkApprovePlan([ready, ready2], {
      versionReadiness: r9(true), readinessById: { a: r9(false), b: r9(true) }, reexporting: false,
    })
    expect(plan.ready.map((d) => d.id)).toEqual(['a'])
    expect(plan.skipped).toEqual([{ doc: ready2, reason: 'its Word file is missing corrections' }])
  })

  it('one rule, `stale`: a picture owed for a flowchart its Word file does not embed does not block', () => {
    // The server folds an owed picture into `stale` when the document embeds the flowcharts.
    expect(bulkApprovePlan([ready], {
      versionReadiness: r9(true), readinessById: { a: r9(false, 1) }, reexporting: false,
    }).ready.map((d) => d.id)).toEqual(['a'])
    const plan = bulkApprovePlan([ready], {
      versionReadiness: r9(true), readinessById: { a: r9(true, 1) }, reexporting: false,
    })
    expect(plan.ready).toEqual([])
    expect(plan.skipped[0].reason).toBe('its Word file is missing corrections')
  })

  it('waits for a document whose check has not come back, and skips one that failed', () => {
    const plan = bulkApprovePlan([ready, ready2], {
      versionReadiness: r9(true), readinessById: {}, failed: new Set(['b']), reexporting: false,
    })
    expect(plan.checking).toEqual([ready])
    expect(plan.skipped).toEqual([{ doc: ready2, reason: 'its Word file could not be checked' }])
  })

  it('approves nothing while a re-export runs', () => {
    const plan = bulkApprovePlan([ready], { versionReadiness: r9(false), readinessById: {}, reexporting: true })
    expect(plan.ready).toEqual([])
    expect(plan.skipped[0].reason).toBe('a re-export is running')
  })
})

describe('filterDocuments', () => {
  const docs = [
    mk('a', 'submitted'),
    mk('b', 'in_review', { reviewer: null }),
    mk('c', 'approved', { process: 'SWE.4' }),
  ]
  const none = { process: 'All', statuses: new Set<Document['status']>(), reviewer: '', search: '' }
  it('filters by state, reviewer (incl. Needs a reviewer), process and name', () => {
    expect(filterDocuments(docs, { ...none, statuses: new Set(['submitted', 'approved']) }).map((d) => d.id)).toEqual(['a', 'c'])
    expect(filterDocuments(docs, { ...none, reviewer: 'none' }).map((d) => d.id)).toEqual(['b'])
    expect(filterDocuments(docs, { ...none, reviewer: 'u2' }).map((d) => d.id)).toEqual(['a', 'c'])
    expect(filterDocuments(docs, { ...none, process: 'SWE.4' }).map((d) => d.id)).toEqual(['c'])
    expect(filterDocuments(docs, { ...none, search: 'B' }).map((d) => d.id)).toEqual(['b'])
  })
})
