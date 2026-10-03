import { useState } from 'react'
import { Button, Icon, Modal, Text } from '../../../components/ui'
import { useApproveDocument, useReopenDocument, useRequestChanges } from '../../../hooks/useApproval'
import { cn } from '../../../lib/cn'
import type { Document } from '../../../types'
import { MAX_COMMENT } from '../review'

/* The reader's three review dialogs (documents.html renderModal): approve (an optional comment;
   it locks the document), request changes (a comment is required) and reopen (a reason is
   required). Each says what will happen before it happens. */

const docLabel = (d: Pick<Document, 'name' | 'process'>) => `${d.name} (${d.process})`

export function CommentBox({
  value, onChange, placeholder, label, id, autoFocus,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  label: string
  id: string
  autoFocus?: boolean
}) {
  return (
    <div>
      <label htmlFor={id} className="block font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline mb-1">{label}</label>
      <textarea
        id={id}
        value={value}
        maxLength={MAX_COMMENT}
        rows={3}
        autoFocus={autoFocus}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full resize-y min-h-16 rounded-lg border border-outline-variant px-2 py-1.5 text-xs leading-[1.45] text-on-surface outline-none focus:border-secondary focus:ring-2 focus:ring-secondary/30"
      />
    </div>
  )
}

function Footer({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
      <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
      {children}
    </div>
  )
}

function Note({ icon, children, className }: { icon: string; children: React.ReactNode; className?: string }) {
  return (
    <p className={cn('flex items-start gap-1.5 text-caption text-on-surface-variant leading-snug', className)}>
      <Icon name={icon} size={14} className="mt-px flex-shrink-0" />
      <span>{children}</span>
    </p>
  )
}

export function ApproveDialog({
  projectId, doc, corrections, blocked, onClose, onDone,
}: {
  projectId: string
  doc: Document
  /** Corrections in force in this document (null: not counted here). */
  corrections: number | null
  /** Why it cannot be approved now (the Word file, a re-export); null when it can. */
  blocked: string | null
  onClose: () => void
  /** After the approval (edit mode closes: the document is locked). */
  onDone?: () => void
}) {
  const approve = useApproveDocument(projectId)
  const [comment, setComment] = useState('')
  const direct = doc.status === 'in_review'
  return (
    <Modal open onClose={onClose} title={`Approve ${docLabel(doc)}`} className="max-w-[460px]">
      <div className="-mt-3 space-y-3">
        <div className="rounded-xl border border-[#b9cdf5] bg-surface-container-low px-3 py-2.5 text-xs text-on-surface leading-[1.7]">
          <p className="flex items-start gap-1.5">
            <Icon name="person" size={14} className="mt-[3px] flex-shrink-0" />
            <span>
              Reviewed by <b>{doc.reviewer?.name ?? 'nobody'}</b>
              {direct ? '. Not submitted: you approve it directly.' : doc.review.comment ? <>: “{doc.review.comment}”</> : ''}
            </span>
          </p>
          {corrections !== null && (
            <p className="flex items-center gap-1.5">
              <Icon name="edit_note" size={14} />{corrections} correction{corrections === 1 ? '' : 's'}
            </p>
          )}
          <p className="flex items-start gap-1.5">
            <Icon name="description" size={14} className="mt-[3px] flex-shrink-0" />
            {blocked ? <span className="text-[#b45309]">{blocked}.</span> : 'The Word file is up to date. Its hash is recorded with the approval.'}
          </p>
        </div>
        <CommentBox id="approve-comment" label="Comment (optional)" value={comment} onChange={setComment}
          placeholder="Anything the record should say" />
        <Note icon="lock">
          Approving locks the document: no corrections until an admin reopens it.
          {doc.process === 'SWE.4' && ' The flowchart labels of its SWE.3 lock too: its test steps are built from them.'}
        </Note>
      </div>
      <Footer onClose={onClose}>
        <Button
          size="sm"
          loading={approve.isPending}
          disabled={!!blocked}
          onClick={() => approve.mutate({ docId: doc.id, comment: comment.trim() || null }, { onSuccess: () => { onDone?.(); onClose() } })}
          className="bg-[#00a572] hover:bg-[#008a5f] disabled:bg-[#00a572]/40"
        >
          <Icon name="check_circle" size={14} />Approve
        </Button>
      </Footer>
    </Modal>
  )
}

export function RequestChangesDialog({ projectId, doc, onClose }: { projectId: string; doc: Document; onClose: () => void }) {
  const send = useRequestChanges(projectId)
  const [comment, setComment] = useState('')
  const reviewer = doc.reviewer?.name ?? 'its reviewer'
  return (
    <Modal open onClose={onClose} title={`Request changes · ${docLabel(doc)}`} className="max-w-[460px]">
      <div className="-mt-3 space-y-3">
        <CommentBox id="changes-comment" label="What needs to change (required)" value={comment} onChange={setComment}
          placeholder={`${reviewer} sees this at the top of the document`} autoFocus />
        <Text as="p" variant="caption" className="leading-snug">
          It goes back to {reviewer}, who fixes it and submits it again.
        </Text>
      </div>
      <Footer onClose={onClose}>
        <Button
          size="sm"
          variant="outline"
          loading={send.isPending}
          disabled={!comment.trim()}
          onClick={() => send.mutate({ docId: doc.id, comment: comment.trim() }, { onSuccess: onClose })}
          className="border-[#f5a3a3] text-error hover:bg-[#fff1f0]"
        >
          <Icon name="undo" size={14} />Request changes
        </Button>
      </Footer>
    </Modal>
  )
}

export function ReopenDialog({ projectId, doc, onClose, onDone }: {
  projectId: string; doc: Document; onClose: () => void
  /** After the reopen (edit mode starts closed). */
  onDone?: () => void
}) {
  const reopen = useReopenDocument(projectId)
  const [reason, setReason] = useState('')
  return (
    <Modal open onClose={onClose} title={`Reopen ${docLabel(doc)}`} className="max-w-[460px]">
      <div className="-mt-3 space-y-3">
        <Text as="p" variant="caption" className="leading-snug">
          It goes back to In review{doc.reviewer ? ` with ${doc.reviewer.name} as its reviewer` : ''}, and corrections are
          allowed again. The approval stays in its activity.
        </Text>
        <CommentBox id="reopen-reason" label="Reason (required)" value={reason} onChange={setReason}
          placeholder="It goes on the record" autoFocus />
      </div>
      <Footer onClose={onClose}>
        <Button
          size="sm"
          loading={reopen.isPending}
          disabled={!reason.trim()}
          onClick={() => reopen.mutate({ docId: doc.id, reason: reason.trim() }, { onSuccess: () => { onDone?.(); onClose() } })}
        >
          <Icon name="lock_open" size={14} />Reopen
        </Button>
      </Footer>
    </Modal>
  )
}
