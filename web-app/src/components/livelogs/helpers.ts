import type { LogFilters, LogLevel, LogRecord, LogSource, ProjectRun } from '../../types'
import type { LogScope } from '../../store/logsPanel'
import { runActivity } from '../../lib/versionComponents'

/* The Logs panel's pure rules: what the server is asked for, how a time and a run read, which
   lines a search keeps. */

/** Lines over this many are folded (a traceback), with "Show N more lines". */
export const FOLD_LINES = 5
/** A run that has reported no progress for this long reads "Quiet for …", in amber. */
export const QUIET_MS = 10 * 60_000

/** All = INFO and up; warnings and errors; or everything, DEBUG too (the busiest). */
export type Show = 'all' | 'warn' | 'debug'

/** The server filters for what the panel shows. A run is asked for by its version (its engine
 *  lines and the API's lines about it both carry it), or by its job when it has no version any
 *  more (a failed run's draft is removed). */
export function serverFilters(scope: LogScope, show: Show, source?: LogSource): LogFilters {
  const level: LogLevel = show === 'warn' ? 'WARNING' : show === 'debug' ? 'DEBUG' : 'INFO'
  if (scope.kind === 'job') return { level, source, job: scope.job }
  if (scope.kind === 'version') return { level, source, project: scope.project, version: scope.version }
  if (scope.kind === 'project') return { level, source, project: scope.project }
  return { level, source }
}

/** One run, one version: its lines need no project or version beside them. */
export const isOneRun = (scope: LogScope) => scope.kind === 'version' || scope.kind === 'job'

/** `10:15:03.420` -- the server's own clock, as sent (no conversion to the reader's zone). */
export function clockOf(ts: string): string {
  const m = /T(\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?)/.exec(ts)
  return m ? m[1] : ts
}

/** The full date and offset, for the hover. */
export function fullTime(ts: string): string {
  return ts.replace('T', ' ')
}

/** A search keeps a line whose message or logger holds the text, any case. */
export function matches(r: LogRecord, q: string): boolean {
  const s = q.trim().toLowerCase()
  return !s || r.message.toLowerCase().includes(s) || r.logger.toLowerCase().includes(s)
}

/** `12 min`, `17 h`, `3 d`. */
export function span(ms: number): string {
  const min = Math.max(0, Math.round(ms / 60_000))
  if (min < 60) return `${min} min`
  const h = Math.round(min / 60)
  return h < 48 ? `${h} h` : `${Math.round(h / 24)} d`
}

const RUN_WORDS: Record<string, string> = {
  generate: 'Generate', export: 'Export', reexport: 'Word file update', resume: 'Resume',
}
/** A run's kind in words, from a log line's `run` or a run record's `command`. */
export function runWords(command: string | null | undefined): string {
  return (command && RUN_WORDS[command]) || (command ? command[0].toUpperCase() + command.slice(1) : 'Run')
}

export interface RunState {
  tone: 'live' | 'quiet' | 'stopped'
  /** What it is doing: "describing globals, 268 of 268". */
  activity: string
  /** "2 min ago", "Quiet for 17 h", "Stopped 3 h ago". */
  when: string
}

/** How a run reads now. Quiet = alive, but no progress for 10 minutes: the run that waits on an
 *  LLM that stopped answering. */
export function runState(run: ProjectRun, now: number): RunState {
  const activity = runActivity(run)
  const at = run.progressAt ?? run.startedAt
  const idle = at ? now - Date.parse(at) : 0
  if (run.stopped) return { tone: 'stopped', activity, when: `Stopped ${span(idle)} ago` }
  if (idle > QUIET_MS) return { tone: 'quiet', activity, when: `Quiet for ${span(idle)}` }
  return { tone: 'live', activity, when: idle < 60_000 ? 'just now' : `${span(idle)} ago` }
}

/** Running first, then by latest progress. */
export function sortRuns<T extends { run: ProjectRun }>(runs: T[]): T[] {
  const at = (r: ProjectRun) => Date.parse(r.progressAt ?? r.startedAt ?? '') || 0
  return [...runs].sort((a, b) => Number(!!b.run.alive) - Number(!!a.run.alive) || at(b.run) - at(a.run))
}

/** The Showing button's words: what kind, and which. */
export function scopeLabel(scope: LogScope, projectName: (id: string) => string): [string, string] {
  if (scope.kind === 'all') return ['Showing', 'Every project, and the API']
  if (scope.kind === 'project') return ['Project', scope.label ?? projectName(scope.project)]
  return ['Run', scope.label ?? projectName(scope.project)]
}
