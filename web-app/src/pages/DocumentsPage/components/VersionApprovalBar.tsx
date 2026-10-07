import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { formatDate } from '../../../lib/format'
import { REVIEW_ORDER, STATUS_META, reviewCounts } from '../../../lib/reviewStatus'
import type { Document, ReviewStatus, Version } from '../../../types'

/* The version's approval, derived from its documents: "N of M approved", a bar segmented by
   state, and a legend whose entries filter the list (documents.html paintVersionBar). A version
   is approved when every one of its documents is — nobody sets it by hand. */
export function VersionApprovalBar({
  version, docs, onOnlyStatus, onNeedsReviewer,
}: {
  version?: Version
  /** Every document of the version (not the filtered rows). */
  docs: Document[]
  onOnlyStatus: (s: ReviewStatus) => void
  onNeedsReviewer: () => void
}) {
  const c = reviewCounts(docs)
  if (!c.total) return null
  const tag = version?.tag ?? 'This version'
  const all = c.approved === c.total
  const pct = Math.round((c.approved / c.total) * 100)
  const by = version?.review?.approvedBy
  const at = formatDate(version?.review?.approvedAt)
  const shown = REVIEW_ORDER.filter((k) => c[k] > 0)

  return (
    <div className="px-5 py-3 border-b border-outline-variant bg-surface">
      <div className="flex items-center gap-2 mb-2">
        {all ? (
          <>
            <Icon name="check_circle" size={16} fill className="text-success" />
            <span className="font-mono text-caption text-state-done">
              <b>{tag} is approved</b> · all {c.total} documents{by ? ` · approved by ${by.name}${at ? `, ${at}` : ''}` : ''}
            </span>
          </>
        ) : (
          <>
            <Icon name="rate_review" size={16} className="text-warn" />
            <span className="font-mono text-caption text-state-warn">
              <b>{tag} is in review</b> · {c.approved} of {c.total} documents approved. The version is approved once all {c.total} are.
            </span>
          </>
        )}
        <span className={cn('ml-auto font-mono text-caption', all ? 'text-success' : 'text-warn')}>{pct}%</span>
      </div>
      <div className="h-2 rounded-[4px] overflow-hidden flex bg-surface-container" role="img" aria-label={`${c.approved} of ${c.total} approved`}>
        {shown.map((k) => (
          <div
            key={k}
            title={`${STATUS_META[k].label}: ${c[k]}`}
            className={STATUS_META[k].dot}
            // eslint-disable-next-line no-restricted-syntax -- a state's share of the bar is data-driven
            style={{ width: `${(c[k] / c.total) * 100}%` }}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-2 mt-1.5">
        {shown.map((k) => (
          <button
            key={k}
            onClick={() => onOnlyStatus(k)}
            title={`Show only ${STATUS_META[k].label}`}
            className="inline-flex items-center gap-[5px] px-1.5 py-0.5 rounded-lg font-mono text-caption text-on-surface-variant hover:bg-surface-container hover:text-on-surface"
          >
            <i className={cn('w-2 h-2 rounded-full inline-block', STATUS_META[k].dot)} aria-hidden />
            {STATUS_META[k].label} {c[k]}
          </button>
        ))}
        {c.needsReviewer > 0 && (
          <button
            onClick={onNeedsReviewer}
            title="Show the documents nobody reviews yet"
            className="inline-flex items-center gap-[5px] px-1.5 py-0.5 rounded-lg font-mono text-caption text-warn hover:bg-surface-container"
          >
            <Icon name="person_off" size={13} />
            Needs a reviewer {c.needsReviewer}
          </button>
        )}
      </div>
    </div>
  )
}
