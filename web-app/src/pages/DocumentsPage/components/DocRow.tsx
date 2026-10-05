import { Avatar, Icon, StatusBadge, Text } from '../../../components/ui'
import { ProcessBadge } from '../../../components/ui/Badge'
import { cn } from '../../../lib/cn'
import { relativeTime } from '../../../lib/format'
import { describeEvent } from '../../../lib/reviewStatus'
import type { Document } from '../../../types'

/** What Download gives while the version's Word files lack corrections (R9 `stale`). */
const PREVIOUS_WORD_FILE = 'Previous Word file — the corrections are not in it yet'

/* One row of the documents list: who reviews it, its state, what happened last, and the one
   review action this role can take from the list (documents.html renderDocList). */
export function DocRow({
  doc, selected, isAdmin, isDeveloper, meId, nameOf, claimPending, wordFileStale = false,
  onToggle, onOpen, onReview, onCompare, onDownload, onAssign, onClaim,
}: {
  doc: Document
  selected: boolean
  isAdmin: boolean
  isDeveloper: boolean
  meId: string
  nameOf: (userId: string) => string | undefined
  claimPending: boolean
  /** Its component's Word files lack corrections (R9 `staleComponents`): Download gives the
   *  previous file. An approved document downloads the file that was approved: never marked. */
  wordFileStale?: boolean
  onToggle: () => void
  onOpen: () => void
  /** Open the document on its Review tab. */
  onReview: () => void
  onCompare: () => void
  onDownload: () => void
  onAssign: () => void
  onClaim: () => void
}) {
  const carried = doc.review.carriedFrom
  const last = doc.review.lastEvent
  const said = last ? describeEvent(last, { nameOf, meId }) : null
  const lastLine = said ? `${said.actor ? `${said.actor} ` : ''}${said.text}` : ''
  const stale = wordFileStale && doc.status !== 'approved'

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
          <RowButton
            icon="download"
            title={stale ? `Download DOCX: ${PREVIOUS_WORD_FILE}` : 'Download DOCX'}
            onClick={onDownload}
            dot={stale}
          />
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

function RowButton({ icon, title, onClick, disabled, className, dot }: {
  icon: string; title: string; onClick: () => void; disabled?: boolean; className?: string
  /** A small amber dot: what it gives is out of date (the title says how). */
  dot?: boolean
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
      {dot && <span className="absolute top-0.5 right-0.5 w-2 h-2 rounded-full bg-amber border border-white" aria-hidden />}
    </button>
  )
}
