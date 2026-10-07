import { describe, expect, it } from 'vitest'
import { attentionChip, failureSuperseded, generationItem, type AttentionItem } from '../attention'
import type { ProjectRun, Version, VersionComponents, VersionRun } from '../../types'

/* Needs attention: what the Overview's banners said, as one chip (most pressing first, "+N") --
   and a failed analysis that a later run of its version made good is no longer said. */

const job = { startedAt: '2026-10-07T09:00:00Z', completedAt: '2026-10-07T09:05:00Z' }
const runAt = (startedAt: string, over: Partial<VersionRun> = {}): VersionRun => ({
  command: 'resume', alive: false, stopped: false, outcome: 'complete', host: null, startedAt, finishedAt: null,
  stage: null, done: null, total: null, stageStartedAt: null, progressAt: null, ...over,
})
const comps = (run: VersionRun | null, over: Partial<VersionComponents> = {}): VersionComponents =>
  ({ components: [], counts: {}, run, job: null, resumeAction: null, ...over })

describe('failureSuperseded', () => {
  it('a later run of the version, finished or at work, makes the failure old news', () => {
    expect(failureSuperseded(job, comps(runAt('2026-10-07T10:00:00Z')))).toBe(true)
    expect(failureSuperseded(job, comps(runAt('2026-10-07T10:00:00Z', { alive: true, outcome: 'running' })))).toBe(true)
    expect(failureSuperseded(job, comps(null, { job: { id: 'j2', mode: 'resume', status: 'running' } }))).toBe(true)
  })

  it('not the failed run itself, nor a later one that failed too, nor a version that is gone', () => {
    expect(failureSuperseded(job, comps(runAt('2026-10-07T09:00:30Z', { outcome: 'failed' })))).toBe(false)
    expect(failureSuperseded(job, comps(runAt('2026-10-07T10:00:00Z', { outcome: 'failed' })))).toBe(false)
    expect(failureSuperseded(job, comps(runAt('2026-10-07T08:00:00Z')))).toBe(false)   // before the failure
    expect(failureSuperseded(job, undefined)).toBe(false)
  })
})

const version = (warnings: string[] = []) => ({ id: 'ver3', tag: 'v1.2.0', warnings }) as unknown as Version
const pRun = (alive: boolean, versionId: string) => ({ ...runAt('2026-10-07T10:00:00Z', { alive }), versionId, versionTag: versionId }) as ProjectRun

describe('attentionChip', () => {
  it('nothing: no chip', () => expect(attentionChip([])).toBeNull())

  it('the most pressing first, the rest counted', () => {
    const items: AttentionItem[] = [
      { kind: 'runs', runs: [pRun(true, 'ver1'), pRun(false, 'ver2')] },
      { kind: 'warnings', version: version(['a', 'b']) },
      { kind: 'failed', job: { id: 'j1' } as never },
    ]
    expect(attentionChip(items)).toEqual({ label: 'Run failed · +3', tone: 'warn', count: 4 })
  })

  it('only work under way is not a warning', () => {
    const items: AttentionItem[] = [{ kind: 'generating', version: version(), text: 'Generating documents · 3 of 25' }]
    expect(attentionChip(items)).toEqual({ label: 'Generating documents · 3 of 25', tone: 'busy', count: 1 })
    expect(attentionChip([{ kind: 'runs', runs: [pRun(true, 'ver1'), pRun(true, 'ver2')] }]))
      .toEqual({ label: '2 other runs at work', tone: 'busy', count: 1 })
  })

  it('runs cut short come before work under way', () => {
    expect(attentionChip([{ kind: 'runs', runs: [pRun(true, 'ver1'), pRun(false, 'ver2'), pRun(false, 'ver4')] }])?.label)
      .toBe('2 runs cut short · +1')
  })
})

describe('generationItem', () => {
  const comp = (state: string) => ({ id: `L.${state}`, layer: 'L', name: state, state, inModel: true, layerParsed: true, error: null, documents: [] })
  it('the version on screen at work, or stopped; nothing when neither', () => {
    const atWork = comps(runAt('2026-10-07T10:00:00Z', { alive: true, outcome: 'running', command: 'export' }),
      { components: [comp('generating'), comp('generated')] as never })
    expect(generationItem(version(), atWork)).toMatchObject({ kind: 'generating', text: expect.stringMatching(/ · \d+ of 2$/) })
    const stopped = comps(runAt('2026-10-07T10:00:00Z', { stopped: true, outcome: 'running' }), { components: [comp('generated')] as never })
    expect(generationItem(version(), stopped)).toMatchObject({ kind: 'stopped', text: 'Generation stopped' })
    expect(generationItem(version(), comps(null, { components: [comp('generated')] as never }))).toBeNull()
  })
})
