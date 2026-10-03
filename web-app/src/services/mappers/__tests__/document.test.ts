import { describe, expect, it } from 'vitest'
import { API_BASE_URL } from '../../../lib/http'
import {
  ApiDocumentDetailSchema, ApiRichDocumentSchema, mapDocument, mapDocumentDetail, mapFlowchart, resolveAssetUrl,
  type ApiDocumentDetail,
} from '../document'

// A document as every route returns it (REVIEW_APPROVE_API_SPEC §2).
const detail: ApiDocumentDetail = {
  id: 'd1',
  name: 'Software Detailed Design',
  subtitle: 'Full',
  process: 'SWE.3',
  layer: 'Layer1',
  group: 'Full',
  status: 'submitted',
  version_id: 'ver3',
  due_date: null,
  assignees: [{ user_id: 'u1', name: 'Alice', initials: 'AL' }],
  reviewer: { user_id: 'u1', name: 'Alice', initials: 'AL' },
  review: {
    comment: 'Checked every function; corrected 3 texts.',
    changes_comment: null,
    approved_by: null, approved_at: null, approval_comment: null, docx_sha256: null,
    carried_from: null,
    last_event: {
      id: 'rev1', document_id: 'd1', version_id: 'ver3', kind: 'submitted',
      actor: { user_id: 'u1', name: 'Alice', initials: 'AL' }, at: '2026-10-01T09:40:00+00:00',
      comment: 'Checked every function; corrected 3 texts.', payload: {},
    },
  },
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-10T00:00:00Z',
}

describe('mapDocument', () => {
  it('resolves version_id to a tag when a lookup is supplied', () => {
    expect(mapDocument(detail, { ver3: 'v1.2.0' }).version).toBe('v1.2.0')
  })
  it('falls back to the raw version_id when no lookup is given', () => {
    expect(mapDocument(detail).version).toBe('ver3')
  })
  it('maps the one reviewer, and names them as the row assignee', () => {
    const d = mapDocument(detail)
    expect(d.reviewer).toEqual({ userId: 'u1', name: 'Alice', initials: 'AL' })
    expect(d.assignee).toBe('Alice')
  })
  it('reads no reviewer as "Needs a reviewer" (null)', () => {
    const d = mapDocument({ ...detail, reviewer: null, assignees: [] })
    expect(d.reviewer).toBeNull()
    expect(d.assignee).toBeUndefined()
  })
  it('maps the review: the comment and the last event', () => {
    const d = mapDocument(detail)
    expect(d.status).toBe('submitted')
    expect(d.review.comment).toBe('Checked every function; corrected 3 texts.')
    expect(d.review.lastEvent).toMatchObject({ kind: 'submitted', actor: { userId: 'u1' }, documentId: 'd1' })
  })
  it('maps an approval and where it was carried from', () => {
    const d = mapDocument({
      ...detail,
      status: 'approved',
      review: {
        ...detail.review,
        approved_by: { user_id: 'u9', name: 'Ada Admin', initials: 'AA' },
        approved_at: '2026-10-01T10:00:00+00:00',
        approval_comment: 'Reads well.',
        docx_sha256: '9f2c',
        carried_from: { version_id: 'ver2', tag: 'v1.1.0' },
      },
    })
    expect(d.review.approvedBy?.name).toBe('Ada Admin')
    expect(d.review.docxSha256).toBe('9f2c')
    expect(d.review.carriedFrom).toEqual({ versionId: 'ver2', tag: 'v1.1.0' })
  })
  it('reads an older state word as the nearest of the four', () => {
    expect(mapDocument({ ...detail, status: 'complete' }).status).toBe('approved')
    expect(mapDocument({ ...detail, status: 'never' }).status).toBe('in_review')
  })
})

describe('mapDocumentDetail', () => {
  it('is the document itself (review is per document, not per section)', () => {
    expect(mapDocumentDetail(detail)).toEqual(mapDocument(detail))
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
  it('accepts the document of the contract', () => {
    expect(ApiDocumentDetailSchema.safeParse(detail).success).toBe(true)
  })
  it('accepts a document nobody reviews, with leftover placeholder sections', () => {
    const doc = { ...detail, reviewer: null, assignees: [], sections: [{ key: 'a' }], review_progress: { resolved: 0, total: 1 } }
    expect(ApiDocumentDetailSchema.safeParse(doc).success).toBe(true)
  })
  it('refuses a document without its review (the API must send it)', () => {
    const { review: _review, ...noReview } = detail
    void _review
    expect(ApiDocumentDetailSchema.safeParse(noReview).success).toBe(false)
  })
})

describe('mapFlowchart (one flowchart SVG in a function table)', () => {
  it('maps a drawn chart: its SVG under the API base, its size and box count', () => {
    const fc = mapFlowchart({
      label: 'int add(int a)', status: 'drawn', image_url: 'projects/p1/documents/d1/assets/flowcharts/Math_add.svg',
      width: 400, height: 200, boxes: 7,
    })
    expect(fc).toEqual({
      label: 'int add(int a)', status: 'drawn',
      imageUrl: `${API_BASE_URL}/projects/p1/documents/d1/assets/flowcharts/Math_add.svg`,
      width: 400, height: 200, boxes: 7, flowchartId: null, editable: false,
    })
  })
  it('names the chart for the label editor, and versions its URL by its drawing', () => {
    const fc = mapFlowchart({
      label: 'f()', status: 'drawn', image_url: 'projects/p1/documents/d1/assets/flowcharts/U_f.svg',
      source_hash: 'abc123', flowchart_id: 'C|U|f|', editable: true,
    })
    expect(fc.flowchartId).toBe('C|U|f|')
    expect(fc.editable).toBe(true)
    expect(fc.imageUrl).toBe(`${API_BASE_URL}/projects/p1/documents/d1/assets/flowcharts/U_f.svg?v=abc123`)
  })
  it('is not editable without an id', () => {
    expect(mapFlowchart({ label: 'f()', image_url: 'x.svg', editable: true }).editable).toBe(false)
  })
  it('keeps too_large with no image', () => {
    const fc = mapFlowchart({ label: 'f()', status: 'too_large', image_url: null, boxes: 612 })
    expect(fc.status).toBe('too_large')
    expect(fc.imageUrl).toBeNull()
    expect(fc.boxes).toBe(612)
  })
  it('is missing when there is no picture, whatever the status says', () => {
    expect(mapFlowchart({ label: 'f()', status: 'drawn', image_url: null }).status).toBe('missing')
    expect(mapFlowchart({ label: 'f()', status: 'something-new' }).status).toBe('missing')
  })
  it('reads an API from before SVGs: a picture is drawn, the DOT is ignored', () => {
    const old = ApiRichDocumentSchema.shape.sections.element
    const section = old.parse({
      id: 's', number: '1', title: 'T', level: 4, type: 'flowchart_table', content: null, table: null,
      children: [],
      flowchart_table: {
        description: 'd', risk: 'r', capacity: 'c', input_name: 'i', output_name: 'o',
        flowcharts: [
          { label: 'a()', image_url: 'x/a.png', mermaid: null },
          { label: 'b()', image_url: null, mermaid: 'digraph G { N1; }' },
        ],
      },
    })
    const flowcharts = section.flowchart_table!.flowcharts.map(mapFlowchart)
    expect(flowcharts.map((f) => f.status)).toEqual(['drawn', 'missing'])
    expect(flowcharts[0]).toMatchObject({ width: null, height: null, boxes: 0 })
  })
})
