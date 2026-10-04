import { cn } from '../../../lib/cn'
import type { Version } from '../../../types'
import { versionRef } from '../helpers'

/* The reference (baseline) the current version is compared with: the version just before it,
   unless another older one is picked here (the page keeps the pick in its address, `?ref=`).
   With one older version there is nothing to pick: its tag shows as a chip. */
export function ReferencePicker({ options, value, fallback, onPick, className }: {
  /** Every version older than the current one, newest first. */
  options: Version[]
  value?: Version
  /** What names the reference when there is no version to show (its short commit). */
  fallback: string
  onPick: (ref: string) => void
  className?: string
}) {
  const chip = 'px-2 py-0.5 rounded bg-surface-container text-on-surface-variant border border-outline-variant uppercase font-mono text-micro font-bold'
  if (!value || options.length < 2) return <span className={cn(chip, className)}>{value?.tag ?? fallback}</span>
  return (
    <select
      aria-label="Reference version"
      title="The version the current one is compared with"
      value={versionRef(value) ?? ''}
      onChange={(e) => onPick(e.target.value)}
      className={cn(chip, 'normal-case cursor-pointer hover:border-secondary focus:outline-none focus:ring-2 focus:ring-secondary', className)}
    >
      {options.map((v) => {
        const ref = versionRef(v) ?? ''
        return <option key={ref} value={ref}>{v.tag}</option>
      })}
    </select>
  )
}
