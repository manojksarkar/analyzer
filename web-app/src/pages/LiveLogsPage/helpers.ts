import type { LogFilters, LogLevel, LogRecord, LogSource, ProjectRun } from '../../types'
import { runActivity } from '../../lib/versionComponents'

/* Live logs: the page's pure rules — filters in the address, how a time and a run read, which
   lines a search keeps. */

/** Lines over this many are folded (a traceback), with "Show N more lines". */
export const FOLD_LINES = 5
/** A run that has reported no progress for this long reads "Quiet for …", in amber. */
export const QUIET_MS = 10 * 60_000

/** What the page shows: All = INFO and up (DEBUG with the Debug box), or warnings and errors. */
export type Show = 'all' | 'warn'

export interface PageFilters {
  show: Show
  debug: boolean
  source?: LogSource
  project?: string
  version?: string
  job?: string
}

/** The address holds the filters, so a run's logs are a link (`?job=…`) and Back works. */
export function filtersFromParams(p: URLSearchParams): PageFilters {
  const level = p.get('level')
  const source = p.get('source')
  return {
    show: level === 'WARNING' ? 'warn' : 'all',
    debug: level === 'DEBUG',
    source: source === 'server' || source === 'engine' ? source : undefined,
    project: p.get('project') || undefined,
    version: p.get('version') || undefined,
    job: p.get('job') || undefined,
  }
}

export function paramsFromFilters(f: PageFilters): Record<string, string> {
  const out: Record<string, string> = {}
  if (f.project) out.project = f.project
  if (f.version) out.version = f.version
  if (f.job) out.job = f.job
  if (f.show === 'warn') out.level = 'WARNING'
  else if (f.debug) out.level = 'DEBUG'
  if (f.source) out.source = f.source
  return out
}

/** The server filters. A run named by its job is asked for by the job alone: the API's lines
 *  about a job carry its project, not always its version. */
export function serverFilters(f: PageFilters): LogFilters {
  const level: LogLevel = f.show === 'warn' ? 'WARNING' : f.debug ? 'DEBUG' : 'INFO'
  if (f.job) return { level, source: f.source, job: f.job }
  return { level, source: f.source, project: f.project, version: f.version }
}

/** `10:15:03.420` — the server's own clock, as sent (no conversion to the reader's zone). */
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

/** How a run in the Runs list reads now. Quiet = alive, but no progress for 10 minutes: the run
 *  that waits on an LLM that stopped answering. */
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
