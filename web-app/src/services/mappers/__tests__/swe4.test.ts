import { describe, expect, it } from 'vitest'
import { ApiRichDocumentSchema, mapRichDocument } from '../document'
import { docxFileName } from '../../../lib/docTree'

// A SWE.4 render as api/services/swe4_render.py sends it: one unit, one test spec.
const swe4 = {
  cover: {
    project_name: 'P', subtitle: 'Software Unit Test Specification', version: 'v1',
    layer: 'Layer1', group: 'Layer1.Lib', standard: 'ASPICE_L2', process: 'SWE.4',
  },
  toc: [{ id: 'intro', number: '1', title: 'Introduction', level: 1 }],
  sections: [{
    id: 'test_spec', number: '2', title: 'Software Unit Test Specification', level: 1, type: 'richtext',
    content: null, table: null, image_url: null, mermaid: null,
    children: [{
      id: 's4-2-1-1-1', number: '2.1.1.1', title: 'Lib-libAdd', level: 4, type: 'test_spec',
      content: 'Adds two values.',
      table: { headers: ['Field', 'Value'], rows: [['Eval. Equipment Name', 'Emulator']] },
      image_url: null, mermaid: null, children: [],
      test_spec: {
        test_case_id: 'TC_1', generation_method: 'Analysis of Requirements', return_type: 'int',
        equipment: 'Emulator', platform: 'VectorCAST', priority: 'Medium', environment: 'Emulator',
        precondition: { mocks: ['libClip()'], parameters: ['int a'], globals: [] },
        inputs: ['int a[-0x80000000-0x7FFFFFFF]'],
        steps: [{ number: '1', text: 'Issue function libAdd with inputs a.' }, { number: '2', text: 'Return a.' }],
        expected: [{ text: 'Successfully returned a', steps: ['2'] }],
        expected_note: null,
      },
    }],
  }],
  meta: {
    pipeline_data_available: true, model_data_available: true, source: 'pipeline',
    layers: ['Layer1'], components: ['Layer1.Lib'], units_total: 1, functions_total: 1, globals_total: 0,
  },
  test_summary: { units: 1, function_specs: 1, dynamic_specs: 0, mocks: 1, equipment: 'Emulator', platform: 'VectorCAST' },
}

describe('SWE.4 render', () => {
  it('validates against the render schema', () => {
    expect(ApiRichDocumentSchema.safeParse(swe4).success).toBe(true)
  })
  it('maps a test spec with its steps and the step each result names', () => {
    const d = mapRichDocument(ApiRichDocumentSchema.parse(swe4))
    const spec = d.sections[0].children[0]
    expect(spec.type).toBe('test_spec')
    expect(spec.testSpec?.testCaseId).toBe('TC_1')
    expect(spec.testSpec?.precondition.mocks).toEqual(['libClip()'])
    expect(spec.testSpec?.steps.map((s) => s.number)).toEqual(['1', '2'])
    expect(spec.testSpec?.expected[0]).toEqual({ text: 'Successfully returned a', steps: ['2'] })
    expect(spec.testSpec?.expectedNote).toBeNull()
  })
  it('maps the summary strip', () => {
    const d = mapRichDocument(ApiRichDocumentSchema.parse(swe4))
    expect(d.testSummary).toEqual({ units: 1, functionSpecs: 1, dynamicSpecs: 0, mocks: 1, equipment: 'Emulator', platform: 'VectorCAST' })
  })
  it('a SWE.3 render has no summary', () => {
    const { test_summary: _drop, ...swe3 } = swe4
    void _drop
    expect(mapRichDocument(ApiRichDocumentSchema.parse(swe3)).testSummary).toBeNull()
  })
})

describe('docxFileName', () => {
  it("names a component's two documents apart, as the engine names them", () => {
    expect(docxFileName({ process: 'SWE.3', group: 'Layer1.Lib', name: 'Lib' })).toBe('software_detailed_design_Layer1.Lib')
    expect(docxFileName({ process: 'SWE.4', group: 'Layer1.Lib', name: 'Lib' })).toBe('software_unit_test_specification_Layer1.Lib')
  })
})
