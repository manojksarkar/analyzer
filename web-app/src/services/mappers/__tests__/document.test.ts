import { describe, expect, it } from 'vitest'
import { API_BASE_URL } from '../../../lib/http'
import {
  ApiDocumentDetailSchema, mapDocument, mapDocumentDetail, resolveAssetUrl,
  type ApiDocumentDetail,
} from '../document'

const detail: ApiDocumentDetail = {
  id: 'd1',
  name: 'Software Detailed Design',
  subtitle: 'Full',
  process: 'SWE.3',
  layer: 'Layer1',
  group: 'Full',
  status: 'in_review',
  version_id: 'ver3',
  due_date: null,
  assignees: [{ user_id: 'u1', name: 'Alice', initials: 'AL' }],
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-10T00:00:00Z',
  sections: [
    { key: 'b', title: 'B', order: 2, content: 'b', review_state: null, reviewed_by: null, reviewed_at: null },
    { key: 'a', title: 'A', order: 1, content: 'a', review_state: 'accepted', reviewed_by: 'u1', reviewed_at: null },
  ],
  review_progress: { resolved: 1, total: 2 },
}

describe('mapDocument', () => {
  it('resolves version_id to a tag when a lookup is supplied', () => {
    expect(mapDocument(detail, { ver3: 'v1.2.0' }).version).toBe('v1.2.0')
  })
  it('falls back to the raw version_id when no lookup is given', () => {
    expect(mapDocument(detail).version).toBe('ver3')
  })
  it('takes the first assignee as the row assignee', () => {
    expect(mapDocument(detail).assignee).toBe('Alice')
  })
})

describe('mapDocumentDetail', () => {
  it('sorts sections by order and maps review_state', () => {
    const d = mapDocumentDetail(detail)
    expect(d.sections.map((s) => s.key)).toEqual(['a', 'b'])
    expect(d.sections[0].reviewState).toBe('accepted')
    expect(d.reviewProgress).toEqual({ resolved: 1, total: 2 })
  })
})

describe('resolveAssetUrl (default mode — relative path under the API base)', () => {
  it('returns null for an empty ref', () => {
    expect(resolveAssetUrl(null)).toBeNull()
  })
  it('passes an absolute / protocol-relative URL through unchanged', () => {
    expect(resolveAssetUrl('https://cdn.example.com/x.png')).toBe('https://cdn.example.com/x.png')
    expect(resolveAssetUrl('//cdn.example.com/x.png')).toBe('//cdn.example.com/x.png')
  })
  it('joins a relative path onto the API base (single slash)', () => {
    expect(resolveAssetUrl('projects/p1/assets/d.png')).toBe(`${API_BASE_URL}/projects/p1/assets/d.png`)
    expect(resolveAssetUrl('/projects/p1/assets/d.png')).toBe(`${API_BASE_URL}/projects/p1/assets/d.png`)
  })
})

describe('ApiDocumentDetailSchema', () => {
  it('accepts the full detail DTO', () => {
    expect(ApiDocumentDetailSchema.safeParse(detail).success).toBe(true)
  })
  it('tolerates a detail DTO without the optional sections list', () => {
    const noSections: ApiDocumentDetail = {
      id: 'd2', name: 'X', subtitle: '', process: 'SWE.2', layer: 'L', group: 'G',
      status: 'approved', version_id: 'ver1', due_date: null, assignees: [],
      created_at: '2026-06-01T00:00:00Z', updated_at: '2026-06-01T00:00:00Z',
    }
    expect(ApiDocumentDetailSchema.safeParse(noSections).success).toBe(true)
  })
})
