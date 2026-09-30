import { describe, expect, it } from 'vitest'
import { API_BASE_URL } from '../../../lib/http'
import {
  ApiDocumentDetailSchema, ApiRichDocumentSchema, mapDocument, mapDocumentDetail, mapFlowchart, resolveAssetUrl,
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
