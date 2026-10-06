import { Icon, Text } from '../../../components/ui'
import { formatShortDate } from '../../../lib/format'
import type { Slot } from '../../../types'
import { SLOT_KIND_LABEL, slotWhere } from '../outline'

/** What an admin can do to orphans (R12). Absent: not an admin. */
export interface OrphanActions {
  /** Discard one orphan. */
  discard: (slot: Slot) => void
  /** Discard every orphan of the version (not only this document's). */
  discardAll: () => void
  /** The version's orphans, for the confirm. */
  versionCount: number
  busy: boolean
}

const FINAL = 'This cannot be undone, and later versions will not carry them.'

/* This document's corrections (R1), newest first; a click goes to the text. Undone ones — the
   page prints the LLM's text again — are listed apart while the Word file still has them (R9
   counts them until it is updated), so the banner's count and this list agree. The ones whose code
   changed since are kept but no longer printed — listed apart, greyed; an admin may discard them
   (R12). Below them, what the next run rewrites (`children`). */
export function CorrectionsTab({
  inForce, undone = [], orphans, isLoading, isError, userName, onJump, orphanActions, children,
}: {
  inForce: Slot[]
  /** Undone corrections the Word file still carries (R9 stale); [] otherwise. */
  undone?: Slot[]
  orphans: Slot[]
  isLoading: boolean
  isError: boolean
  userName: (id: string | null) => string
  onJump: (slot: Slot) => void
  orphanActions?: OrphanActions
  children?: React.ReactNode
}) {
  const newest = [...inForce].sort((a, b) => (b.updatedAt ?? '').localeCompare(a.updatedAt ?? ''))
  function discardOne(s: Slot) {
    if (!orphanActions) return
    if (window.confirm(`Discard this orphaned correction (${slotWhere(s)})? ${FINAL}`)) orphanActions.discard(s)
  }
  function discardAll() {
    if (!orphanActions) return
    const n = orphanActions.versionCount
    if (window.confirm(`Discard all ${n} orphaned correction${n === 1 ? '' : 's'} of this version? ${FINAL}`)) {
      orphanActions.discardAll()
    }
  }
  return (
    <div className="flex-1 overflow-y-auto px-3 py-3">
      <Text as="p" variant="caption" className="mb-2">This document’s corrections, newest first. Click one to go to it.</Text>
      {isLoading && <Text as="p" variant="caption" className="font-mono">Loading…</Text>}
      {isError && (
        <p className="flex items-center gap-1 text-caption text-error"><Icon name="error" size={14} />Could not read the corrections.</p>
      )}
      {!isLoading && !isError && !newest.length && !undone.length && (
        <Text as="p" variant="caption" className="font-mono">No corrections yet.</Text>
      )}
      {newest.map((s) => (
        <JumpCard key={`${s.kind}:${s.key}`} slot={s} onJump={onJump}>
          <Card slot={s} userName={userName} />
        </JumpCard>
      ))}
      {undone.length > 0 && (
        <section aria-label="Undone corrections">
          <Text as="p" variant="label" className="block text-on-surface-variant tracking-[0.06em] mt-3 mb-1.5">
            Undone — not in the Word file yet ({undone.length})
          </Text>
          {undone.map((s) => (
            <JumpCard key={`${s.kind}:${s.key}`} slot={s} onJump={onJump}>
              <Card slot={s} userName={userName} undone />
            </JumpCard>
          ))}
        </section>
      )}
      {orphans.length > 0 && (
        <section aria-label="Orphaned corrections">
          <div className="flex items-baseline justify-between gap-2 mt-3 mb-1.5">
            <Text as="p" variant="label" className="block text-on-surface-variant tracking-[0.06em]">
              No longer applies ({orphans.length})
            </Text>
            {orphanActions && (
              <button
                type="button"
                disabled={orphanActions.busy}
                onClick={discardAll}
                className="font-mono text-label font-semibold text-error hover:underline disabled:opacity-50"
              >
                Discard all orphans
              </button>
            )}
          </div>
          {orphans.map((s) => (
            <div key={`${s.kind}:${s.key}`} className="border border-dashed border-outline-variant rounded-xl px-2.5 py-2 mb-2 bg-surface-container-low opacity-80">
              <Card slot={s} userName={userName} orphan />
              {orphanActions && (
                <button
                  type="button"
                  disabled={orphanActions.busy}
                  onClick={() => discardOne(s)}
                  aria-label={`Discard the orphaned correction of ${slotWhere(s)}`}
                  className="mt-1 font-mono text-label font-semibold text-error hover:underline disabled:opacity-50"
                >
                  Discard
                </button>
              )}
            </div>
          ))}
        </section>
      )}
      {children}
    </div>
  )
}

function JumpCard({ slot, onJump, children }: { slot: Slot; onJump: (slot: Slot) => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={() => onJump(slot)}
      className="block w-full text-left border border-outline-variant rounded-xl px-2.5 py-2 mb-2 bg-surface-container-lowest hover:border-secondary hover:bg-surface transition-colors"
    >
      {children}
    </button>
  )
}

function Card({ slot, userName, orphan, undone }: {
  slot: Slot; userName: (id: string | null) => string; orphan?: boolean; undone?: boolean
}) {
  const who = userName(slot.updatedBy)
  return (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <span className={orphan || undone ? 'font-mono text-label font-semibold uppercase tracking-[0.04em] text-outline' : 'font-mono text-label font-semibold uppercase tracking-[0.04em] text-secondary'}>
          {SLOT_KIND_LABEL[slot.kind] ?? slot.kind}
        </span>
        <span className="font-mono text-label text-on-surface-variant truncate">{slotWhere(slot)}</span>
      </div>
      <p className={orphan ? 'text-xs text-outline mt-1 line-clamp-3' : 'text-xs text-on-surface mt-1 line-clamp-3'}>
        {undone ? slot.text : slot.humanText ?? slot.text}
      </p>
      <p className="font-mono text-label text-outline mt-1">
        {orphan && 'The code changed, so it is kept but not printed. '}
        {undone && 'Back to the LLM’s text on the page. The Word file keeps the correction until it is updated. '}
        {who || 'Someone'}{slot.updatedAt ? ` · ${formatShortDate(slot.updatedAt)}` : ''}
      </p>
    </>
  )
}
