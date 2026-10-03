import { Button, Icon, Modal, Text } from '../ui'
import { addsDocuments } from '../../lib/runScope'

/* Ask before stopping a web job (POST /jobs/{id}/cancel): one click must not throw a run away.
   What it costs depends on the job: documents being added to a version keep what is finished;
   a version's own run is removed with everything it made so far. Used by the Overview's Cancel
   Job and the Components panel's Stop. */

export function StopRunDialog({ job, versionTag, busy, onConfirm, onClose }: {
  /** The job and its `mode` (`export` / `reexport` add documents; anything else is a generation). */
  job: { id: string; mode: string }
  /** The version the run makes, when known. */
  versionTag?: string | null
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const adds = addsDocuments(job.mode)
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
        <Text as="p" variant="caption" className="font-mono">
          Job {job.id}{versionTag ? ` · version ${versionTag}` : ''}
        </Text>
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
