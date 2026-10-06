import { cn } from '../../../lib/cn'
import type { ProjectRun } from '../../../types'
import { runState, runWords } from '../helpers'

/* Runs at work now, or stopped before they finished, in every project shown (GET …/runs — a web
   job or `analyzer.py` on the server). One click shows only that run's lines. A run that has
   reported no progress for 10 minutes turns amber: the one waiting on an LLM that stopped
   answering, visible without a search. */

const DOT = { live: 'bg-success', quiet: 'bg-warn', stopped: 'bg-warn' } as const

export function RunsRail({ runs, selectedVersion, scope, now, onSelect, projectName }: {
  runs: { projectId: string; run: ProjectRun }[]
  selectedVersion?: string
  /** What "All runs" covers: every project, or the one picked. */
  scope: string
  now: number
  onSelect: (pick: { projectId: string; run: ProjectRun } | null) => void
  projectName: (id: string) => string
}) {
  const item = 'block w-full text-left px-3.5 py-2.5 border-b border-hairline hover:bg-surface-container-low'
  const on = 'bg-tint shadow-[inset_3px_0_0_var(--color-secondary)]'
  return (
    <aside className="w-[252px] flex-shrink-0 border-r border-outline-variant flex flex-col min-h-0" aria-label="Runs">
      <div className="h-8 flex items-center px-3.5 bg-surface-container-low border-b border-outline-variant flex-shrink-0">
        <span className="font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline">Runs</span>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        <button type="button" onClick={() => onSelect(null)} className={cn(item, !selectedVersion && on)}>
          <span className="block text-body font-semibold text-on-surface">All runs</span>
          <span className="block text-xs text-on-surface-variant mt-px">{scope}</span>
        </button>
        {runs.map(({ projectId, run }) => {
          const s = runState(run, now)
          return (
            <button key={run.versionId} type="button" onClick={() => onSelect({ projectId, run })}
              title={`${run.versionId}${run.host ? ` · on ${run.host}` : ''}`}
              className={cn(item, selectedVersion === run.versionId && on)}>
              <span className="block text-body font-semibold text-on-surface truncate">{projectName(projectId)}</span>
              <span className="block text-xs text-on-surface-variant mt-px">{run.versionTag} · {runWords(run.command)}</span>
              {s.activity && <span className="block text-xs text-outline mt-0.5 truncate">{s.activity}</span>}
              <span className={cn('flex items-center gap-1.5 text-xs mt-0.5', s.tone === 'live' ? 'text-outline' : 'text-warn')}>
                <span className={cn('w-[7px] h-[7px] rounded-full flex-shrink-0', DOT[s.tone])} aria-hidden />
                {s.when}
              </span>
            </button>
          )
        })}
        {!runs.length && <p className="px-3.5 py-4 text-xs text-outline">No run is at work.</p>}
      </div>
      <p className="px-3.5 py-2.5 text-label leading-4 text-outline border-t border-hairline">
        Runs at work or stopped before they finished. Amber: no progress for 10 minutes.
      </p>
    </aside>
  )
}
