import { describe, expect, it } from 'vitest'
import { ApiRunSettingsSchema, ApiVersionComponentsSchema, mapRunSettings, mapVersionComponents } from '..'

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

  it('stale stays stale, and the layer flags are mapped (parsed when an older API does not say)', () => {
    const v = mapVersionComponents(ApiVersionComponentsSchema.parse({
      ...BODY,
      components: [
        { ...BODY.components[0], state: 'stale' },
        { ...BODY.components[0], component: 'Layer2.Gpio', layer: 'Layer2', name: 'Gpio', state: 'not_requested',
          in_model: false, layer_parsed: false, documents: [] },
      ],
      counts: { stale: 1, not_requested: 1 },
    }))
    expect(v.components[0]).toMatchObject({ state: 'stale', inModel: true, layerParsed: true })
    expect(v.components[1]).toMatchObject({ id: 'Layer2.Gpio', inModel: false, layerParsed: false })
    expect(v.counts).toEqual({ stale: 1, not_requested: 1 })
  })

  it("maps each component's group (from the version's config); null when an older API does not say", () => {
    const v = mapVersionComponents(ApiVersionComponentsSchema.parse({
      ...BODY,
      components: [{ ...BODY.components[0], group: 'My Sample' }, { ...BODY.components[0], group: null }, BODY.components[0]],
    }))
    expect(v.components.map((c) => c.group)).toEqual(['My Sample', null, null])
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

/* GET …/versions/{vid}/run-settings → RunSettings: how a version was made, run by run. */
const RUN_BODY = {
  version_id: 'ver1', running: true,
  runs: [
    { at: '2026-10-28T09:14:02Z', host: 'build-01', code: '782d749', phases: [1, 1], docType: 'all', components: null,
      llmServer: { provider: 'anthropic', defaultModel: 'claude-sonnet-5-5', baseUrl: 'https://api.anthropic.com',
                   apiKey: 'set', customHeaders: [], timeoutSeconds: 300 },
      headersFromEnvironment: [],
      speedups: { llms: [{ name: 'claude-a', maxConcurrent: 2 }], pacing: 'after', parseWorkers: 'auto -> 4',
                  pictureBatches: false, fastNullCheck: false },
      llvm: { libPath: 'C:/LLVM/bin/libclang.dll', includePath: 'C:/LLVM/include' } },
    { at: '2026-10-28T09:20:45Z', phases: [4, null], docType: 'swe3',
      components: ['Layer1.Math', 'Layer1.Util', 'Layer1.Lib', 'Layer1.App', 'Layer1.Core'],
      llmServer: { provider: 'openai', defaultModel: 'gpt-oss', apiKey: 'none', customHeaders: ['x-dep-ticket'] },
      headersFromEnvironment: ['USER_ID'], speedups: { llms: [], parseWorkers: '1' }, futureField: 1 },
  ],
}

describe('mapRunSettings', () => {
  it('lists the newest run first, in the drawer’s words', () => {
    const r = mapRunSettings(ApiRunSettingsSchema.parse(RUN_BODY))
    expect(r.running).toBe(true)
    expect(r.runs.map((x) => x.what)).toEqual(['Documents (SWE.3)', 'Parse'])
    expect(r.runs[1]).toMatchObject({
      components: 'all components', llm: 'anthropic / claude-sonnet-5-5', endpoint: 'https://api.anthropic.com',
      lanes: [{ name: 'claude-a', atOnce: '2' }], credentials: 'API key set', pacing: 'after',
      parsing: 'auto → 4 files at once', llvm: 'C:/LLVM/bin/libclang.dll', host: 'build-01', code: '782d749',
    })
    expect(r.runs[0]).toMatchObject({
      components: 'Layer1.Math, Layer1.Util, Layer1.Lib and 2 more', endpoint: null, lanes: [],
      credentials: 'API key none · headers x-dep-ticket, USER_ID', parsing: '1 file at once', llvm: null, host: null,
    })
  })
})
