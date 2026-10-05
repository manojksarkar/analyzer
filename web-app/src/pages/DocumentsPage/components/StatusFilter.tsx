import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { REVIEW_STATUSES, STATUS_META } from '../../../lib/reviewStatus'
import type { ReviewStatus } from '../../../types'

/* The list's status filter: the four review states, any number of them. */
export function StatusFilter({
  value, onToggle, onClear,
}: {
  value: ReadonlySet<ReviewStatus>
  onToggle: (s: ReviewStatus) => void
  onClear: () => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const one = value.size === 1 ? [...value][0] : null
  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        aria-expanded={open}
        className={cn(
          'flex items-center gap-1.5 px-3 py-2 border rounded-lg bg-white hover:bg-surface-container-low transition-colors font-mono text-caption font-medium',
          value.size ? 'border-secondary text-secondary' : 'border-outline-variant text-on-surface-variant',
        )}
      >
        <Icon name="filter_list" size={14} />
        {one ? STATUS_META[one].label : value.size > 1 ? `Status (${value.size})` : 'Status'}
        <Icon name="expand_more" size={13} />
      </button>
      {open && (
        <div className="absolute right-0 bg-white border border-outline-variant rounded-lg overflow-hidden top-[calc(100%+6px)] z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)] min-w-[200px]">
          <div className="py-1.5">
            {REVIEW_STATUSES.map((key) => (
              <button
                key={key}
                onClick={() => onToggle(key)}
                className="w-full flex items-center justify-between gap-3 px-3 py-2 hover:bg-surface-container-low text-on-surface font-mono text-caption"
              >
                <span className="flex items-center gap-2">
                  <i className={cn('w-2 h-2 rounded-full inline-block', STATUS_META[key].dot)} aria-hidden />
                  {STATUS_META[key].label}
                </span>
                {value.has(key) && <Icon name="check" size={14} className="text-secondary" />}
              </button>
            ))}
          </div>
          <div className="border-t border-outline-variant py-1">
            <button
              onClick={() => { onClear(); setOpen(false) }}
              className="w-full text-left px-3 py-2 hover:bg-surface-container-low text-on-surface-variant font-mono text-caption"
            >
              Clear filter
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
