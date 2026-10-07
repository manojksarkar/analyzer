import { useEffect, useRef, useState } from 'react'
import { Icon } from '../ui'
import { cn } from '../../lib/cn'
import type { LogScope } from '../../store/logsPanel'
import type { ProjectRun } from '../../types'
import { runState, runWords, scopeLabel } from './helpers'

/* What the panel shows, in one button: a run (every project's runs at work, or stopped before
   they finished -- amber when one has reported nothing for 10 minutes), this project, or every
   project and the API. */

const DOT = { live: 'bg-success', quiet: 'bg-warn', stopped: 'bg-warn' } as const

export function ScopePicker({ scope, onPick, runs, projectId, now, projectName }: {
  scope: LogScope
  onPick: (scope: LogScope) => void
  runs: { projectId: string; run: ProjectRun }[]
  /** The project of the page the panel is on, if any. */
  projectId?: string
  now: number
  projectName: (id: string) => string
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const off = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', off)
    return () => document.removeEventListener('mousedown', off)
  }, [open])

  const [kind, which] = scopeLabel(scope, projectName)
  const same = (s: LogScope) => JSON.stringify({ ...s, label: undefined }) === JSON.stringify({ ...scope, label: undefined })
  const pick = (s: LogScope) => { onPick(s); setOpen(false) }
  const item = 'block w-full text-left px-3 py-1.5 text-body text-on-surface hover:bg-surface-container-low'
  const head = 'px-3 pt-2 pb-0.5 font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline'

  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-haspopup="listbox" aria-expanded={open}
        className="inline-flex items-center gap-1.5 h-[30px] max-w-[360px] px-2.5 border border-outline-variant rounded-lg bg-surface-container-lowest text-body text-on-surface whitespace-nowrap">
        <span className="text-outline">{kind}:</span>
        <span className="font-medium truncate">{which}</span>
        <Icon name="expand_more" size={16} className="text-on-surface-variant" />
      </button>
      {open && (
        <div role="listbox" aria-label="Show"
          className="absolute left-0 bottom-[calc(100%+6px)] z-10 min-w-[340px] max-h-[320px] overflow-auto py-1 bg-surface-container-lowest border border-outline-variant rounded-xl shadow-[0_8px_24px_rgba(0,0,0,.25)]">
          <p className={head}>Runs</p>
          {runs.map(({ projectId: pid, run }) => {
            const s = runState(run, now)
            const label = `${projectName(pid)} · ${run.versionTag} · ${runWords(run.command)}`
            const target: LogScope = { kind: 'version', project: pid, version: run.versionId, label }
            return (
              <button key={run.versionId} type="button" role="option" aria-selected={same(target)}
                onClick={() => pick(target)} className={cn(item, same(target) && 'bg-tint text-secondary')}>
                {label}
                <span className={cn('flex items-center gap-1.5 text-xs mt-px', s.tone === 'live' ? 'text-outline' : 'text-warn')}>
                  <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', DOT[s.tone])} aria-hidden />
                  {[s.activity, s.when].filter(Boolean).join(' · ')}
                </span>
              </button>
            )
          })}
          {!runs.length && <p className="px-3 py-1.5 text-xs text-outline">No run is at work.</p>}
          <p className={head}>Everything</p>
          {projectId && (
            <button type="button" role="option" aria-selected={same({ kind: 'project', project: projectId })}
              onClick={() => pick({ kind: 'project', project: projectId })}
              className={cn(item, same({ kind: 'project', project: projectId }) && 'bg-tint text-secondary')}>
              This project · {projectName(projectId)}
            </button>
          )}
          <button type="button" role="option" aria-selected={scope.kind === 'all'} onClick={() => pick({ kind: 'all' })}
            className={cn(item, scope.kind === 'all' && 'bg-tint text-secondary')}>
            Every project, and the API
          </button>
        </div>
      )}
    </div>
  )
}
