import { useState } from 'react'
import { Button, Modal, Text, toast } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { EditSession } from '../editSession'

/* Cancel beside Done in edit mode (docs/ui-mockups/documents.html#cancel, compare.html#cancel).
   Nothing changed since Edit: it just leaves. Otherwise it asks, then puts each text back as it
   was before Edit (editSession.ts) and leaves. */

export function CancelEdit({ session, onLeave, size = 'md', labelsNote = false }: {
  session: EditSession
  /** Leave edit mode (no "Word file out of date" suggestion: nothing was meant to change). */
  onLeave: () => void
  /** `md`: the reader's Subbar; `sm`: the compare page's pane header. */
  size?: 'md' | 'sm'
  /** Say that flowchart labels stay (the reader, where they are corrected in their own dialog). */
  labelsNote?: boolean
}) {
  const [asking, setAsking] = useState<number | null>(null)
  const [checking, setChecking] = useState(false)

  async function cancel() {
    setChecking(true)
    const n = await session.pending()
    setChecking(false)
    if (n) setAsking(n)
    else onLeave()
  }

  async function discard() {
    const { done, failed } = await session.discard()
    setAsking(null)
    onLeave()
    if (done) {
      toast.success(`${done} correction${done === 1 ? '' : 's'} discarded`,
        'Each text is back as it was before you pressed Edit.')
    }
    if (failed.length) {
      toast.error(`${failed.length} text${failed.length === 1 ? '' : 's'} not put back`, failed[0])
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => { void cancel() }}
        disabled={checking || session.discarding}
        title="Leave edit mode and put back the texts you corrected"
        className={cn(
          'flex items-center border border-outline-variant text-on-surface-variant bg-surface-container-lowest hover:bg-surface-container-low transition-colors font-mono disabled:opacity-45',
          size === 'md' ? 'gap-1.5 px-3 py-1.5 rounded-lg text-caption font-bold tracking-[0.04em]' : 'gap-1 px-2 py-0.5 rounded text-label',
        )}
      >
        {size === 'md' ? 'CANCEL' : 'Cancel'}
      </button>
      {asking !== null && (
        <Modal
          open
          onClose={() => { if (!session.discarding) setAsking(null) }}
          title="Discard your corrections?"
          className="max-w-[440px]"
        >
          <div className="-mt-3">
            <Text as="p" variant="body" className="text-on-surface-variant leading-relaxed">
              Discard the <strong className="text-on-surface">{asking === 1 ? '1 correction' : `${asking} corrections`}</strong> made
              since you pressed Edit? Each text goes back to what it was before.
              {labelsNote && ' Flowchart labels saved in their own dialog stay.'}
            </Text>
            <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
              <Button type="button" variant="outline" size="sm" disabled={session.discarding} onClick={() => setAsking(null)}>
                Keep editing
              </Button>
              <Button type="button" size="sm" loading={session.discarding} onClick={() => { void discard() }}
                      className="bg-error text-on-status border border-error hover:bg-error/90">
                Discard
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </>
  )
}
