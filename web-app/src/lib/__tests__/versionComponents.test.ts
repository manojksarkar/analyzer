import { describe, expect, it } from 'vitest'
import {
  addsLayer, componentTree, componentsByLayer, filterTree, generationBannerShown, generationSummary, groupOf,
  layerNote, layersAdded, pickable, runActivity, runVerb,
} from '../versionComponents'
import type { ArchLayer, VersionComponent, VersionComponents, VersionRun } from '../../types'

/* Staged generation's pure rules: what the Generation banner says, and how the Components drawer
   lays the components out (lib/versionComponents.ts). */

const one = (id: string, over: Partial<VersionComponent> = {}): VersionComponent => ({
  id, layer: id.split('.')[0], name: id.split('.')[1], state: 'not_requested',
  inModel: true, layerParsed: true, error: null, documents: [], ...over,
})
const DOC = { id: 'd1', process: 'SWE.3', status: 'in_review' as const }
const run = (over: Partial<VersionRun> = {}): VersionRun => ({
  command: 'export', alive: true, stopped: false, outcome: 'running', host: null, startedAt: '2026-10-05T09:00:00Z',
  finishedAt: null, stage: 'flowcharts', done: 38, total: 112, stageStartedAt: null, progressAt: '2026-10-05T10:00:00Z',
  ...over,
})
const view = (components: VersionComponent[], over: Partial<VersionComponents> = {}): VersionComponents => ({
  components, counts: {}, run: null, job: null, ...over,
})

describe('the component helpers', () => {
  const BODY = [one('Layer1.Math', { state: 'generated', documents: [DOC] }), one('Layer1.App'),
    one('Layer1.Util', { state: 'failed' }), one('Layer2.Gpio', { state: 'stopped' })]

  it('groups by layer in order, and only components without documents are pickable', () => {
    expect(componentsByLayer(BODY).map(([l, cs]) => [l, cs.length])).toEqual([['Layer1', 3], ['Layer2', 1]])
    expect(BODY.filter(pickable).map((c) => c.id)).toEqual(['Layer1.App', 'Layer1.Util', 'Layer2.Gpio'])
  })

  it('outside the model: pickable when its layer is to be added, never when the layer is parsed', () => {
    const toAdd = one('Layer3.Can', { inModel: false, layerParsed: false })
    const noSource = one('Layer1.Ghost', { inModel: false, layerParsed: true })
    const stale = one('Layer1.Math', { state: 'stale', documents: [DOC] })
    expect([toAdd, noSource, stale].filter(pickable).map((c) => c.id)).toEqual(['Layer3.Can'])
    expect(addsLayer(toAdd) && !addsLayer(noSource)).toBe(true)
    expect(layersAdded([toAdd, one('Layer2.Lin', { inModel: false, layerParsed: false }), stale])).toEqual(['Layer2', 'Layer3'])
  })

  it('a note only under a layer the model lacks, naming the layers whose documents may go stale', () => {
    const comps = [one('Layer1.Math'), one('Layer3.Can', { inModel: false, layerParsed: false })]
    expect(layerNote('Layer1', comps)).toBeNull()
    expect(layerNote('Layer3', comps)).toMatch(/Generate adds layer Layer3 .*Layer1 documents may be marked stale/)
  })
})

describe('the Generation banner', () => {
  it('names the run by its command', () => {
    expect(runVerb('export')).toBe('Generating documents')
    expect(runVerb('web run')).toBe('Generating documents')
    expect(runVerb('generate')).toBe('Generating documents')
    expect(runVerb('reexport')).toBe('Updating Word files')
    expect(runVerb('resume')).toBe('Resuming document generation')
  })

  it("says the run's stage in words, with its progress", () => {
    expect(runActivity(run())).toBe('drawing flowcharts, 38 of 112')
    expect(runActivity(run({ stage: 'docx_exporter', done: 3, total: 25 }))).toBe('writing Word files, 3 of 25')
    expect(runActivity(run({ stage: 'parser:parse', done: 0, total: 0 }))).toBe('parsing the code')
    // A stage it does not know: the stage itself, separators as spaces.
    expect(runActivity(run({ stage: 'new-stage_name', total: null }))).toBe('new stage name')
    expect(runActivity(run({ stage: null }))).toBe('')
    expect(runActivity(null)).toBe('')
  })

  const comps = [one('Layer1.Math', { state: 'generated', documents: [DOC] }), one('Layer1.App', { state: 'stale', documents: [DOC] }),
    one('Layer1.Util'), one('Layer2.Gpio')]

  it('a run at work: its verb, its stage, when it started — first, whatever else is true', () => {
    const s = generationSummary(view(comps, { run: run(), job: { id: 'j', mode: 'export', status: 'running' } }))
    expect(s).toMatchObject({ total: 4, withDocs: 2, stale: 1 })
    expect(s?.row).toEqual({ kind: 'running', verb: 'Generating documents', activity: 'drawing flowcharts, 38 of 112', startedAt: '2026-10-05T09:00:00Z' })
    // A web job whose run has not started yet: its mode names it, no stage.
    expect(generationSummary(view(comps, { job: { id: 'j', mode: 'reexport', status: 'queued' } }))?.row)
      .toEqual({ kind: 'running', verb: 'Updating Word files', activity: '', startedAt: null })
  })

  it('a run stopped before it finished, or components cut short', () => {
    expect(generationSummary(view(comps, { run: run({ alive: false, stopped: true }) }))?.row)
      .toEqual({ kind: 'stopped', at: '2026-10-05T10:00:00Z', cutShort: 0 })
    expect(generationSummary(view([...comps, one('Layer2.Uart', { state: 'failed' })]))?.row)
      .toEqual({ kind: 'stopped', at: null, cutShort: 1 })
  })

  it('nothing at work: the components without documents; one no run can make does not count', () => {
    const ghost = one('Layer1.Ghost', { inModel: false, layerParsed: true })
    expect(generationSummary(view([...comps, ghost]))?.row).toEqual({ kind: 'missing', missing: 2 })
    const done = [one('Layer1.Math', { state: 'generated', documents: [DOC] }), ghost]
    expect(generationSummary(view(done))?.row).toBeNull()
    expect(generationBannerShown(view(done))).toBe(false)
  })

  it('shown while a row applies; gone once every component has its documents and nothing runs', () => {
    const all = [one('Layer1.Math', { state: 'generated', documents: [DOC] })]
    expect(generationBannerShown(view(all))).toBe(false)
    expect(generationBannerShown(view(all, { run: run({ alive: false, stopped: false, outcome: 'complete' }) }))).toBe(false)
    expect(generationBannerShown(view(all, { run: run() }))).toBe(true)
    // Only out of date: the second row alone.
    expect(generationBannerShown(view([one('Layer1.Math', { state: 'stale', documents: [DOC] })]))).toBe(true)
    expect(generationBannerShown(view([]))).toBe(false)
    expect(generationBannerShown(undefined)).toBe(false)
  })

  it('a version with no documents yet: only when it has a model to make them from', () => {
    const model = [one('Layer1.Math'), one('Layer1.App')]
    const noModel = [one('Layer1.Math', { inModel: false, layerParsed: false })]
    expect(generationBannerShown(view(model), { needsModel: true })).toBe(true)
    expect(generationBannerShown(view(noModel), { needsModel: true })).toBe(false)
    expect(generationBannerShown(view(noModel))).toBe(true)
  })
})

describe('the Components drawer layout', () => {
  const LAYERS: ArchLayer[] = [
    { name: 'Layer2', groups: [{ name: 'Platform', components: [{ name: 'Gpio' }] }] },
    { name: 'Layer1', groups: [
      { name: 'My Sample', components: [{ name: 'Sample Core' }, { name: 'Lib' }] },
      { name: 'Support', components: [{ name: 'Math' }] },
    ] },
  ]

  it("a component's group: the API's, else the project's architecture by layer and name", () => {
    expect(groupOf(one('Layer1.Math', { group: 'From API' }), LAYERS)).toBe('From API')
    // `Sample Core` in the configuration is the folder `Sample-Core`.
    expect(groupOf(one('Layer1.Sample-Core'), LAYERS)).toBe('My Sample')
    expect(groupOf(one('Layer1.Math', { group: null }), LAYERS)).toBe('Support')
    expect(groupOf(one('Layer1.Unknown'), LAYERS)).toBeNull()
    expect(groupOf(one('Layer1.Math'))).toBeNull()
  })

  it("layer → group → chips, in the project's order; ungrouped first, with no heading", () => {
    const tree = componentTree([
      one('Layer1.Lib'), one('Layer1.Math'), one('Layer1.Other'), one('Layer1.Sample-Core'), one('Layer2.Gpio'),
    ], LAYERS)
    expect(tree.map((l) => [l.layer, l.groups.map((g) => [g.name, g.comps.map((c) => c.name)])])).toEqual([
      ['Layer2', [['Platform', ['Gpio']]]],
      ['Layer1', [[null, ['Other']], ['My Sample', ['Lib', 'Sample-Core']], ['Support', ['Math']]]],
    ])
    // The API's group wins over the project's, which may have changed since the version was made.
    const api = componentTree([one('Layer1.Math', { group: 'Old' }), one('Layer1.Lib', { group: 'My Sample' })], LAYERS)
    expect(api[0].groups.map((g) => g.name)).toEqual(['My Sample', 'Old'])
  })

  it('search and "Without documents" hide chips; empty groups and layers go', () => {
    const tree = componentTree([
      one('Layer1.Lib', { state: 'generated', documents: [DOC] }), one('Layer1.Sample-Core'),
      one('Layer1.Math', { state: 'stale', documents: [DOC] }), one('Layer2.Gpio'),
    ], LAYERS)
    const names = (t: ReturnType<typeof filterTree>) => t.map((l) => [l.layer, l.groups.map((g) => [g.name, g.size, g.comps.map((c) => c.name)])])
    expect(names(filterTree(tree, 'sample core', false))).toEqual([['Layer1', [['My Sample', 2, ['Sample-Core']]]]])
    expect(names(filterTree(tree, 'GPIO', false))).toEqual([['Layer2', [['Platform', 1, ['Gpio']]]]])
    expect(names(filterTree(tree, '', true))).toEqual([
      ['Layer2', [['Platform', 1, ['Gpio']]]], ['Layer1', [['My Sample', 2, ['Sample-Core']]]],
    ])
    expect(filterTree(tree, 'nothing', false)).toEqual([])
  })
})
