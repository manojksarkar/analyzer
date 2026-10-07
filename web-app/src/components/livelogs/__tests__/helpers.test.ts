import { describe, expect, it } from 'vitest'
import type { LogRecord, ProjectRun } from '../../../types'
import { clockOf, isOneRun, matches, runState, runWords, scopeLabel, serverFilters, sortRuns, span } from '../helpers'
import { runScope } from '../../../store/logsPanel'

const run = (over: Partial<ProjectRun> = {}): ProjectRun => ({
  versionId: 'ver1', versionTag: 'v1.2.0', command: 'generate', alive: true, stopped: false, outcome: 'running',
  host: null, startedAt: '2026-10-06T09:00:00Z', finishedAt: null, stage: 'LLM-global', done: 268, total: 268,
  stageStartedAt: null, progressAt: '2026-10-06T10:00:00Z', ...over,
})
const NOW = Date.parse('2026-10-06T10:05:00Z')
const name = (id: string) => ({ p1: 'Brake Control Unit' } as Record<string, string>)[id] ?? id

describe('Logs panel helpers', () => {
  it('what the server is asked for, per scope', () => {
    expect(serverFilters({ kind: 'all' }, 'all')).toEqual({ level: 'INFO', source: undefined })
    expect(serverFilters({ kind: 'project', project: 'p1' }, 'warn', 'engine'))
      .toEqual({ level: 'WARNING', source: 'engine', project: 'p1' })
    expect(serverFilters({ kind: 'version', project: 'p1', version: 'v9' }, 'debug'))
      .toEqual({ level: 'DEBUG', source: undefined, project: 'p1', version: 'v9' })
    expect(serverFilters({ kind: 'job', project: 'p1', job: 'job9' }, 'all'))
      .toEqual({ level: 'INFO', source: undefined, job: 'job9' })
  })

  it('a run is its version, or its job once the version is gone', () => {
    expect(runScope('p1', 'v9', 'job9')).toEqual({ kind: 'version', project: 'p1', version: 'v9', label: undefined })
    expect(runScope('p1', null, 'job9', 'Failed run')).toEqual({ kind: 'job', project: 'p1', job: 'job9', label: 'Failed run' })
    expect(runScope('p1', null, null)).toEqual({ kind: 'project', project: 'p1' })
    expect([isOneRun({ kind: 'version', project: 'p', version: 'v' }), isOneRun({ kind: 'project', project: 'p' })]).toEqual([true, false])
  })

  it('the Showing button names the scope', () => {
    expect(scopeLabel({ kind: 'all' }, name)).toEqual(['Showing', 'Every project, and the API'])
    expect(scopeLabel({ kind: 'project', project: 'p1' }, name)).toEqual(['Project', 'Brake Control Unit'])
    expect(scopeLabel({ kind: 'version', project: 'p1', version: 'v9', label: 'Brake Control Unit · v1.2.0 · Generate' }, name))
      .toEqual(['Run', 'Brake Control Unit · v1.2.0 · Generate'])
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

  it('spans, run words and the order of runs', () => {
    expect([span(30_000), span(12 * 60_000), span(17 * 3600_000), span(72 * 3600_000)]).toEqual(['1 min', '12 min', '17 h', '3 d'])
    expect([runWords('reexport'), runWords('generate'), runWords(null), runWords('other')]).toEqual(['Word file update', 'Generate', 'Run', 'Other'])
    const a = { run: run({ versionId: 'a', alive: false, stopped: true, progressAt: '2026-10-06T10:04:00Z' }) }
    const b = { run: run({ versionId: 'b', progressAt: '2026-10-06T08:00:00Z' }) }
    const c = { run: run({ versionId: 'c', progressAt: '2026-10-06T10:00:00Z' }) }
    expect(sortRuns([a, b, c]).map((x) => x.run.versionId)).toEqual(['c', 'b', 'a'])
  })
})
