import { Avatar, Icon, StatusBadge, Text } from '../../../components/ui'
import { ProcessBadge } from '../../../components/ui/Badge'
import { WordFileMenu } from '../../../components/wordfiles/WordFileMenu'
import { cn } from '../../../lib/cn'
import { relativeTime } from '../../../lib/format'
import { describeEvent } from '../../../lib/reviewStatus'
import { cap, outOfDateWhy } from '../../../lib/wordFiles'
import type { Document, OutOfDateFile } from '../../../types'

/* One row of the documents list: who reviews it, its state, what happened last, and the one
   review action this role can take from the list (documents.html renderDocList). Its download
   (documents.html dlBtn): out of date — a small menu, the corrected file (updated first, after
   the confirm; the document in hand counts as the one open, so a developer may too) or the
   current file as it is; updating — a spinner; up to date or approved — a plain download. */
export function DocRow({
  doc, selected, isAdmin, isDeveloper, meId, nameOf, claimPending, wordFile, updating = false, correctedBlocked = '',
  onToggle, onOpen, onReview, onCompare, onDownload, onCorrected, onAssign, onClaim,
}: {
  doc: Document
  selected: boolean
  isAdmin: boolean
  isDeveloper: boolean
  meId: string
  nameOf: (userId: string) => string | undefined
  claimPending: boolean
  /** Its Word file is out of date (R9 `outOfDate`), and why. Never for an approved document: it
   *  downloads the file that was approved. */
  wordFile?: OutOfDateFile
  /** An update writes its Word file now. */
  updating?: boolean
  /** Why *Corrected file* cannot start now ('' = it can). */
  correctedBlocked?: string
  onToggle: () => void
  onOpen: () => void
  /** Open the document on its Review tab. */
  onReview: () => void
  onCompare: () => void
  /** Download its Word file as it is. */
  onDownload: () => void
  /** *Corrected file*: update it first (the confirm dialog asks), then download. */
  onCorrected?: () => void
  onAssign: () => void
  onClaim: () => void
}) {
  const carried = doc.review.carriedFrom
  const last = doc.review.lastEvent
  const said = last ? describeEvent(last, { nameOf, meId }) : null
  const lastLine = said ? `${said.actor ? `${said.actor} ` : ''}${said.text}` : ''
  const stale = doc.status !== 'approved' ? wordFile : undefined

  // The one review action from the list, per role and state.
  let action: React.ReactNode = null
  if (isAdmin && doc.status === 'submitted') {
    action = <RowButton icon="fact_check" title="Review and approve" onClick={onReview} className="text-secondary" />
  } else if (isAdmin && doc.status !== 'approved') {
    action = (
      <RowButton
        icon="person_add"
        title={doc.reviewer ? `Re-assign (now ${doc.reviewer.name})` : 'Assign a reviewer'}
        onClick={onAssign}
      />
    )
  } else if (isDeveloper && !doc.reviewer && doc.status !== 'approved') {
    action = (
      <RowButton icon="front_hand" title="Claim: become its reviewer" onClick={onClaim} disabled={claimPending} className="text-secondary" />
    )
  } else if (isDeveloper && doc.reviewer?.userId === meId) {
    action = (
      <span title="You review it" className="p-1.5 flex items-center text-[#00a572]">
        <Icon name="how_to_reg" size={15} />
      </span>
    )
  }

  return (
    <tr
      className={cn('border-b border-outline-variant last:border-0 cursor-pointer transition-colors', selected && 'bg-surface-container-low')}
      onClick={onOpen}
    >
      <td className="px-3 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          aria-label={`Select ${doc.name}`}
          checked={selected}
          onChange={onToggle}
          className="accent-secondary w-[15px] h-[15px] cursor-pointer"
        />
      </td>
      <td className="px-3 py-3.5">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-surface-container-low border border-outline-variant flex items-center justify-center flex-shrink-0">
            <Icon name="article" size={15} className="text-on-surface-variant" />
          </div>
          <div className="min-w-0">
            <p className="text-on-surface hover:text-secondary transition-colors font-mono text-body font-medium truncate">{doc.name}</p>
            <Text as="p" variant="caption" className="font-mono mt-0.5 whitespace-nowrap truncate">{doc.subtitle}</Text>
          </div>
        </div>
      </td>
      <td className="px-3 py-3.5"><ProcessBadge process={doc.process} /></td>
      <td className="px-3 py-3.5">
        <div className="flex items-center gap-2 min-w-0">
          <Avatar person={doc.reviewer} size={24} />
          {doc.reviewer ? (
            <span className="text-on-surface truncate font-mono text-caption">{doc.reviewer.name}</span>
          ) : (
            <span className="text-[#b45309] text-caption font-semibold truncate" title="Nobody reviews it yet">Needs a reviewer</span>
          )}
        </div>
      </td>
      <td className="px-3 py-3.5">
        <StatusBadge status={doc.status} />
        {carried && (
          <p className="font-mono text-label text-[#00a572] mt-[3px]" title={`Content unchanged since ${carried.tag}`}>from {carried.tag}</p>
        )}
      </td>
      <td className="px-3 py-3.5 text-caption text-on-surface-variant leading-[1.35]">
        {said ? (
          <>
            <p className="truncate" title={lastLine}>
              {said.actor && <b className="font-semibold">{said.actor} </b>}{said.text}
            </p>
            <p className="font-mono text-label text-outline mt-0.5">{relativeTime(last?.at)}</p>
          </>
        ) : <span className="text-outline">—</span>}
      </td>
      <td className="px-3 py-3.5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-1">
          <RowButton icon="open_in_new" title="View" onClick={onOpen} className="text-secondary" />
          {updating && doc.status !== 'approved' ? (
            <span title="Updating…" role="img" aria-label="Updating…" className="p-1.5 flex items-center text-[#b45309]">
              <Icon name="autorenew" size={15} className="animate-spin" />
            </span>
          ) : stale ? (
            <WordFileMenu
              label="Download"
              trigger={(
                <button
                  type="button"
                  title={`Out of date: ${outOfDateWhy(stale)}`}
                  aria-label={`Download DOCX (out of date: ${outOfDateWhy(stale)})`}
                  className="relative p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant"
                >
                  <Icon name="download" size={15} />
                  <span className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-amber border border-white" aria-hidden />
                </button>
              )}
              items={[
                {
                  icon: 'sync', label: 'Corrected file', sub: correctedBlocked || 'Updated first', disabled: !!correctedBlocked,
                  onSelect: () => onCorrected?.(),
                },
                { icon: 'download', label: 'Current file', sub: cap(outOfDateWhy(stale)), onSelect: onDownload },
              ]}
            />
          ) : (
            <RowButton icon="download" title="Download DOCX" onClick={onDownload} />
          )}
          {carried ? (
            <span title={`Content unchanged since ${carried.tag}: nothing to compare`} className="p-1.5 flex items-center cursor-not-allowed text-outline-variant">
              <Icon name="compare_arrows" size={15} />
            </span>
          ) : (
            <RowButton icon="compare_arrows" title="Compare vs reference" onClick={onCompare} />
          )}
          {action}
        </div>
      </td>
    </tr>
  )
}

function RowButton({ icon, title, onClick, disabled, className }: {
  icon: string; title: string; onClick: () => void; disabled?: boolean; className?: string
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      className={cn('relative p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant disabled:opacity-40', className)}
    >
      <Icon name={icon} size={15} />
    </button>
  )
}
