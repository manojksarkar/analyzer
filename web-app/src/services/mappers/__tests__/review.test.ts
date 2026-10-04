import { describe, expect, it } from 'vitest'
import {
  ApiExportReadinessSchema, ApiRegenerationQueueSchema, ApiRichDocumentSchema, ApiSlotSchema,
  mapExportReadiness, mapRegenerationQueue, mapRichDocument, mapSlot, mapSlotSave,
} from '../index'
import { describeSave } from '../../../hooks/useReview'

const slot = {
  slotKind: 'description', slotKey: 'C|U|f|int', text: 'Adds.', llmText: 'Adds.', humanText: null,
  isOverridden: false, isOrphaned: false, canUndo: false, updatedBy: null, updatedAt: null,
}

describe('mapSlot (one correctable text, the shape every review route returns)', () => {
  it('maps the address and the state', () => {
    expect(ApiSlotSchema.safeParse(slot).success).toBe(true)
    expect(mapSlot({ ...slot, isOverridden: true, canUndo: true, humanText: 'Adds a.', updatedBy: 'u1' })).toEqual({
      kind: 'description', key: 'C|U|f|int', text: 'Adds.', llmText: 'Adds.', humanText: 'Adds a.',
      isOverridden: true, isOrphaned: false, canUndo: true, updatedBy: 'u1', updatedAt: null,
    })
  })
  it('keeps a behaviour row’s bullets and ids', () => {
    const s = mapSlot({ ...slot, slotKind: 'behaviourDescription', bullets: ['a', 'b'], functionId: 'F', externalCallerId: 'X' })
    expect(s.bullets).toEqual(['a', 'b'])
    expect([s.functionId, s.externalCallerId]).toEqual(['F', 'X'])
  })
  it('reads a save’s answer', () => {
    const r = mapSlotSave({ ...slot, previousText: 'Old.', firstEdit: true,
      queuedForRegeneration: [{ slotKind: 'unitDescription', slotKey: 'C|U' }] })
    expect(r.previousText).toBe('Old.')
    expect(describeSave(r)).toBe('You replaced “Old.”. The next run rewrites 1 text that depends on it: 1 unit description.')
  })
})

describe('mapRegenerationQueue (R10)', () => {
  it('maps each queued text, its reason and the correction that caused it', () => {
    const api = {
      pending: [{
        slotKind: 'description', slotKey: 'L1.App|AppMain|App_Start|void',
        reason: 'its description was written with this function as context',
        causedBy: { slotKind: 'description', slotKey: 'L2.Gpio|GpioDrv|Gpio_Init|void' },
        requestedAt: '2026-09-18T09:14:22Z',
      }],
      total: 1,
    }
    expect(ApiRegenerationQueueSchema.safeParse(api).success).toBe(true)
    expect(mapRegenerationQueue(api)).toEqual([{
      slotKind: 'description', slotKey: 'L1.App|AppMain|App_Start|void',
      reason: 'its description was written with this function as context',
      causedBy: { slotKind: 'description', slotKey: 'L2.Gpio|GpioDrv|Gpio_Init|void' },
      requestedAt: '2026-09-18T09:14:22Z',
    }])
  })
})

describe('mapExportReadiness (R9)', () => {
  it('maps staleness and the latest re-export', () => {
    const api = {
      stale: true, reason: 'overrides newer', explanation: 'x', overrideCount: 3, pendingRenders: 0, failedRenders: 1,
      reexport: { jobId: 'j1', status: 'running', startedAt: '2026-09-30T20:00:00Z', completedAt: null, errorMessage: null },
      newestOverrideAt: null, oldestDerivationAt: null,
    }
    expect(ApiExportReadinessSchema.safeParse(api).success).toBe(true)
    const r = mapExportReadiness(api)
    expect(r.overrideCount).toBe(3)
    expect(r.reexport?.status).toBe('running')
  })
})

describe('the render carries each text’s slot', () => {
  it('maps cell slots, a function’s slots and a flowchart’s id', () => {
    const doc = {
      cover: { project_name: 'P', subtitle: 's', version: 'v1', layer: 'L', group: 'C' },
      toc: [],
      meta: { pipeline_data_available: true, model_data_available: true, source: 'pipeline', layers: [], components: [],
        units_total: 1, functions_total: 1, globals_total: 0 },
      sections: [
        { id: 'C|U-iface', number: '2.1.1.2', title: 'unit interface', level: 4, type: 'table', content: null,
          table: { headers: ['a', 'Information'], rows: [['IF_1', 'Adds.']], cell_slots: [[null, slot]] }, children: [] },
        { id: 'C|U-fn-f', number: '2.1.1.3', title: 'U-f', level: 4, type: 'flowchart_table', content: 'Adds.', table: null,
          children: [],
          flowchart_table: { description: 'Adds.', risk: 'Medium', capacity: 'Common', input_name: 'x', output_name: 'y',
            flowcharts: [{ label: 'int f()', image_url: 'a.svg', flowchart_id: 'C|U|f|int', editable: true }],
            description_slot: slot, input_name_slot: { ...slot, slotKind: 'behaviourInputName', text: '' }, output_name_slot: null } },
      ],
    }
    expect(ApiRichDocumentSchema.safeParse(doc).success).toBe(true)
    const [table, fn] = mapRichDocument(doc).sections
    expect(table.table?.cellSlots?.[0][1]?.key).toBe('C|U|f|int')
    expect(table.table?.cellSlots?.[0][0]).toBeNull()
    expect(fn.flowchartTable?.descriptionSlot?.text).toBe('Adds.')
    expect(fn.flowchartTable?.inputNameSlot?.kind).toBe('behaviourInputName')
    expect(fn.flowchartTable?.outputNameSlot).toBeNull()
    expect(fn.flowchartTable?.flowcharts[0].editable).toBe(true)
  })
  it('reads an API from before slots: no slots, nothing editable', () => {
    const [s] = mapRichDocument({
      cover: { project_name: 'P', subtitle: 's', version: 'v1', layer: 'L', group: 'C' }, toc: [],
      meta: { pipeline_data_available: true, model_data_available: true, source: 'pipeline', layers: [], components: [],
        units_total: 0, functions_total: 0, globals_total: 0 },
      sections: [{ id: 't', number: '1', title: 'T', level: 1, type: 'table', content: null,
        table: { headers: ['a'], rows: [['x']] }, children: [] }],
    }).sections
    expect(s.table?.cellSlots).toBeUndefined()
    expect(s.contentSlot).toBeNull()
  })
})
