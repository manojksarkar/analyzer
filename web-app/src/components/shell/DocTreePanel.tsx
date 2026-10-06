import { useState, useRef, useEffect } from 'react'
import { Icon, Skeleton, Text } from '../ui'
import { cn } from '../../lib/cn'
import { NEEDS_REVIEWER, PROCESS_TITLES, type ReviewerOption } from '../../lib/docTree'
import { STATUS_META } from '../../lib/reviewStatus'
import type { Document } from '../../types'

/**
 * Left document-tree rail (reviewer filter + process-grouped docs). Presentational:
 * the host page owns the grouping + reviewer-filter state so it can stay in sync
 * with a table (Documents) or run standalone (Inspector). Single-doc processes
 * render as a flat row; multi-doc processes (SWE.3) get a collapsible group, and
 * when a process spans more than one layer its docs are sub-grouped by layer.
 * The filter's value is a reviewer's user id, `none` (Needs a reviewer) or '' (all).
 */
export function DocTreePanel({
  groups, assigneeOptions, effectiveAssignee, meId, isDeveloper, activeDocId, onPickAssignee, onOpenDoc, onFold, loading,
}: {
  groups: { process: string; docs: Document[] }[]
  assigneeOptions: ReviewerOption[]
  effectiveAssignee: string
  /** The signed-in user's id ("My reviews"). */
  meId: string
  isDeveloper: boolean
  activeDocId?: string
  onPickAssignee: (value: string) => void
  onOpenDoc: (doc: Document) => void
  /** Shows a button that folds the panel away (the Inspector, where the reader needs the width). */
  onFold?: () => void
  /** The documents are not read yet: placeholder rows, not "No documents". */
  loading?: boolean
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  // The reviewer menu closes on a click outside it, and on Esc -- back to its button when focus
  // was in the menu. An Esc elsewhere (a correction box, a dialog) is not the menu's: focus stays.
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      const inMenu = !!ref.current && ref.current.contains(document.activeElement)
      setOpen(false)
      if (inMenu) trigger.current?.focus()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const label = !effectiveAssignee ? 'Reviewer'
    : effectiveAssignee === meId ? 'My reviews'
      : effectiveAssignee === NEEDS_REVIEWER ? 'Needs a reviewer'
        : assigneeOptions.find((o) => o.value === effectiveAssignee)?.label ?? 'Reviewer'

  function toggleCollapse(p: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p)
      else next.add(p)
      return next
    })
  }

  function renderDocRow(d: Document, pad: string) {
    const active = d.id === activeDocId
    return (
      <button
        key={d.id}
        onClick={() => onOpenDoc(d)}
        title={d.name}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'w-full flex items-center gap-1.5 py-[5px] pr-2.5 transition-colors text-left font-mono text-caption',
          pad,
          active ? 'bg-surface-container text-secondary font-medium border-l-2 border-secondary' : 'text-on-surface-variant hover:bg-surface-container-low',
        )}
      >
        <span
          className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', STATUS_META[d.status].dot)}
          title={STATUS_META[d.status].label}
          aria-hidden
        />
        <span className="truncate">{d.name}</span>
      </button>
    )
  }

  return (
    <aside className="w-60 flex-shrink-0 bg-surface-container-lowest border-r border-outline-variant flex flex-col">
      {/* Panel header */}
      <div className="px-3 py-2.5 border-b border-outline-variant flex-shrink-0 flex items-center justify-between">
        <Text variant="label" className="block text-on-surface-variant tracking-[0.1em]">Documents</Text>
        {onFold && (
          <button
            type="button"
            onClick={onFold}
            title="Hide the document list"
            aria-label="Hide the document list"
            className="p-0.5 -my-1 rounded text-outline hover:text-secondary hover:bg-surface-container-low"
          >
            <Icon name="left_panel_close" size={18} />
          </button>
        )}
      </div>

      {/* Assignee filter */}
      <div className="px-3 py-2 border-b border-outline-variant flex-shrink-0 relative" ref={ref}>
        <button
          ref={trigger}
          onClick={() => setOpen((v) => !v)}
          aria-haspopup="true"
          aria-expanded={open}
          aria-label={`Reviewer filter: ${label}`}
          className={cn(
            'w-full flex items-center gap-2 px-2.5 py-1.5 border rounded-lg bg-surface-container-lowest hover:bg-surface-container-low transition-colors font-mono text-caption font-medium',
            effectiveAssignee ? 'border-secondary text-secondary' : 'border-outline-variant text-on-surface-variant',
          )}
        >
          <Icon name="person" size={14} className={effectiveAssignee ? 'text-secondary' : 'text-on-surface-variant'} />
          <span className="flex-1 text-left truncate">{label}</span>
          <Icon name="expand_more" size={13} className={cn('transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <div className="absolute left-2 right-2 top-[calc(100%-4px)] bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)]">
            <div className="py-1.5 max-h-[260px] overflow-y-auto">
              {isDeveloper && meId && (
                <>
                  <button
                    onClick={() => { onPickAssignee(meId); setOpen(false) }}
                    className={cn('w-full text-left px-3 py-2 hover:bg-surface-container-low font-mono text-caption text-on-surface', effectiveAssignee === meId && 'bg-surface-container-low')}
                  >
                    My reviews
                  </button>
                  <div className="border-t border-outline-variant my-0.5" />
                </>
              )}
              <button
                onClick={() => { onPickAssignee(''); setOpen(false) }}
                className={cn('w-full text-left px-3 py-2 hover:bg-surface-container-low font-mono text-caption text-on-surface', !effectiveAssignee && 'bg-surface-container-low')}
              >
                All reviewers
              </button>
              <button
                onClick={() => { onPickAssignee(NEEDS_REVIEWER); setOpen(false) }}
                className={cn('w-full text-left px-3 py-2 hover:bg-surface-container-low font-mono text-caption text-warn', effectiveAssignee === NEEDS_REVIEWER && 'bg-surface-container-low')}
              >
                Needs a reviewer
              </button>
              {assigneeOptions.map((a) => (
                <button
                  key={a.value}
                  onClick={() => { onPickAssignee(a.value); setOpen(false) }}
                  className={cn('w-full text-left px-3 py-2 hover:bg-surface-container-low font-mono text-caption text-on-surface truncate', effectiveAssignee === a.value && 'bg-surface-container-low')}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Tree: buttons in reading order, so Tab walks it */}
      <nav aria-label="Documents of this version" className="flex-1 overflow-y-auto min-h-0 py-2">
        {loading ? (
          <div className="px-2.5 space-y-2" aria-hidden>
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-5" />)}
          </div>
        ) : groups.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <Text variant="caption" className="font-mono">No documents</Text>
          </div>
        ) : (
          groups.map((g) => {
            // Single-doc processes render as one flat row; only multi-doc
            // processes (SWE.3) get a collapsible group — per documents.html.
            if (g.docs.length === 1) {
              const d = g.docs[0]
              const active = d.id === activeDocId
              return (
                <button
                  key={g.process}
                  onClick={() => onOpenDoc(d)}
                  title={d.name}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'w-full flex items-center gap-2 px-3 py-2 transition-colors text-left select-none',
                    active ? 'bg-surface-container-low' : 'hover:bg-surface-container-low',
                  )}
                >
                  <span className={cn('font-mono text-caption font-semibold whitespace-nowrap', active ? 'text-secondary' : 'text-on-surface')}>{g.process}</span>
                  <span className="font-mono text-label text-on-surface-variant truncate">{d.name}</span>
                </button>
              )
            }
            const isOpen = !collapsed.has(g.process)
            // Sub-group the docs by layer. Only worth an extra tree level when the
            // process spans more than one layer; a single-layer process stays flat.
            const byLayer = new Map<string, Document[]>()
            for (const d of g.docs) {
              const k = d.layer || 'Other'
              const arr = byLayer.get(k) ?? []
              arr.push(d)
              byLayer.set(k, arr)
            }
            const layers = [...byLayer.keys()].sort()
            const multiLayer = layers.length > 1
            return (
              <div key={g.process}>
                <button
                  onClick={() => toggleCollapse(g.process)}
                  aria-expanded={isOpen}
                  className="w-full flex items-center gap-1.5 px-3 py-2 hover:bg-surface-container-low transition-colors select-none"
                >
                  <Icon name="chevron_right" size={14} className={cn('text-on-surface-variant transition-transform', isOpen && 'rotate-90')} />
                  <span className="font-mono text-caption font-semibold text-on-surface flex-shrink-0">{g.process}</span>
                  <span className="font-mono text-label text-on-surface-variant truncate">{PROCESS_TITLES[g.process] ?? ''}</span>
                </button>
                {isOpen && (multiLayer
                  ? layers.map((layer) => {
                      const key = `${g.process}/${layer}`
                      const layerOpen = !collapsed.has(key)
                      const docs = byLayer.get(layer)!
                      return (
                        <div key={key}>
                          <button
                            onClick={() => toggleCollapse(key)}
                            aria-expanded={layerOpen}
                            className="w-full flex items-center gap-1.5 pl-7 pr-3 py-1.5 hover:bg-surface-container-low transition-colors select-none"
                          >
                            <Icon name="chevron_right" size={12} className={cn('text-on-surface-variant transition-transform', layerOpen && 'rotate-90')} />
                            <span className="font-mono text-label text-on-surface-variant uppercase tracking-[0.08em] truncate">{layer}</span>
                          </button>
                          {layerOpen && docs.map((d) => renderDocRow(d, 'pl-11'))}
                        </div>
                      )
                    })
                  : g.docs.map((d) => renderDocRow(d, 'pl-8')))}
              </div>
            )
          })
        )}
      </nav>
    </aside>
  )
}
