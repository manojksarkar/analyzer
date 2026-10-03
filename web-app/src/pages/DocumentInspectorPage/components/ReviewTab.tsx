import { useState } from 'react'
import { Avatar, Button, Icon, StatusBadge, Text } from '../../../components/ui'
import { useClaimDocument, useDocumentEvents, useSubmitForApproval } from '../../../hooks/useApproval'
import { useReexportVersion } from '../../../hooks/useReview'
import { cn } from '../../../lib/cn'
import { formatDateTime } from '../../../lib/format'
import { describeEvent, eventMeta, shortHash, wordFileOutOfDate } from '../../../lib/reviewStatus'
import type { Document, ExportReadiness, ReviewEvent } from '../../../types'
import { MAX_COMMENT, reviewAction, type ReviewCtx } from '../review'

/* The reader's Review tab (documents.html renderReviewTab): the document's state, its reviewer,
   whether its Word file has every correction (R9 for its component and type), the one action
   this role can take now, and the activity that is the review record (A10). Every document has
   it, SWE.3 and SWE.4 alike. */

export function ReviewTab({
  projectId, versionId, doc, versionTag, ctx, readiness, readinessFailed, corrections, isSwe3, nameOf,
  onAssign, onApprove, onChanges, onReopen, onSubmitted,
}: {
  projectId: string
  versionId: string
  doc: Document
  /** The document's version, as its cover names it. */
  versionTag: string
  ctx: ReviewCtx
  /** R9 for this document (A15). */
  readiness: ExportReadiness | undefined
  /** R9 could not be read (a version without its database answers 503). */
  readinessFailed?: boolean
  /** Corrections in force in this document; null where they are not counted (SWE.4). */
  corrections: number | null
  isSwe3: boolean
  nameOf: (userId: string) => string | undefined
  onAssign: () => void
  onApprove: () => void
  onChanges: () => void
  onReopen: () => void
  /** After a submit: edit mode closes. */
  onSubmitted: () => void
}) {
  const { data: events, isLoading: eventsLoading } = useDocumentEvents(projectId, doc.id)
  const claim = useClaimDocument(projectId)
  const submit = useSubmitForApproval(projectId)
  const reexport = useReexportVersion(projectId, versionId)
  const [comment, setComment] = useState('')
  const [nudge, setNudge] = useState(false)

  const action = reviewAction(doc, ctx)
  const lastOf = (kind: ReviewEvent['kind']) => events?.find((e) => e.kind === kind)
  const n = corrections ?? 0
  const corr = `${n} correction${n === 1 ? '' : 's'}`

  function doSubmit() {
    const c = comment.trim()
    if (!c) { setNudge(true); return }
    submit.mutate({ docId: doc.id, comment: c }, { onSuccess: () => { setComment(''); setNudge(false); onSubmitted() } })
  }

  /* ── the Word file: up to date, missing corrections, or being rebuilt ── */
  const word = ctx.reexporting ? <span className="text-[#b45309]">re-exporting…</span>
    : !readiness ? <span className="text-outline">{readinessFailed ? 'not checked' : '…'}</span>
      : wordFileOutOfDate(readiness) ? (
        <>
          <span className="text-[#b45309]" title={readiness.explanation ?? undefined}>
            {readiness.pendingRenders && !readiness.stale
              ? `${readiness.pendingRenders} picture${readiness.pendingRenders === 1 ? '' : 's'} missing`
              : 'corrections missing'}
          </span>
          {ctx.isAdmin && (
            <button
              type="button"
              disabled={reexport.isPending}
              onClick={() => reexport.mutate()}
              title="Re-export the version's Word files"
              className="text-secondary font-mono text-label font-semibold hover:underline disabled:opacity-50"
            >
              Re-export
            </button>
          )}
        </>
      ) : <span className="text-[#00a572]">up to date</span>

  /* ── the one action ── */
  let body: React.ReactNode
  switch (action.kind) {
    case 'approved': {
      const ap = lastOf('approved')
      const by = doc.review.approvedBy ?? ap?.actor ?? null
      const at = doc.review.approvedAt ?? ap?.at ?? null
      const sha = doc.review.docxSha256 ?? (typeof ap?.payload.docx_sha256 === 'string' ? ap.payload.docx_sha256 : null)
      const carried = doc.review.carriedFrom
      body = (
        <>
          <Box tone="ok">
            <span className="block font-mono text-label font-semibold uppercase tracking-[0.06em] text-[#00a572] mb-0.5">Approved</span>
            {carried
              ? <>In {carried.tag}. The content is unchanged in {versionTag}, so the approval carries.</>
              : <>By {by?.name ?? 'an admin'}{at ? ` · ${formatDateTime(at)}` : ''}</>}
            {doc.review.approvalComment && <p className="text-on-surface mt-1">“{doc.review.approvalComment}”</p>}
            {sha && <p className="font-mono text-label text-on-surface-variant mt-1 break-all">Word file sha256 {shortHash(sha)}</p>}
          </Box>
          <Note icon="lock">Locked: no corrections.{ctx.isAdmin ? '' : ' An admin can reopen it.'}</Note>
          {action.canReopen && <ActionButton tone="outline" icon="lock_open" label="Reopen…" onClick={onReopen} />}
        </>
      )
      break
    }
    case 'assign':
      body = (
        <>
          <Note>Nobody reviews it yet.</Note>
          <ActionButton tone="primary" icon="person_add" label="Assign a reviewer…" onClick={onAssign} />
        </>
      )
      break
    case 'claim':
      body = (
        <>
          <Note>Nobody reviews it yet. Claim it to become its reviewer.</Note>
          <ActionButton tone="primary" icon="front_hand" label="Claim" loading={claim.isPending} onClick={() => claim.mutate(doc.id)} />
        </>
      )
      break
    case 'decide':
    case 'wait': {
      const sub = lastOf('submitted')
      body = (
        <>
          <Box tone="info">
            <span className="block font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline mb-0.5">
              {doc.reviewer ? `${doc.reviewer.name.split(' ')[0]}’s review` : 'The review'}
            </span>
            “{doc.review.comment ?? sub?.comment ?? ''}”
            <p className="font-mono text-label text-outline mt-1">
              {corrections !== null ? `${corr} · ` : ''}submitted {formatDateTime(sub?.at) ?? ''}
            </p>
          </Box>
          {action.kind === 'decide' ? (
            <>
              <ActionButton tone="ok" icon="check_circle" label="Approve…" onClick={onApprove} disabledWhy={action.approveBlocked} />
              {action.approveBlocked && <Why>{action.approveBlocked}.</Why>}
              <ActionButton tone="bad" icon="undo" label="Request changes…" onClick={onChanges} />
            </>
          ) : (
            <Note icon="hourglass_top">Waiting for an admin to approve it.</Note>
          )}
        </>
      )
      break
    }
    case 'submit': {
      const back = doc.status === 'changes_requested' ? lastOf('changes_requested') : undefined
      const backComment = doc.review.changesComment ?? back?.comment
      body = (
        <>
          {doc.status === 'changes_requested' && backComment && (
            <Box tone="bad" className="mb-2.5">
              <span className="block font-mono text-label font-semibold uppercase tracking-[0.06em] text-error mb-0.5">
                Changes requested{back ? ` · ${formatDateTime(back.at)}` : ''}
              </span>
              “{backComment}”
            </Box>
          )}
          <label htmlFor="review-comment" className="block font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline mb-1">
            {action.submitHeading}
          </label>
          <textarea
            id="review-comment"
            value={comment}
            maxLength={MAX_COMMENT}
            rows={3}
            placeholder="What you checked, and what you corrected"
            onChange={(e) => { setComment(e.target.value); if (nudge) setNudge(false) }}
            className={cn(
              'w-full resize-y min-h-16 rounded-lg border px-2 py-1.5 text-xs leading-[1.45] text-on-surface outline-none focus:border-secondary focus:ring-2 focus:ring-secondary/30',
              nudge ? 'border-error' : 'border-outline-variant',
            )}
          />
          {nudge && <Why>Say what you checked: the comment is the review record the admin approves on.</Why>}
          {corrections !== null && (
            <p className="font-mono text-label text-outline mt-1">{corr} in this document{isSwe3 ? ' · Edit to correct more' : ''}</p>
          )}
          <ActionButton tone="primary" icon="send" label="Submit for approval" loading={submit.isPending} onClick={doSubmit} />
          {action.directApprove && (
            <>
              <ActionButton tone="outline" icon="check_circle" label="Approve directly…" onClick={onApprove} disabledWhy={action.approveBlocked} />
              {action.approveBlocked && <Why>{action.approveBlocked}.</Why>}
            </>
          )}
        </>
      )
      break
    }
    default:
      body = <Note>{doc.reviewer?.name ?? 'Someone'} reviews it. You can read and download it.</Note>
  }

  return (
    <div className="flex-1 overflow-y-auto px-3 pt-2 pb-4">
      <Row k="Status">
        <StatusBadge status={doc.status} suffix={doc.review.carriedFrom ? ` · from ${doc.review.carriedFrom.tag}` : undefined} />
      </Row>
      <Row k="Reviewer">
        {doc.reviewer ? (
          <>
            <Avatar person={doc.reviewer} size={18} />
            <span className="truncate">{doc.reviewer.name}</span>
            {ctx.isAdmin && doc.status !== 'approved' && (
              <button type="button" onClick={onAssign} className="text-secondary font-mono text-label font-semibold hover:underline flex-shrink-0">Change</button>
            )}
          </>
        ) : <span className="text-[#b45309] font-semibold">Needs a reviewer</span>}
      </Row>
      <Row k="Word file">{word}</Row>

      <div className="py-3 border-b border-surface-container">{body}</div>

      <Text as="p" variant="label" className="text-outline tracking-[0.06em] mt-3 mb-2">Activity</Text>
      {eventsLoading && <Text as="p" variant="caption" className="font-mono">Loading…</Text>}
      {events && events.length === 0 && <Text as="p" variant="caption" className="font-mono">Nothing yet.</Text>}
      <ol>
        {(events ?? []).map((e, i, arr) => <TimelineItem key={e.id} e={e} last={i === arr.length - 1} nameOf={nameOf} meId={ctx.meId} />)}
      </ol>
    </div>
  )
}

function TimelineItem({ e, last, nameOf, meId }: {
  e: ReviewEvent; last: boolean; nameOf: (id: string) => string | undefined; meId: string
}) {
  const { actor, text } = describeEvent(e, { nameOf, meId })
  const sha = typeof e.payload.docx_sha256 === 'string' ? e.payload.docx_sha256 : null
  return (
    <li className="relative pl-4 pb-3">
      <span className={cn('absolute left-0.5 top-[5px] w-[7px] h-[7px] rounded-full', eventMeta(e.kind).dot)} aria-hidden />
      {!last && <span className="absolute left-[5px] top-[15px] bottom-0 w-px bg-surface-container" aria-hidden />}
      <p className="text-caption leading-[1.4] text-on-surface">{actor && <b className="font-semibold">{actor} </b>}{text}</p>
      {e.comment && <p className="text-caption leading-[1.4] text-on-surface-variant mt-0.5">“{e.comment}”</p>}
      {sha && <p className="font-mono text-label text-outline mt-0.5 break-all">Word file sha256 {shortHash(sha)}</p>}
      <p className="font-mono text-label text-outline mt-0.5">{formatDateTime(e.at)}</p>
    </li>
  )
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 py-[7px] border-b border-surface-container">
      <span className="font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline flex-shrink-0">{k}</span>
      <span className="flex items-center gap-1.5 min-w-0 text-caption text-on-surface text-right">{children}</span>
    </div>
  )
}

const BOX_TONE = {
  ok: 'bg-[#f0fdf9] border-[#86efac] text-[#065f46]',
  info: 'bg-surface-container-low border-[#b9cdf5] text-on-surface',
  bad: 'bg-[#fff1f0] border-[#f5a3a3] text-on-surface',
} as const

function Box({ tone, className, children }: { tone: keyof typeof BOX_TONE; className?: string; children: React.ReactNode }) {
  return <div className={cn('rounded-xl border px-2.5 py-2 text-caption leading-[1.45] break-words', BOX_TONE[tone], className)}>{children}</div>
}

function Note({ icon, children }: { icon?: string; children: React.ReactNode }) {
  return (
    <p className="text-caption text-on-surface-variant leading-[1.4] mt-1.5 first:mt-0">
      {icon && <Icon name={icon} size={13} className="mr-1 align-[-2px]" />}
      {children}
    </p>
  )
}

function Why({ children }: { children: React.ReactNode }) {
  return <p className="text-caption text-[#b45309] leading-[1.4] mt-1">{children}</p>
}

const BUTTON_TONE = {
  primary: { variant: 'primary', cls: 'bg-secondary text-white hover:bg-secondary-container border-transparent' },
  ok: { variant: 'primary', cls: 'bg-[#00a572] text-white hover:bg-[#008a5f] disabled:bg-[#00a572]/40 border-transparent' },
  bad: { variant: 'outline', cls: 'bg-white text-error border-[#f5a3a3] hover:bg-[#fff1f0]' },
  outline: { variant: 'outline', cls: 'bg-white text-on-surface border-outline-variant hover:bg-surface-container-low' },
} as const

function ActionButton({ tone, icon, label, onClick, loading, disabledWhy }: {
  tone: keyof typeof BUTTON_TONE
  icon: string
  label: string
  onClick: () => void
  loading?: boolean
  /** Off, and why (the button's title). */
  disabledWhy?: string | null
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant={BUTTON_TONE[tone].variant}
      loading={loading}
      disabled={!!disabledWhy}
      title={disabledWhy ?? undefined}
      onClick={onClick}
      className={cn('w-full mt-2 border font-mono text-caption', BUTTON_TONE[tone].cls)}
    >
      <Icon name={icon} size={14} />{label}
    </Button>
  )
}
