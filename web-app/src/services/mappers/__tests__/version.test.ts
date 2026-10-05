import { describe, expect, it } from 'vitest'
import { ApiVersionSchema, mapVersion, type ApiVersion } from '../version'

const base: ApiVersion = {
  id: 'ver6779ec8c',
  tag: 'v1.0.0',
  commit_sha: '9d4dd0f95f8ae3a1b6aaaa27b227291882eec9e4',
  branch: 'main',
  description: 'Generating…',
  status: 'in_review',
  docs_count: 13,
  created_by: 'u1',
  created_at: '2026-09-28T18:20:38Z',
  review: {
    documents: 13, approved: 4, in_review: 6, submitted: 2, changes_requested: 1, carried: 3,
    approved_by: null, approved_at: null,
  },
}

describe('mapVersion', () => {
  it('maps the wire shape', () => {
    const v = mapVersion(base)
    expect(v.id).toBe('ver6779ec8c')
    expect(v.shortSha).toBe('9d4dd0f')
    expect(v.docsCount).toBe(13)
  })

  it('reads an approved version as complete, and one in review as in review', () => {
    expect(mapVersion({ ...base, status: 'approved' }).pageState).toBe('complete')
    expect(mapVersion(base).pageState).toBe('in_review')
  })

  it('a version the CLI made (no branch, description or author) still maps', () => {
    const v = mapVersion(ApiVersionSchema.parse({ ...base, branch: null, description: null, created_by: null }))
    expect(v.branch).toBe('')
    expect(v.description).toBe('')
  })

  it('reads a draft as not run — its run has not finished, or it was only tagged', () => {
    expect(mapVersion({ ...base, status: 'draft', docs_count: 0 }).pageState).toBe('never')
  })

  it('maps how it was made, and tolerates an API that does not say', () => {
    const v = mapVersion(ApiVersionSchema.parse({ ...base,
      run: { made_by: 'cli', scope: { type: 'layer', names: ['Layer1'] }, doc_type: null, model_only: true } }))
    expect(v.run).toEqual({ madeBy: 'cli', scope: { type: 'layer', names: ['Layer1'] }, docType: null, modelOnly: true })
    expect(mapVersion(base).run).toBeNull()
    expect(mapVersion({ ...base, run: { made_by: null, scope: null, doc_type: 'all', model_only: false } }).run)
      .toEqual({ madeBy: null, scope: null, docType: 'all', modelOnly: false })
  })

  it("carries the run's warnings, and none from an API that does not send them", () => {
    const w = 'Layer1 / G / Ghost: `Layer1/Gone` is not in the checkout'
    expect(mapVersion({ ...base, warnings: [w] }).warnings).toEqual([w])
    expect(mapVersion(base).warnings).toEqual([])
  })

  it('maps the review counts (A14)', () => {
    expect(mapVersion(base).review).toEqual({
      documents: 13, approved: 4, inReview: 6, submitted: 2, changesRequested: 1, carried: 3,
      approvedBy: null, approvedAt: null,
    })
  })

  it('names who approved a fully approved version, and when', () => {
    const v = mapVersion({
      ...base,
      status: 'approved',
      review: { ...base.review, approved: 13, in_review: 0, submitted: 0, changes_requested: 0,
        approved_by: { user_id: 'u1', name: 'Alice Admin', initials: 'AA' }, approved_at: '2026-10-01T09:40:00Z' },
    })
    expect(v.status).toBe('approved')
    expect(v.review?.approvedBy?.name).toBe('Alice Admin')
  })

  it('reads an older `complete` as approved', () => {
    expect(mapVersion({ ...base, status: 'complete' }).status).toBe('approved')
  })
})
