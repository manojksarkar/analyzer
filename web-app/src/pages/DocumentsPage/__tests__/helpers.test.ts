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
      versionReadiness: r9(false), readinessById: {},
    })
    expect(plan.ready.map((d) => d.id)).toEqual(['a', 'b'])
    expect(plan.skipped.map((s) => [s.doc.id, s.reason])).toEqual([
      ['c', 'not ready for approval'], ['d', 'already approved'],
    ])
    expect(plan.checking).toEqual([])
    expect(plan.behind).toEqual([])
  })

  it('R9 lists the out-of-date Word files: those are behind (offered the update), the rest ready', () => {
    const plan = bulkApprovePlan([ready, ready2], {
      versionReadiness: { ...r9(true), outOfDate: [{ documentId: 'b', component: 'L1.B', name: 'b', docType: 'SWE.3',
        why: ['corrections'], corrections: 1, pictures: 0, layer: null, updating: false }] },
      readinessById: {},
    })
    expect(plan.ready.map((d) => d.id)).toEqual(['a'])
    expect(plan.behind.map((d) => d.id)).toEqual(['b'])
    expect(plan.checking).toEqual([])
  })

  it('an older API: checks each document when the version is stale; an out-of-date one is behind', () => {
    const plan = bulkApprovePlan([ready, ready2], {
      versionReadiness: r9(true), readinessById: { a: r9(false), b: r9(true) },
    })
    expect(plan.ready.map((d) => d.id)).toEqual(['a'])
    expect(plan.behind).toEqual([ready2])
  })

  it('one rule, `stale`: a picture owed for a flowchart its Word file does not embed does not block', () => {
    // The server folds an owed picture into `stale` when the document embeds the flowcharts.
    expect(bulkApprovePlan([ready], {
      versionReadiness: r9(true), readinessById: { a: r9(false, 1) },
    }).ready.map((d) => d.id)).toEqual(['a'])
    const plan = bulkApprovePlan([ready], {
      versionReadiness: r9(true), readinessById: { a: r9(true, 1) },
    })
    expect(plan.ready).toEqual([])
    expect(plan.behind).toEqual([ready])
  })

  it('waits for a document whose check has not come back, and skips one that failed', () => {
    const plan = bulkApprovePlan([ready, ready2], {
      versionReadiness: r9(true), readinessById: {}, failed: new Set(['b']),
    })
    expect(plan.checking).toEqual([ready])
    expect(plan.skipped).toEqual([{ doc: ready2, reason: 'its Word file could not be checked' }])
  })

  it('a document whose Word file an update writes now is behind, not ready', () => {
    const plan = bulkApprovePlan([mk('a', 'submitted', { group: 'L1.A' }), mk('b', 'submitted', { group: 'L1.B' })], {
      versionReadiness: { ...r9(false), outOfDate: [], reexport: { jobId: 'j1', status: 'running', startedAt: null,
        completedAt: null, errorMessage: null, components: ['L1.A'], componentsDone: 0 } },
      readinessById: {},
    })
    expect(plan.behind.map((d) => d.id)).toEqual(['a'])
    expect(plan.ready.map((d) => d.id)).toEqual(['b'])
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
