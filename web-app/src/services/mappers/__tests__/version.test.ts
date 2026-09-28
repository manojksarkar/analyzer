import { describe, expect, it } from 'vitest'
import { mapVersion, type ApiVersion } from '../version'

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

  it('reads a draft as not run — its run has not finished, or it was only tagged', () => {
    expect(mapVersion({ ...base, status: 'draft', docs_count: 0 }).pageState).toBe('never')
  })
})
