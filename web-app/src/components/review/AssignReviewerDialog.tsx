import { useState } from 'react'
import { useTeam } from '../../hooks/useProjects'
import { useAssignReviewer, useAssignReviewerBatch } from '../../hooks/useApproval'
import { Avatar, Button, Icon, Modal, RoleBadge, Skeleton, Text } from '../ui'
import { cn } from '../../lib/cn'
import type { Document } from '../../types'

/* Assign one reviewer to one or several documents (A1 / A2). One reviewer per document: this
   replaces the reviewer a document has. An approved document is skipped — reopen it first. Each
   member shows how many open reviews they have, so the work can be spread. Used by the documents
   list (row and batch bar), the reader's Review tab and the Overview's review queue. */

const docLabel = (d: Pick<Document, 'name' | 'process'>) => `${d.name} (${d.process})`

export function AssignReviewerDialog({
  projectId, documents, allDocuments, onClose, onDone,
}: {
  projectId: string
  /** The documents to assign. */
  documents: Document[]
  /** The version's documents, for each member's count of open reviews. */
  allDocuments?: Document[]
  onClose: () => void
  onDone?: () => void
}) {
  const { data: team, isLoading } = useTeam(projectId)
  const assignOne = useAssignReviewer(projectId)
  const assignMany = useAssignReviewerBatch(projectId)
  const open = documents.filter((d) => d.status !== 'approved')
  const skipped = documents.length - open.length
  const [pick, setPick] = useState<string | null>(
    documents.length === 1 ? documents[0].reviewer?.userId ?? null : null,
  )
  const members = (team ?? []).filter((m) => !m.pending && m.userId)
  const picked = members.find((m) => m.userId === pick)
  const busy = assignOne.isPending || assignMany.isPending
  const load = (userId: string) =>
    (allDocuments ?? documents).filter((d) => d.reviewer?.userId === userId && d.status !== 'approved').length
  // Assigning a document to the reviewer it already has changes nothing.
  const changes = open.filter((d) => d.reviewer?.userId !== pick)

  function submit() {
    if (!picked?.userId || !changes.length) return
    const done = () => { onDone?.(); onClose() }
    if (changes.length === 1) {
      assignOne.mutate({ docId: changes[0].id, userId: picked.userId, name: picked.name }, { onSuccess: done })
    } else {
      assignMany.mutate({ docIds: changes.map((d) => d.id), userId: picked.userId, name: picked.name }, { onSuccess: done })
    }
  }

  const n = open.length
  return (
    <Modal
      open
      onClose={onClose}
      title={`Assign a reviewer · ${n} document${n === 1 ? '' : 's'}`}
      className="max-w-[460px]"
    >
      <div className="-mt-3 space-y-3">
        <Text as="p" variant="caption" className="leading-snug">
          {open.slice(0, 4).map(docLabel).join(' · ')}{open.length > 4 ? ` and ${open.length - 4} more` : ''}
        </Text>
        <div className="max-h-[300px] overflow-y-auto space-y-1.5 pr-0.5">
          {isLoading && Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-11" />)}
          {!isLoading && members.length === 0 && (
            <Text as="p" variant="caption" className="font-mono">No active members to assign.</Text>
          )}
          {members.map((m) => {
            const on = pick === m.userId
            const k = load(m.userId as string)
            return (
              <button
                key={m.id}
                type="button"
                onClick={() => setPick(m.userId as string)}
                aria-pressed={on}
                className={cn(
                  'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-xl border text-left transition-colors',
                  on ? 'border-secondary bg-surface-container-low' : 'border-outline-variant hover:border-secondary hover:bg-surface',
                )}
              >
                <Avatar person={{ userId: m.userId as string, name: m.name, initials: m.initials }} size={28} />
                <span className="flex-1 min-w-0">
                  <span className="flex items-center gap-1.5">
                    <span className="text-body text-on-surface truncate">{m.name}</span>
                    <RoleBadge role={m.role} />
                  </span>
                  <span className="block font-mono text-label text-outline mt-px">{k} open review{k === 1 ? '' : 's'}</span>
                </span>
                {on && <Icon name="check" size={18} className="text-secondary flex-shrink-0" />}
              </button>
            )
          })}
        </div>
        <p className="flex items-start gap-1.5 text-caption text-on-surface-variant leading-snug">
          <Icon name="info" size={14} className="mt-px flex-shrink-0" />
          <span>
            One reviewer per document: this replaces the reviewer it has.{' '}
            {picked ? picked.name.split(' ')[0] : 'The reviewer'} gets a notification.
          </span>
        </p>
        {skipped > 0 && (
          <p className="text-caption text-warn leading-snug">
            {skipped} approved document{skipped === 1 ? ' is' : 's are'} skipped: reopen {skipped === 1 ? 'it' : 'them'} first.
          </p>
        )}
        {picked && open.length > 0 && changes.length === 0 && (
          <p className="text-caption text-on-surface-variant">{picked.name} already reviews {open.length === 1 ? 'it' : 'them'}.</p>
        )}
      </div>
      <div className="flex justify-end gap-2 pt-4 mt-4 -mx-6 px-6 border-t border-outline-variant">
        <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
        <Button size="sm" loading={busy} disabled={!picked || changes.length === 0} onClick={submit}>
          <Icon name="person_add" size={14} />Assign
        </Button>
      </div>
    </Modal>
  )
}
