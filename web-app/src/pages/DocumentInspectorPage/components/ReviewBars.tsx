import { Button, Icon } from '../../../components/ui'
import { reexportActive, useReexportFinished, useReexportVersion } from '../../../hooks/useReview'
import { cn } from '../../../lib/cn'
import { formatDateTime } from '../../../lib/format'
import type { Document, ExportReadiness } from '../../../types'

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

/** Above the document, its review state when it asks for something (documents.html
 *  paintReviewBanner): approved and locked; sent back with the admin's comment; ready for an
 *  admin's decision. In review says nothing here: the Review tab has it. */
export function ReviewStateBanner({
  doc, versionTag, isAdmin, isMine, changesBy, changesAt, onReopen, onOpenReview,
}: {
  doc: Document
  /** The document's version, as its cover names it. */
  versionTag: string
  isAdmin: boolean
  /** The signed-in user reviews it. */
  isMine: boolean
  /** Who asked for changes, and when (the record's last `changes_requested`). */
  changesBy?: string | null
  changesAt?: string | null
  onReopen: () => void
  /** Bring the Review tab forward. */
  onOpenReview: () => void
}) {
  const r = doc.review
  if (doc.status === 'approved') {
    const at = formatDateTime(r.approvedAt)
    return (
      <StateBanner
        tone="ok"
        icon="lock"
        action={isAdmin ? <BannerAction tone="ok" icon="lock_open" label="Reopen…" onClick={onReopen} /> : undefined}
      >
        {r.carriedFrom
          ? <><b>Approved in {r.carriedFrom.tag}.</b> The content is unchanged in {versionTag}, so the approval carries.</>
          : <><b>Approved</b>{r.approvedBy ? ` by ${r.approvedBy.name}` : ''}{at ? ` · ${at}` : ''}.</>}
        {' '}Locked: no corrections.{isAdmin ? '' : ' An admin can reopen it.'}
      </StateBanner>
    )
  }
  if (doc.status === 'changes_requested') {
    const at = formatDateTime(changesAt)
    return (
      <StateBanner
        tone="bad"
        icon="undo"
        action={isMine ? <BannerAction tone="bad" label="Submit again…" onClick={onOpenReview} /> : undefined}
      >
        <b>Changes requested</b>{changesBy ? ` by ${changesBy}` : ''}{at ? ` · ${at}` : ''}
        {r.changesComment && <span className="block text-on-surface mt-0.5">“{r.changesComment}”</span>}
      </StateBanner>
    )
  }
  if (doc.status === 'submitted' && isAdmin) {
    return (
      <StateBanner
        tone="info"
        icon="pending_actions"
        action={<BannerAction tone="info" label="Approve or request changes…" onClick={onOpenReview} />}
      >
        <b>Ready for approval.</b> {doc.reviewer?.name ?? 'Its reviewer'} submitted it{r.comment ? <>: “{r.comment}”</> : '.'}
      </StateBanner>
    )
  }
  return null
}

const STATE_TONE = {
  ok: { box: 'bg-[#f0fdf9] border-[#86efac] text-[#065f46]', icon: 'text-[#00a572]', act: 'border-[#86efac] text-[#065f46]' },
  bad: { box: 'bg-[#fff1f0] border-[#f5a3a3] text-on-error-container', icon: 'text-error', act: 'border-[#f5a3a3] text-error' },
  info: { box: 'bg-surface-container-low border-[#b9cdf5] text-on-surface', icon: 'text-secondary', act: 'border-[#8ab0f0] text-secondary' },
} as const

function StateBanner({ tone, icon, action, children }: {
  tone: keyof typeof STATE_TONE; icon: string; action?: React.ReactNode; children: React.ReactNode
}) {
  const t = STATE_TONE[tone]
  return (
    <div role="status" className={cn('mb-4 flex items-start gap-2.5 px-3.5 py-2.5 rounded-xl border text-xs leading-[1.45]', t.box)}>
      <Icon name={icon} size={18} className={cn('flex-shrink-0', t.icon)} />
      <p className="flex-1 min-w-0">{children}</p>
      {action}
    </div>
  )
}

function BannerAction({ tone, icon, label, onClick }: {
  tone: keyof typeof STATE_TONE; icon?: string; label: string; onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('ml-auto flex-shrink-0 inline-flex items-center gap-1 px-2.5 py-[5px] rounded-lg border bg-white font-mono text-label font-semibold hover:opacity-90', STATE_TONE[tone].act)}
    >
      {icon && <Icon name={icon} size={13} />}
      {label}
    </button>
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
