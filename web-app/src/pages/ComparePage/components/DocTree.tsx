import { Button, Icon, Skeleton } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { FailedLoad } from '../../../lib/failedLoad'
import type { DiffType } from '../../../types'
import { DIFF_BADGE, type TreeMode } from '../helpers'

/* ─── Left document tree (Diff / All) ─── */
// `process` tells a component's two documents apart: its SWE.3 and SWE.4 share its name.
export interface TreeRow { id: string; name: string; process?: string; diffType: DiffType; changed: boolean }

export function DocTree({ rows, mode, setMode, activeId, onSelect, changedCount, total, loading, failed }: {
  rows: TreeRow[]; mode: TreeMode; setMode: (m: TreeMode) => void
  activeId: string | null; onSelect: (id: string) => void
  changedCount: number; total: number; loading: boolean
  /** The list could not be read: say so, with Retry, not "No documents". */
  failed?: FailedLoad | null
}) {
  return (
    <aside className="w-60 flex-shrink-0 bg-white border-r border-outline-variant flex flex-col overflow-hidden">
      <div className="px-3 py-2.5 border-b border-outline-variant flex-shrink-0 flex items-center justify-between">
        <span className="text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.1em]">Documents</span>
        <div className="flex items-center rounded-lg border border-outline-variant overflow-hidden font-mono text-label font-semibold">
          <button onClick={() => setMode('diff')} className={cn('px-2 py-1 transition-colors', mode === 'diff' ? 'bg-primary text-white' : 'text-on-surface-variant')}>Diff</button>
          <button onClick={() => setMode('all')} className={cn('px-2 py-1 transition-colors', mode === 'all' ? 'bg-primary text-white' : 'text-on-surface-variant')}>All</button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {failed ? (
          <div role="alert" className="px-3 py-6 flex flex-col items-center text-center gap-2 font-mono text-caption">
            <Icon name="error" size={18} className="text-error" />
            <span className="text-on-surface">Could not load the documents</span>
            <span className="text-outline break-words">{failed.error instanceof Error ? failed.error.message : ''}</span>
            <Button variant="outline" size="sm" loading={failed.retrying} onClick={failed.retry}>Retry</Button>
          </div>
        ) : loading ? (
          <div className="px-2.5 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-5" />)}
          </div>
        ) : rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-outline font-mono text-caption">{mode === 'diff' ? 'No changed documents' : 'No documents'}</div>
        ) : (
          rows.map((d) => {
            const isActive = activeId === d.id
            return (
              <button
                key={d.id}
                onClick={() => onSelect(d.id)}
                className={cn(
                  'w-full flex items-center gap-1.5 transition-colors font-mono text-caption text-left border-l-2 py-[5px]',
                  isActive ? 'pl-2 pr-2.5 bg-surface-container text-secondary border-secondary' : 'px-2.5 border-transparent text-on-surface-variant hover:bg-surface-container-low',
                )}
              >
                <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', isActive ? 'bg-secondary' : d.changed ? DIFF_BADGE[d.diffType].dot : 'bg-outline-variant')} aria-hidden />
                <span className={cn('truncate', !d.changed && !isActive && 'opacity-40')}>{d.name}</span>
                {d.process && <span className={cn('ml-auto flex-shrink-0 text-label text-outline', !d.changed && !isActive && 'opacity-40')}>{d.process}</span>}
              </button>
            )
          })
        )}
      </div>
      <div className="px-3 py-2 border-t border-outline-variant flex-shrink-0">
        <span className="text-on-surface-variant font-mono text-caption">{changedCount} changed of {total}</span>
      </div>
    </aside>
  )
}
