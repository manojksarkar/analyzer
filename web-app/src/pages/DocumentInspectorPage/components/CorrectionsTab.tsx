import { Icon, Text } from '../../../components/ui'
import { formatShortDate } from '../../../lib/format'
import type { Slot } from '../../../types'
import { SLOT_KIND_LABEL, slotWhere } from '../outline'

/* This document's corrections (R1), newest first; a click goes to the text. The ones whose
   code changed since are kept but no longer printed — listed apart, greyed. */
export function CorrectionsTab({
  inForce, orphans, isLoading, isError, userName, onJump,
}: {
  inForce: Slot[]
  orphans: Slot[]
  isLoading: boolean
  isError: boolean
  userName: (id: string | null) => string
  onJump: (slot: Slot) => void
}) {
  const newest = [...inForce].sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))
  return (
    <div className="flex-1 overflow-y-auto px-3 py-3">
      <Text as="p" variant="caption" className="mb-2">This document’s corrections, newest first. Click one to go to it.</Text>
      {isLoading && <Text as="p" variant="caption" className="font-mono">Loading…</Text>}
      {isError && (
        <p className="flex items-center gap-1 text-caption text-error"><Icon name="error" size={14} />Could not read the corrections.</p>
      )}
      {!isLoading && !isError && !newest.length && (
        <Text as="p" variant="caption" className="font-mono">No corrections yet.</Text>
      )}
      {newest.map((s) => (
        <button
          key={`${s.kind}:${s.key}`}
          type="button"
          onClick={() => onJump(s)}
          className="block w-full text-left border border-outline-variant rounded-xl px-2.5 py-2 mb-2 bg-white hover:border-secondary hover:bg-surface transition-colors"
        >
          <Card slot={s} userName={userName} />
        </button>
      ))}
      {orphans.length > 0 && (
        <>
          <Text as="p" variant="label" className="block text-on-surface-variant tracking-[0.06em] mt-3 mb-1.5">
            No longer applies ({orphans.length})
          </Text>
          {orphans.map((s) => (
            <div key={`${s.kind}:${s.key}`} className="border border-dashed border-outline-variant rounded-xl px-2.5 py-2 mb-2 bg-surface-container-low opacity-80">
              <Card slot={s} userName={userName} orphan />
            </div>
          ))}
        </>
      )}
    </div>
  )
}

function Card({ slot, userName, orphan }: { slot: Slot; userName: (id: string | null) => string; orphan?: boolean }) {
  const who = userName(slot.updatedBy)
  return (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <span className={orphan ? 'font-mono text-label font-semibold uppercase tracking-[0.04em] text-outline' : 'font-mono text-label font-semibold uppercase tracking-[0.04em] text-secondary'}>
          {SLOT_KIND_LABEL[slot.kind] ?? slot.kind}
        </span>
        <span className="font-mono text-label text-on-surface-variant truncate">{slotWhere(slot)}</span>
      </div>
      <p className={orphan ? 'text-xs text-outline mt-1 line-clamp-3' : 'text-xs text-on-surface mt-1 line-clamp-3'}>
        {slot.humanText ?? slot.text}
      </p>
      <p className="font-mono text-label text-outline mt-1">
        {orphan && 'The code changed, so it is kept but not printed. '}
        {who || 'Someone'}{slot.updatedAt ? ` · ${formatShortDate(slot.updatedAt)}` : ''}
      </p>
    </>
  )
}
