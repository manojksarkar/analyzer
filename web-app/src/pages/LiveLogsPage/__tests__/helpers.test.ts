import { describe, expect, it } from 'vitest'
import type { LogRecord, ProjectRun } from '../../../types'
import {
  clockOf, filtersFromParams, matches, paramsFromFilters, runState, runWords, serverFilters, sortRuns, span,
} from '../helpers'

const run = (over: Partial<ProjectRun> = {}): ProjectRun => ({
  versionId: 'ver1', versionTag: 'v1.2.0', command: 'generate', alive: true, stopped: false, outcome: 'running',
  host: null, startedAt: '2026-10-06T09:00:00Z', finishedAt: null, stage: 'LLM-global', done: 268, total: 268,
  stageStartedAt: null, progressAt: '2026-10-06T10:00:00Z', ...over,
})
const NOW = Date.parse('2026-10-06T10:05:00Z')

describe('Live logs helpers', () => {
  it('the address holds the filters, both ways', () => {
    const f = filtersFromParams(new URLSearchParams('project=p1&version=v9&level=WARNING&source=engine'))
    expect(f).toEqual({ show: 'warn', debug: false, source: 'engine', project: 'p1', version: 'v9', job: undefined })
    expect(paramsFromFilters(f)).toEqual({ project: 'p1', version: 'v9', level: 'WARNING', source: 'engine' })
    expect(filtersFromParams(new URLSearchParams('level=DEBUG&source=nope'))).toMatchObject({ show: 'all', debug: true, source: undefined })
    expect(paramsFromFilters({ show: 'all', debug: false })).toEqual({})
  })

  it('a run with a job is asked for by its job alone', () => {
    expect(serverFilters({ show: 'all', debug: false, project: 'p1', version: 'v9', job: 'job1' }))
      .toEqual({ level: 'INFO', source: undefined, job: 'job1' })
    expect(serverFilters({ show: 'warn', debug: true, project: 'p1' }))
      .toEqual({ level: 'WARNING', source: undefined, project: 'p1', version: undefined })
    expect(serverFilters({ show: 'all', debug: true }).level).toBe('DEBUG')
  })

  it('a time reads as the server wrote it', () => {
    expect(clockOf('2026-10-06T06:55:08.052+05:30')).toBe('06:55:08.052')
    expect(clockOf('2026-10-06T06:55:08+05:30')).toBe('06:55:08')
  })

  it('search matches the message or the logger, any case', () => {
    const r = { message: 'HTTP 503 from the upstream', logger: 'llm_client' } as LogRecord
    expect(matches(r, '  upstream ')).toBe(true)
    expect(matches(r, 'LLM_CLIENT')).toBe(true)
    expect(matches(r, 'parser')).toBe(false)
    expect(matches(r, '')).toBe(true)
  })

  it('a run that reports nothing for 10 minutes is quiet; one cut short is stopped', () => {
    expect(runState(run({ progressAt: '2026-10-06T10:04:30Z' }), NOW)).toEqual({ tone: 'live', activity: 'describing globals, 268 of 268', when: 'just now' })
    expect(runState(run({ progressAt: '2026-10-06T09:58:00Z' }), NOW).when).toBe('7 min ago')
    expect(runState(run({ progressAt: '2026-10-05T17:05:00Z' }), NOW)).toMatchObject({ tone: 'quiet', when: 'Quiet for 17 h' })
    expect(runState(run({ alive: false, stopped: true, progressAt: '2026-10-06T07:05:00Z' }), NOW))
      .toMatchObject({ tone: 'stopped', when: 'Stopped 3 h ago' })
  })

  it('spans and run words', () => {
    expect([span(30_000), span(12 * 60_000), span(17 * 3600_000), span(72 * 3600_000)]).toEqual(['1 min', '12 min', '17 h', '3 d'])
    expect([runWords('reexport'), runWords('generate'), runWords(null), runWords('other')]).toEqual(['Word file update', 'Generate', 'Run', 'Other'])
  })

  it('running runs first, then the latest progress', () => {
    const a = { run: run({ versionId: 'a', alive: false, stopped: true, progressAt: '2026-10-06T10:04:00Z' }) }
    const b = { run: run({ versionId: 'b', progressAt: '2026-10-06T08:00:00Z' }) }
    const c = { run: run({ versionId: 'c', progressAt: '2026-10-06T10:00:00Z' }) }
    expect(sortRuns([a, b, c]).map((x) => x.run.versionId)).toEqual(['c', 'b', 'a'])
  })
})
