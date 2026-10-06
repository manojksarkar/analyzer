import { Button, Icon, Modal } from '../ui'
import { useUpdateWordFiles } from '../../hooks/useWordFiles'
import {
  compNames, fileLabel, outOfDateWhy, plural, type UpdateAsk, type Wording,
} from '../../lib/wordFiles'
import type { OutOfDateFile } from '../../types'

/* Every update a button starts on its own asks first (WORD_FILE_UPDATES D7, W0; documents.html
   renderModal 'confirm'): the Word files it writes, each with why, and at most two notes — what
   waits while it runs, and that approved files are not changed. Rebuild all: its count and its
   cost. From a download: when the download starts. Buttons inside a dialog that already says what
   happens (Approve, bulk approve, Download all) and Submit start without this one. */

export function UpdateWordFilesDialog({
  projectId, versionId, ask, files, rebuildCount, documentId, words, onClose,
}: {
  projectId: string
  versionId: string
  ask: UpdateAsk
  /** The version's out-of-date Word files (R9 `outOfDate`). */
  files: OutOfDateFile[]
  /** Rebuild all: how many Word files it rewrites (every not-approved document of the version). */
  rebuildCount: number
  /** The document open (the reader, a row's download): sent as `document_id`. */
  documentId?: string
  words: Wording
  onClose: () => void
}) {
  const update = useUpdateWordFiles(projectId, versionId, words)
  const rebuild = !!ask.rebuild
  const writes = rebuild ? [] : files.filter((f) => !ask.components || ask.components.includes(f.component))
  const count = rebuild ? rebuildCount : writes.length
  const names = [...new Set(writes.map((f) => f.name))]
  const notes = rebuild
    ? ['Rewrites every file. Takes longer.', `Corrections to ${words.versionTag} wait until it is done.`]
    : ask.download
      ? ['The download starts when it is done.']
      : [`Corrections to ${compNames(names, true)} wait until it is done.`, 'Approved files are not changed.']

  function start() {
    update.mutate({
      request: rebuild
        ? { scope: 'all' }
        : { scope: 'out_of_date', components: ask.components ?? undefined, documentId },
      download: ask.download,
    })
    onClose()
  }

  return (
    <Modal open onClose={onClose} title={`${rebuild ? 'Rebuild' : 'Update'} ${plural(count, 'Word file')}`} className="max-w-[460px]">
      <div className="-mt-3 space-y-2">
        {!rebuild && (
          <div className="rounded-xl border border-[#b9cdf5] bg-surface-container-low px-3 py-2.5 text-xs text-on-surface leading-[1.7] max-h-[150px] overflow-auto">
            {writes.length ? (
              <ul aria-label="Word files it writes">
                {writes.map((f) => (
                  <li key={f.documentId}>
                    {fileLabel(f)} <span className="text-[#92400e]">· {outOfDateWhy(f)}</span>
                  </li>
                ))}
              </ul>
            ) : <p>Nothing is out of date now.</p>}
          </div>
        )}
        {notes.map((n) => (
          <p key={n} className="text-caption text-on-surface-variant leading-snug">{n}</p>
        ))}
      </div>
      <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" disabled={!count} onClick={start}>
          <Icon name={rebuild ? 'autorenew' : 'sync'} size={14} />{rebuild ? 'Rebuild' : 'Update'}
        </Button>
      </div>
    </Modal>
  )
}
