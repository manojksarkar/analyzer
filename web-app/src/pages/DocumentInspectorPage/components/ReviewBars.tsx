import { Button, Icon } from '../../../components/ui'
import { reexportActive, useReexportFinished, useReexportVersion } from '../../../hooks/useReview'
import type { ExportReadiness } from '../../../types'

/* Review & update: what edit mode says above the document. */

/** Whether the version's Word files have every correction (R9), and Re-export for an admin. */
export function ReadinessBanner({
  projectId, versionId, readiness, isAdmin,
}: {
  projectId: string
  versionId: string
  readiness: ExportReadiness | undefined
  isAdmin: boolean
}) {
  const reexport = useReexportVersion(projectId, versionId)
  useReexportFinished(projectId, readiness)
  if (!readiness) return null

  if (reexportActive(readiness)) {
    return (
      <Banner icon="autorenew" spin>
        <b>Re-exporting the Word files…</b> The corrections are being written into SWE.3 and SWE.4.
        Editing is paused until it ends.
      </Banner>
    )
  }
  if (!readiness.stale && !readiness.pendingRenders) {
    return readiness.failedRenders ? (
      <Banner icon="image_not_supported">
        {readiness.failedRenders} flowchart picture{readiness.failedRenders === 1 ? '' : 's'} could not be redrawn
        for the Word file. Its text is up to date.
      </Banner>
    ) : null
  }
  const n = readiness.overrideCount
  return (
    <Banner
      icon="warning"
      action={isAdmin ? (
        <Button size="sm" loading={reexport.isPending} onClick={() => reexport.mutate()}
          className="bg-[#b45309] hover:bg-[#92400e] text-white font-mono text-label">
          <Icon name="sync" size={14} />Re-export
        </Button>
      ) : undefined}
    >
      <b>The Word files don’t have the latest corrections yet</b>
      {n ? ` (${n} correction${n === 1 ? '' : 's'} in this version)` : ''}. The page shows them; Download
      still gives the old text until the Word files are re-exported.
      {!isAdmin && ' An admin can re-export.'}
    </Banner>
  )
}

function Banner({ icon, spin, action, children }: {
  icon: string; spin?: boolean; action?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div role="status" className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl border bg-[#fffbeb] border-[#fcd34d]">
      <Icon name={icon} size={18} className={spin ? 'text-[#b45309] animate-spin' : 'text-[#b45309]'} />
      <p className="flex-1 min-w-0 text-caption text-[#92400e]">{children}</p>
      {action}
    </div>
  )
}

/** The sticky line that says edit mode is on, and how it works. */
export function EditBar({ locked }: { locked: boolean }) {
  return (
    <div className="sticky top-0 z-10 flex items-center gap-2.5 px-6 py-2 bg-surface-container-low border-b border-[#b9cdf5]">
      <Icon name="edit_note" size={18} className="text-secondary" />
      <p className="flex-1 text-caption text-on-surface">
        {locked ? (
          <><b>Editing is paused</b> while a run or a re-export rebuilds this document. It comes back when that ends.</>
        ) : (
          <>
            <b>Editing.</b> Click an outlined text to correct it — it saves when you leave the box
            (<kbd className="font-mono text-label border border-outline-variant border-b-2 rounded px-1 bg-white">Enter</kbd>;
            {' '}<kbd className="font-mono text-label border border-outline-variant border-b-2 rounded px-1 bg-white">Esc</kbd> cancels).
            Text that comes from the code stays as it is. Flowcharts: <b>Edit flowchart</b> on each one.
          </>
        )}
      </p>
    </div>
  )
}
