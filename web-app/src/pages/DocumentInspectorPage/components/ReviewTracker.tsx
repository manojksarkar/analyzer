import { Icon, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { DocSection, SectionReviewState } from '../../../types'

/* review_state → outline/tracker icon */
const SECTION_STATE: Record<SectionReviewState, { icon: string; cls: string }> = {
  accepted: { icon: 'check_circle',           cls: 'text-[#00a572]' },
  edited:   { icon: 'edit',                   cls: 'text-secondary' },
  declined: { icon: 'cancel',                 cls: 'text-error' },
}
function sectionStateIcon(s: SectionReviewState | null) {
  return s ? SECTION_STATE[s] : { icon: 'radio_button_unchecked', cls: 'text-outline' }
}

/* ── Review tracker (in-review right panel) ── */
export function ReviewTracker({
  sections, progress, reviewer, reviewerInitials, isAdmin, assignedToMe,
  onMarkComplete, onReassign, onAssignToMe, onJump,
}: {
  sections: DocSection[]
  progress?: { resolved: number; total: number }
  reviewer?: string
  reviewerInitials?: string
  isAdmin: boolean
  assignedToMe: boolean
  onMarkComplete: () => void
  onReassign: () => void
  onAssignToMe: () => void
  onJump: (key: string) => void
}) {
  const total = progress?.total ?? sections.length
  const resolved = progress?.resolved ?? 0
  const pct = total ? Math.round((resolved / total) * 100) : 0

  return (
    <div className="flex-1 overflow-y-auto py-3 px-3 space-y-4">
      {/* Reviewer + progress */}
      <div>
        <Text variant="label" className="block text-on-surface-variant tracking-[0.08em] mb-2">Reviewer</Text>
        <div className="flex items-center gap-2 mb-2">
          {reviewer ? (
            <div className="w-7 h-7 rounded-full bg-secondary-container flex items-center justify-center flex-shrink-0">
              <span className="font-bold text-on-secondary-container font-sans text-micro">{reviewerInitials}</span>
            </div>
          ) : (
            // An empty seat, not a filled blue "—" that read like a remove button.
            <div className="w-7 h-7 rounded-full border border-dashed border-outline-variant bg-white flex items-center justify-center flex-shrink-0">
              <Icon name="person" size={14} className="text-outline" />
            </div>
          )}
          <span className={cn('font-mono text-caption truncate', reviewer ? 'text-on-surface' : 'text-outline')}>{reviewer ?? 'Unassigned'}</span>
        </div>
        <div className="flex items-center justify-between mb-1">
          <Text variant="caption" className="font-mono">Progress</Text>
          <Text variant="caption" className="font-mono">{pct}%</Text>
        </div>
        <div className="h-1.5 rounded-[3px] bg-surface-container overflow-hidden">
          {/* eslint-disable-next-line no-restricted-syntax -- review progress width is data-driven */}
          <div className={cn('h-full rounded-[3px]', pct === 100 ? 'bg-[#00a572]' : 'bg-secondary')} style={{ width: `${pct}%` }} />
        </div>
        <Text as="p" variant="caption" className="font-mono mt-1">{resolved} of {total} sections</Text>
      </div>

      {/* Section checklist */}
      <div>
        <Text variant="label" className="block text-on-surface-variant tracking-[0.08em] mb-2">Sections</Text>
        <div className="space-y-1.5">
          {sections.map((s) => {
            const st = sectionStateIcon(s.reviewState)
            return (
              <button
                key={s.key}
                onClick={() => onJump(s.key)}
                title={s.title}
                className="w-full flex items-start gap-1.5 text-left hover:bg-surface-container-low rounded transition-colors px-1 py-0.5"
              >
                <Icon name={st.icon} size={12} className={cn('mt-0.5 flex-shrink-0', st.cls)} />
                {/* Wraps: SWE.4's chapter titles are long and were cut to "2. Unit Test Specifica…". */}
                <span className="font-mono text-label text-on-surface-variant leading-snug [overflow-wrap:anywhere]">{s.title}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Actions */}
      <div className="space-y-2 pt-1 border-t border-outline-variant">
        <button
          onClick={onMarkComplete}
          className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 bg-[#00a572] text-white rounded-lg hover:opacity-90 transition-opacity font-mono text-label font-semibold"
        >
          <Icon name="check_circle" size={12} />
          Mark Complete
        </button>
        {isAdmin && (
          <button
            onClick={onReassign}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 border border-outline-variant hover:bg-surface-container rounded-lg transition-colors font-mono text-label text-on-surface-variant"
          >
            <Icon name="person_add" size={12} />
            Re-assign
          </button>
        )}
        {!isAdmin && !assignedToMe && (
          <button
            onClick={onAssignToMe}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 border border-secondary text-secondary hover:bg-surface-container-low rounded-lg transition-colors font-mono text-label font-semibold"
          >
            <Icon name="person_add" size={12} />
            Assign to me
          </button>
        )}
      </div>
    </div>
  )
}
