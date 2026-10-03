import { describe, expect, it } from 'vitest'
import {
  ApiReviewEventSchema, EMPTY_REVIEW, mapDocReview, mapReviewEvent, mapSkipped, mapVersionReview,
  type ApiReviewEvent,
} from '../approval'
import { ApiNotificationSchema, mapNotification } from '../notification'

// REVIEW_APPROVE_API_SPEC §2 Event, as A10 / A11 send it.
const event: ApiReviewEvent = {
  id: 'rev1a2b3c4d', document_id: 'docc1442', version_id: 'verf6223ff0', kind: 'approved',
  actor: { user_id: 'u1', name: 'Alice Admin', initials: 'AA' }, at: '2026-10-01T09:40:00+00:00',
  comment: 'Corrections read well.', payload: { docx_sha256: '9f2c', direct: false },
}

describe('mapReviewEvent', () => {
  it('maps the wire event', () => {
    expect(mapReviewEvent(event)).toEqual({
      id: 'rev1a2b3c4d', documentId: 'docc1442', versionId: 'verf6223ff0', kind: 'approved',
      actor: { userId: 'u1', name: 'Alice Admin', initials: 'AA' }, at: '2026-10-01T09:40:00+00:00',
      comment: 'Corrections read well.', payload: { docx_sha256: '9f2c', direct: false },
    })
  })
  it('reads a run event: no actor, and a null payload as empty', () => {
    const e = mapReviewEvent({ ...event, kind: 'generated', actor: null, comment: null, payload: null })
    expect(e.actor).toBeNull()
    expect(e.payload).toEqual({})
  })
  it('keeps the document an A11 event names', () => {
    const e = mapReviewEvent({ ...event, document: { id: 'docc1442', name: 'Util', process: 'SWE.3' } })
    expect(e.document).toEqual({ id: 'docc1442', name: 'Util', process: 'SWE.3' })
  })
  it('validates the contract shape', () => {
    expect(ApiReviewEventSchema.safeParse(event).success).toBe(true)
    expect(ApiReviewEventSchema.safeParse({ ...event, at: undefined }).success).toBe(false)
  })
})

describe('mapDocReview', () => {
  it('reads no review as nothing said and nothing approved', () => {
    expect(mapDocReview(undefined)).toEqual(EMPTY_REVIEW)
    expect(mapDocReview(null)).toEqual(EMPTY_REVIEW)
  })
  it('maps the comments, the approval and the last event', () => {
    const r = mapDocReview({
      comment: 'Checked.', changes_comment: null,
      approved_by: { user_id: 'u1', name: 'Alice Admin', initials: 'AA' }, approved_at: '2026-10-01T09:40:00+00:00',
      approval_comment: 'Fine.', docx_sha256: 'abc', carried_from: null, last_event: event,
    })
    expect(r.approvedBy?.userId).toBe('u1')
    expect(r.approvalComment).toBe('Fine.')
    expect(r.lastEvent?.kind).toBe('approved')
  })
})

describe('mapVersionReview', () => {
  it('is null when the API sends none', () => {
    expect(mapVersionReview(undefined)).toBeNull()
  })
})

describe('mapSkipped', () => {
  it('maps what A2 / A9 skipped, and why', () => {
    expect(mapSkipped([{ document_id: 'd2', code: 'WRONG_STATE', message: 'In review' }]))
      .toEqual([{ documentId: 'd2', code: 'WRONG_STATE', message: 'In review' }])
  })
})

describe('mapNotification (A16)', () => {
  const n = {
    id: 'n1', project_id: 'p1', type: 'review_submitted', message: 'Bob submitted Util (SWE.3) for approval',
    document_id: 'd1', read_at: null, created_at: '2026-10-01T09:40:00Z',
  }
  it('names the document it is about', () => {
    expect(mapNotification(n).documentId).toBe('d1')
    expect(mapNotification({ ...n, document_id: null }).documentId).toBeNull()
  })
  it('keeps read ones (all=true): read_at set', () => {
    expect(mapNotification({ ...n, read_at: '2026-10-01T10:00:00Z' }).readAt).toBe('2026-10-01T10:00:00Z')
  })
  it('validates the contract shape', () => {
    expect(ApiNotificationSchema.safeParse(n).success).toBe(true)
  })
})
