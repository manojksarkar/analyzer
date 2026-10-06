import { Button, Icon, Modal } from '../ui'
import { useUpdateWordFiles } from '../../hooks/useWordFiles'
import { componentsOf, plural, type DownloadAllChoice, type Wording } from '../../lib/wordFiles'

/* Download all while Word files are out of date (documents.html renderModal 'dlall'; W3): the
   files as they are, or the corrected files — updated first, then downloaded. This dialog's button
   is the confirmation: no second dialog. A developer's update reaches the ones they review. */

export function DownloadAllDialog({
  projectId, versionId, choice, isAdmin, fileName, words, onAsIs, onClose,
}: {
  projectId: string
  versionId: string
  choice: DownloadAllChoice
  isAdmin: boolean
  /** The zip's name. */
  fileName: string
  words: Wording
  /** Every Word file of the version as it is now. */
  onAsIs: () => void
  onClose: () => void
}) {
  const update = useUpdateWordFiles(projectId, versionId, words)
  const n = choice.files.length

  function corrected() {
    update.mutate({
      request: isAdmin
        ? { scope: 'out_of_date' }
        : { scope: 'out_of_date', components: componentsOf(choice.mine) },
      download: { versionId, fileName },
    })
    onClose()
  }

  return (
    <Modal open onClose={onClose} title="Download all Word files" className="max-w-[460px]">
      <div className="-mt-3 space-y-2">
        <p className="text-body text-on-surface">{plural(n, 'file')} {n === 1 ? 'is' : 'are'} out of date.</p>
        {choice.note && <p className="text-caption text-on-surface-variant leading-snug">{choice.note}</p>}
        {choice.blocked && <p className="text-caption text-on-surface-variant leading-snug">{choice.blocked}</p>}
      </div>
      <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button variant="outline" size="sm" onClick={() => { onAsIs(); onClose() }}>As they are</Button>
        {choice.mine.length > 0 && (
          // The tooltip sits on a wrapper: a disabled button gets no pointer events.
          <span title={choice.blocked || undefined}>
            <Button size="sm" disabled={!!choice.blocked} onClick={corrected}>
              <Icon name="sync" size={14} />Corrected files
            </Button>
          </span>
        )}
      </div>
    </Modal>
  )
}
