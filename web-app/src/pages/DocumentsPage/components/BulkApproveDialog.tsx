import { Button, Icon, Modal, Text } from '../../../components/ui'
import { plural } from '../../../lib/wordFiles'
import type { BulkApprovePlan } from '../helpers'

/* Approve several (A9; documents.html renderModal 'bulk'): only the selected documents that are
   Ready for approval and whose Word file is up to date. The ones whose file is out of date are
   named with *Update them* — this dialog's link starts the update, no second dialog; while a run
   holds the version, it says when instead. The rest are not ready for approval. */

const docLabel = (d: { name: string; process: string }) => `${d.name} (${d.process})`

export function BulkApproveDialog({
  plan, busy, onConfirm, onClose, update,
}: {
  plan: BulkApprovePlan
  busy: boolean
  onConfirm: () => void
  onClose: () => void
  /** The out-of-date files' update: every one of them updating already (`going`), why it cannot
   *  start now (`blocked`), or how to start it. */
  update: { going: boolean; blocked: string; onUpdate: () => void }
}) {
  const n = plan.ready.length
  const behind = plan.behind.length
  const other = plan.skipped.length
  const checking = plan.checking.length
  return (
    <Modal open onClose={onClose} title={`Approve ${n} document${n === 1 ? '' : 's'}`} className="max-w-[460px]">
      <div className="-mt-3 space-y-3 text-xs text-on-surface">
        {n > 0 ? (
          <p className="leading-relaxed">{plan.ready.map(docLabel).join(' · ')}</p>
        ) : checking === 0 ? (
          <p>None of the selected documents can be approved now.</p>
        ) : null}
        {checking > 0 && (
          <p className="flex items-center gap-1.5 text-on-surface-variant">
            <Icon name="progress_activity" size={14} className="animate-spin" />
            Checking the Word file of {checking} document{checking === 1 ? '' : 's'}…
          </p>
        )}
        {behind > 0 && (
          <p className="text-caption text-warn leading-snug" title={plan.behind.map(docLabel).join(', ')}>
            {plural(behind, 'Word file')} {behind === 1 ? 'is' : 'are'} out of date.{' '}
            {update.going ? 'Updating…' : update.blocked ? update.blocked : (
              <button type="button" onClick={update.onUpdate} className="text-secondary font-semibold hover:underline">
                Update {behind === 1 ? 'it' : 'them'}
              </button>
            )}
          </p>
        )}
        {other > 0 && (
          <p className="text-caption text-warn leading-snug" title={plan.skipped.map((s) => `${docLabel(s.doc)}: ${s.reason}`).join('\n')}>
            {plural(other, 'other selected document')} {other === 1 ? 'is' : 'are'} not ready for approval.
          </p>
        )}
        <Text as="p" variant="caption" className="leading-snug">
          Each is approved on its own record, with its Word file’s hash, and locked.
        </Text>
      </div>
      <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button
          size="sm"
          loading={busy}
          disabled={n === 0 || checking > 0}
          onClick={onConfirm}
          className="bg-on-tertiary-container hover:bg-[#008a5f] disabled:bg-on-tertiary-container/40"
        >
          <Icon name="check_circle" size={14} />Approve {n}
        </Button>
      </div>
    </Modal>
  )
}
