import { Button, Icon, Modal, Text } from '../../../components/ui'
import type { BulkApprovePlan } from '../helpers'

/* Approve several (A9): only the selected documents that are Ready for approval and whose Word
   file has every correction. The dialog names how many that is, and how many are skipped. */

const docLabel = (d: { name: string; process: string }) => `${d.name} (${d.process})`

export function BulkApproveDialog({
  plan, busy, onConfirm, onClose,
}: {
  plan: BulkApprovePlan
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const n = plan.ready.length
  const skip = plan.skipped.length
  const checking = plan.checking.length
  const reasons = [...new Set(plan.skipped.map((s) => s.reason))]
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
        {skip > 0 && (
          <p className="text-caption text-[#b45309] leading-snug">
            {skip} other selected document{skip === 1 ? ' is' : 's are'} skipped: {reasons.join(', or ')}.
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
          className="bg-[#00a572] hover:bg-[#008a5f] disabled:bg-[#00a572]/40"
        >
          <Icon name="check_circle" size={14} />Approve {n}
        </Button>
      </div>
    </Modal>
  )
}
