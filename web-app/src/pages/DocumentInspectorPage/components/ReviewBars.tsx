import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { formatDateTime } from '../../../lib/format'
import type { Document } from '../../../types'

/* Review & update: what edit mode says above the document. The Word file's banner is
   WordFileBanner.tsx. */

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
  ok: { box: 'bg-state-done-bg border-success-line text-state-done', icon: 'text-success', act: 'border-success-line text-state-done' },
  bad: { box: 'bg-violet-bg border-violet-line text-on-surface', icon: 'text-violet', act: 'border-violet-line text-violet' },
  info: { box: 'bg-surface-container-low border-info-line text-on-surface', icon: 'text-secondary', act: 'border-secondary-container/50 text-secondary' },
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
      className={cn('ml-auto flex-shrink-0 inline-flex items-center gap-1 px-2.5 py-[5px] rounded-lg border bg-surface-container-lowest font-mono text-label font-semibold hover:opacity-90', STATE_TONE[tone].act)}
    >
      {icon && <Icon name={icon} size={13} />}
      {label}
    </button>
  )
}

/** What holds edit mode: an update writing this document's Word file (corrections to its
 *  component wait — the server answers 409 `WORD_FILE_UPDATING`; every other document stays
 *  editable), the rebuild of every file, or a run rebuilding the version. */
export type EditHold = 'update' | 'rebuild' | 'run' | null

/** The sticky line that says edit mode is on, and how it works — or what it waits for. */
export function EditBar({ hold }: { hold: EditHold }) {
  return (
    <div className="sticky top-0 z-10 flex items-center gap-2.5 px-6 py-2 bg-surface-container-low border-b border-info-line">
      <Icon name={hold === 'update' || hold === 'rebuild' ? 'hourglass_top' : 'edit_note'} size={18} className="text-secondary" />
      <p className="flex-1 text-caption text-on-surface">
        {hold === 'update' ? (
          <><b>Updating this document’s Word file.</b> Corrections wait until it is done.</>
        ) : hold === 'rebuild' ? (
          <><b>Rebuilding the Word files.</b> Corrections wait until it is done.</>
        ) : hold === 'run' ? (
          <><b>Editing is paused</b> while a run rebuilds this document. It comes back when that ends.</>
        ) : (
          <>
            <b>Editing.</b> Click an outlined text to correct it — it saves when you leave the box
            (<kbd className="font-mono text-label border border-outline-variant border-b-2 rounded px-1 bg-surface-container-lowest">Enter</kbd>;
            {' '}<kbd className="font-mono text-label border border-outline-variant border-b-2 rounded px-1 bg-surface-container-lowest">Esc</kbd> cancels).
            Text that comes from the code stays as it is. Flowcharts: <b>Edit flowchart</b> on each one.
          </>
        )}
      </p>
    </div>
  )
}
