import { describe, expect, it } from 'vitest'
import { ApiVersionComponentsSchema, mapVersionComponents } from '..'

/* GET …/versions/{vid}/components → VersionComponents (staged generation). */

const BODY = {
  version_id: 'ver1',
  components: [{
    component: 'Layer1.Math', layer: 'Layer1', name: 'Math', state: 'generated', in_model: true, error: null,
    documents: [{ id: 'd1', process: 'SWE.3', status: 'approved' }],
  }],
  counts: { generated: 1, bogus: 2 },
  run: { command: 'generate', alive: false, stopped: true, outcome: 'running', done: 10, total: 40 },
}

describe('mapVersionComponents', () => {
  it('maps the wire shape', () => {
    const v = mapVersionComponents(ApiVersionComponentsSchema.parse(BODY))
    expect(v.components[0]).toMatchObject({ id: 'Layer1.Math', layer: 'Layer1', name: 'Math', state: 'generated', inModel: true })
    expect(v.components[0].documents).toEqual([{ id: 'd1', process: 'SWE.3', status: 'approved' }])
    expect(v.run).toMatchObject({ command: 'generate', stopped: true, alive: false, done: 10, total: 40, stage: null })
  })

  it('an unknown state reads as not generated, and a missing run as none', () => {
    const v = mapVersionComponents(ApiVersionComponentsSchema.parse({
      ...BODY, components: [{ ...BODY.components[0], state: 'weird' }], run: null,
    }))
    expect(v.components[0].state).toBe('not_requested')
    expect(v.run).toBeNull()
    expect(v.counts).toEqual({ generated: 1, not_requested: 2 })
  })
})
