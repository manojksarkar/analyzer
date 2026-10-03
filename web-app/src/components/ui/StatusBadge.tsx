import { cn } from '../../lib/cn'
import { STATUS_META, type StatusKey } from '../../lib/reviewStatus'
import { Icon } from './Icon'

/**
 * The one status badge: a document's review state (In review · Ready for approval · Changes
 * requested · Approved) or a version's / page's (adds Not run, Running, Stale). Words, icons and
 * colours come from lib/reviewStatus — never a local map.
 */
export function StatusBadge({
  status, size = 'md', label, suffix, title, className,
}: {
  status: StatusKey
  /** `sm`: the compact pill of a picker row or a tree. */
  size?: 'sm' | 'md'
  /** Replaces the state's word (a derived line such as "In review · 3/6 approved"). */
  label?: string
  /** Added after the word: " · from v1.1.0". */
  suffix?: string
  title?: string
  className?: string
}) {
  const m = STATUS_META[status] ?? STATUS_META.in_review
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border font-mono font-bold whitespace-nowrap',
        size === 'sm' ? 'px-1.5 text-micro' : 'px-2 py-0.5 text-label',
        m.badge,
        className,
      )}
    >
      <Icon
        name={m.icon}
        size={size === 'sm' ? 9 : 11}
        fill
        className={status === 'running' ? 'animate-spin' : undefined}
      />
      {label ?? m.label}
      {suffix}
    </span>
  )
}
