import { memo, type ReactNode } from 'react'
import { cn } from '../../../lib/cn'
import type { LogLevel, LogRecord } from '../../../types'
import { FOLD_LINES, clockOf, fullTime, runWords } from '../helpers'

/* One log line: its time, a tag for anything but INFO, the message exactly as written (a traceback
   folds past five lines), and under it who wrote it and — across runs — where: project, version and
   run by name, each a link that narrows the page to it. */

const TAG: Partial<Record<LogLevel, string>> = {
  DEBUG: 'text-outline border border-outline-variant',
  WARNING: 'text-warn bg-warn-bg',
  ERROR: 'text-error bg-error-container',
  CRITICAL: 'text-white bg-error',
}

export interface LogPick { project?: string; version?: string; job?: string }

function highlight(text: string, q: string): ReactNode {
  const s = q.trim()
  if (!s) return text
  const lower = text.toLowerCase(), needle = s.toLowerCase()
  const out: ReactNode[] = []
  let i = 0
  for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, i)) {
    out.push(text.slice(i, at), <mark key={at} className="bg-highlight text-inherit rounded-[2px]">{text.slice(at, at + s.length)}</mark>)
    i = at + s.length
  }
  out.push(text.slice(i))
  return out
}

export const LogRow = memo(function LogRow({ r, oneRun, query, open, onToggle, onPick, projectName, versionTag }: {
  r: LogRecord
  /** The page shows one run: where it ran is said once, above. */
  oneRun: boolean
  query: string
  open: boolean
  onToggle: (seq: number) => void
  onPick: (p: LogPick) => void
  projectName: (id: string) => string
  versionTag: (id: string) => string
}) {
  const lines = r.message.split('\n')
  const folded = lines.length > FOLD_LINES && !open
  const link = 'text-on-surface-variant hover:text-secondary hover:underline'
  const ctx: ReactNode[] = [<span key="who">{r.source === 'server' ? 'API' : 'Engine'} · {r.logger}</span>]
  if (!oneRun) {
    if (r.project) {
      ctx.push(<button key="p" type="button" title={r.project} className={link} onClick={() => onPick({ project: r.project! })}>{projectName(r.project)}</button>)
    }
    if (r.version) {
      ctx.push(<button key="v" type="button" title={r.version} className={link}
        onClick={() => onPick({ project: r.project ?? undefined, version: r.version! })}>{versionTag(r.version)}</button>)
    }
    if (r.job) {
      ctx.push(<button key="j" type="button" title={r.job} className={link}
        onClick={() => onPick({ project: r.project ?? undefined, version: r.version ?? undefined, job: r.job! })}>{runWords(r.run)}</button>)
    }
    if (r.step) ctx.push(<span key="s">{r.step}</span>)
  }
  if (r.components.length) ctx.push(<span key="c">{r.components.join(', ')}</span>)

  return (
    <div className="grid grid-cols-[94px_70px_minmax(0,1fr)] gap-x-3 px-4 py-1.5 border-b border-hairline hover:bg-surface-container-low">
      <span title={fullTime(r.ts)} className="font-mono text-xs leading-5 text-on-surface-variant whitespace-nowrap [font-variant-ligatures:none]">
        {clockOf(r.ts)}
      </span>
      <span>
        {r.level !== 'INFO' && (
          <span className={cn('inline-block mt-px px-1.5 rounded-[4px] font-mono text-label font-semibold leading-[18px] tracking-[0.03em]', TAG[r.level])}>
            {r.level}
          </span>
        )}
      </span>
      <div className="min-w-0" title={r.pid ? `pid ${r.pid}` : undefined}>
        <pre className="m-0 font-mono text-xs leading-5 text-on-surface whitespace-pre-wrap break-words [font-variant-ligatures:none]">
          {highlight(folded ? lines.slice(0, FOLD_LINES).join('\n') : r.message, query)}
        </pre>
        {lines.length > FOLD_LINES && (
          <button type="button" onClick={() => onToggle(r.seq)} className="text-xs text-secondary hover:underline">
            {open ? 'Show less' : `Show ${lines.length - FOLD_LINES} more lines`}
          </button>
        )}
        <p className="mt-0.5 text-label leading-4 text-outline">
          {ctx.map((c, i) => <span key={i}>{i > 0 && ' · '}{c}</span>)}
        </p>
      </div>
    </div>
  )
})
