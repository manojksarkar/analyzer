import { Button, Icon, Modal, Text } from '../../../components/ui'
import type { VersionJob } from '../../../types'

/* Stop the web job at work on a version (POST /jobs/{id}/cancel). What it costs depends on the
   job: documents being added to the version keep what is finished; the version's own run is
   removed with everything it made so far. */

const ADDS_DOCUMENTS = ['export', 'reexport']

export function StopRunDialog({ job, busy, onConfirm, onClose }: {
  job: VersionJob
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const adds = ADDS_DOCUMENTS.includes(job.mode)
  return (
    <Modal open onClose={onClose} title={adds ? 'Stop making these documents?' : 'Cancel this generation?'}
           className="max-w-[440px]">
      <div className="-mt-3 space-y-3 text-xs text-on-surface">
        {adds ? (
          <p className="leading-relaxed">
            The run stops now. Components already finished keep their documents; the one being made
            and those waiting show as <b>Stopped</b>, and can be generated again later.
          </p>
        ) : (
          <p className="leading-relaxed text-[#991b1b]">
            The run stops now and <b>this version is removed</b>, with everything made so far. To keep
            what is made, let it finish.
          </p>
        )}
        <Text as="p" variant="caption" className="font-mono">Job {job.id}</Text>
      </div>
      <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
        <Button variant="outline" size="sm" onClick={onClose}>Keep running</Button>
        <Button variant="danger" size="sm" loading={busy} onClick={onConfirm}>
          <Icon name="stop_circle" size={14} />{adds ? 'Stop' : 'Cancel generation'}
        </Button>
      </div>
    </Modal>
  )
}
