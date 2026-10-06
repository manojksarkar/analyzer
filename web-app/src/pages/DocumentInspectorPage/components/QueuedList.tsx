import { Icon, Text } from '../../../components/ui'
import { formatShortDate } from '../../../lib/format'
import { kindWords, useRegenerationQueue } from '../../../hooks/useReview'
import { slotRef } from '../outline'

/* R10, read-only: this document's texts the next run rewrites, because a correction they were
   written from has changed (API spec §15) — the version's others only counted. Recorded at save
   time, drained by a run — nothing clears them on a timer. A text is matched by its kind and its
   whole key against the page's slots (a function's description and its input and output names
   share a key) and the key shown as the server gave it — never taken apart. */

/** A key for the eye: a behaviour row's and a node label's keys join their two ids with U+0001,
 *  shown as a visible mark. */
function shownKey(key: string): string {
  // eslint-disable-next-line no-control-regex -- behaviour-row and node-label keys join their parts with U+0001
  return key.replace(/[\u0000-\u001f]+/g, ' · ')
}

export function QueuedList({ projectId, versionId, slotRefs }: {
  projectId: string
  versionId: string
  /** The texts this document prints (its slots), each as `slotRef(kind, key)`. */
  slotRefs: Set<string>
}) {
  const { data, isLoading, isError } = useRegenerationQueue(projectId, versionId)
  const items = (data ?? []).filter((q) => slotRefs.has(slotRef(q.slotKind, q.slotKey)))
  const elsewhere = (data?.length ?? 0) - items.length
  return (
    <section aria-label="Queued for the next run" className="mt-4">
      <Text as="p" variant="label" className="block text-on-surface-variant tracking-[0.06em] mb-1">
        Queued for the next run{data ? ` (${items.length})` : ''}
      </Text>
      <Text as="p" variant="caption" className="mb-2">
        Texts in this document written from wording that has since been corrected. The next run rewrites them.
      </Text>
      {isLoading && <Text as="p" variant="caption" className="font-mono">Loading…</Text>}
      {isError && (
        <p className="flex items-center gap-1 text-caption text-error"><Icon name="error" size={14} />Could not read the queue.</p>
      )}
      {data && !items.length && <Text as="p" variant="caption" className="font-mono">Nothing queued in this document.</Text>}
      {items.map((q) => (
        <div key={`${q.slotKind}:${q.slotKey}`} className="border border-outline-variant rounded-xl px-2.5 py-2 mb-2 bg-surface-container-lowest">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-label font-semibold uppercase tracking-[0.04em] text-on-surface-variant">
              {kindWords(q.slotKind)}
            </span>
            {q.requestedAt && <span className="font-mono text-label text-outline flex-shrink-0">{formatShortDate(q.requestedAt)}</span>}
          </div>
          <p className="font-mono text-label text-on-surface mt-0.5 truncate" title={shownKey(q.slotKey)}>
            {q.label ?? shownKey(q.slotKey)}
          </p>
          {q.reason && <p className="text-xs text-on-surface-variant mt-1">{q.reason}</p>}
          {q.causedBy && (
            <p className="font-mono text-label text-outline mt-1 truncate" title={shownKey(q.causedBy.slotKey)}>
              Caused by a correction to the {kindWords(q.causedBy.slotKind)} {q.causedBy.label ?? shownKey(q.causedBy.slotKey)}
            </p>
          )}
        </div>
      ))}
      {elsewhere > 0 && (
        <Text as="p" variant="caption" className="font-mono">
          {elsewhere} more in other documents of this version.
        </Text>
      )}
    </section>
  )
}
