import type { AnalysisJob, ProjectRun, Version, VersionComponents } from '../types'
import { generationSummary } from './versionComponents'

/* Needs attention (components/attention/): what used to stack as banners on the Overview -- a
   failed analysis, the version's generation stopped or at work, every other run at work or cut
   short, a run's warnings -- now one chip beside the version and a drawer with each of them. */

/** A failed analysis is old news once a later run of its version is at work or has finished: a
 *  Resume, a Generate of its components. "Last analysis failed" stayed after the version was
 *  resumed and made, because it reads the project's last ANALYSIS job, and neither is one. */
export function failureSuperseded(
  job: Pick<AnalysisJob, 'startedAt' | 'completedAt'>, comps: VersionComponents | undefined,
): boolean {
  if (!comps) return false
  if (comps.job) return true                              // a web job holds the version now
  const run = comps.run
  if (!run?.startedAt) return false
  const failedAt = Date.parse(job.completedAt ?? job.startedAt ?? '')
  if (Number.isNaN(failedAt) || Date.parse(run.startedAt) <= failedAt) return false
  return run.alive === true || run.outcome === 'running' || run.outcome === 'complete'
}

export type AttentionItem =
  | { kind: 'failed'; job: AnalysisJob }
  /** The version on screen: its generation at work, or stopped before it finished. */
  | { kind: 'generating' | 'stopped'; version: Version; text: string }
  | { kind: 'runs'; runs: ProjectRun[] }
  | { kind: 'warnings'; version: Version }

/** The version on screen's generation, as an item: at work or stopped (the Overview's banner says
 *  the rest -- components without documents, Word files out of date). */
export function generationItem(version: Version | undefined, comps: VersionComponents | undefined): AttentionItem | null {
  const s = generationSummary(comps)
  if (!version || !s?.row) return null
  if (s.row.kind === 'running') {
    return { kind: 'generating', version, text: `${s.row.verb} · ${s.withDocs} of ${s.total}` }
  }
  if (s.row.kind === 'stopped') {
    const n = s.row.cutShort
    return { kind: 'stopped', version, text: s.row.at ? 'Generation stopped' : `${n} component${n === 1 ? '' : 's'} not made` }
  }
  return null
}

export interface AttentionChipState {
  /** The most pressing item, and "+N" for the others. */
  label: string
  /** warn: something failed, stopped or warned; busy: only work under way. */
  tone: 'warn' | 'busy'
  count: number
}

/** The chip for these items, most pressing first: failed, stopped, cut short, at work, warnings. */
export function attentionChip(items: AttentionItem[]): AttentionChipState | null {
  const runs = items.flatMap((i) => (i.kind === 'runs' ? i.runs : []))
  const cut = runs.filter((r) => !r.alive).length
  const atWork = runs.length - cut
  const parts: [string, 'warn' | 'busy'][] = []
  for (const i of items) if (i.kind === 'failed') parts.push(['Run failed', 'warn'])
  for (const i of items) if (i.kind === 'stopped') parts.push([i.text, 'warn'])
  if (cut) parts.push([`${cut} run${cut === 1 ? '' : 's'} cut short`, 'warn'])
  for (const i of items) if (i.kind === 'generating') parts.push([i.text, 'busy'])
  if (atWork) parts.push([`${atWork} other run${atWork === 1 ? '' : 's'} at work`, 'busy'])
  for (const i of items) {
    if (i.kind === 'warnings') {
      const n = i.version.warnings.length
      parts.push([`${n} warning${n === 1 ? '' : 's'}`, 'warn'])
    }
  }
  if (!parts.length) return null
  return {
    label: parts.length > 1 ? `${parts[0][0]} · +${parts.length - 1}` : parts[0][0],
    tone: parts.some(([, t]) => t === 'warn') ? 'warn' : 'busy',
    count: parts.length,
  }
}
