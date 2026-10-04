import type { ReactNode } from 'react'
import { useDownloadDoc } from '../../../hooks/useDocumentMutations'
import { Avatar, Icon, StatusBadge, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { relativeTime } from '../../../lib/format'
import { GENERATED_PROCESSES, docxFileName, shownProcesses } from '../../../lib/docTree'
import {
  NEXT_STEP, REVIEW_ORDER, STATUS_META, describeEvent, eventMeta, reviewCounts, shortHash,
} from '../../../lib/reviewStatus'
import type { Document, ReviewEvent, TeamMember, Version } from '../../../types'
import { concernsMe, foldRunEvents, myReviews, reviewQueues } from '../helpers'

/* The Overview's review and approval (project-detail.html): the version's approval by state, the
   admin's queues, a developer's reviews, what can be claimed, and the record of what happened. */

type Nav = (to: string) => void

const PROCESS_LABELS: Record<string, string> = {
  'SWE.3': 'Detailed Design',
  'SWE.4': 'Unit Test Specification',
  'SYS.1': 'Req. Elicitation',
  'SYS.2': 'System Architecture',
  'SWE.1': 'SW Requirements',
  'SWE.2': 'SW Architecture',
}
// SWE.3 and SWE.4 first, as the documents are made; any other process only with a document.
const processRows = (documents: Document[]) =>
  [...GENERATED_PROCESSES, ...shownProcesses(documents).filter((p) => !GENERATED_PROCESSES.includes(p))]
    .map((key) => ({ key, label: PROCESS_LABELS[key] ?? key }))

const pct = (n: number, total: number) => (total ? Math.round((n / total) * 100) : 0)
const KPI_LABEL = 'font-mono text-caption font-medium tracking-[.07em]'
const DOC_TH = 'text-left px-4 py-2.5 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[.07em]'
const docPath = (projectId: string, d: Pick<Document, 'id'>, review = false) =>
  `/projects/${projectId}/documents/${d.id}${review ? '?tab=review' : ''}`

/* A segmented bar: one part per state, approved first. */
function StateBar({ docs, className }: { docs: Document[]; className?: string }) {
  const c = reviewCounts(docs)
  return (
    <div className={cn('rounded-full bg-[#e8eaed] overflow-hidden flex', className)}>
      {REVIEW_ORDER.filter((k) => c[k]).map((k) => (
        <div
          key={k}
          title={`${STATUS_META[k].label}: ${c[k]}`}
          className={cn('h-full', STATUS_META[k].dot)}
          // eslint-disable-next-line no-restricted-syntax -- a state's share of the bar is data-driven
          style={{ width: `${(c[k] / c.total) * 100}%` }}
        />
      ))}
    </div>
  )
}

/* The version's approval as a donut: one arc per state, "N of M approved" inside. */
function Donut({ docs }: { docs: Document[] }) {
  const C = 326.73
  const c = reviewCounts(docs)
  // Each state's arc starts where the ones before it end.
  const lens = REVIEW_ORDER.map((k) => (c.total ? (c[k] / c.total) * C : 0))
  const starts = lens.map((_, i) => lens.slice(0, i).reduce((a, b) => a + b, 0))
  return (
    <svg width="136" height="136" viewBox="0 0 136 136" role="img" aria-label={`${c.approved} of ${c.total} approved`}>
      <g transform="rotate(-90 68 68)">
        <circle cx="68" cy="68" r="52" fill="none" stroke="#e8eaed" strokeWidth="14" />
        {REVIEW_ORDER.map((k, i) => (
          <circle key={k} cx="68" cy="68" r="52" fill="none" stroke={STATUS_META[k].hex} strokeWidth="14"
            strokeDasharray={`${lens[i].toFixed(2)} ${C.toFixed(2)}`} strokeDashoffset={(-starts[i]).toFixed(2)} />
        ))}
      </g>
      <text x="68" y="63" textAnchor="middle" fontSize="30" fontWeight="700" fill="#0b1c30" fontFamily="Inter,sans-serif">{c.approved}</text>
      <text x="68" y="81" textAnchor="middle" fontSize="11" fill="#9aa0a6" fontFamily="Inter,sans-serif">of {c.total} approved</text>
    </svg>
  )
}

export function KpiStrip({ documents, version, versions, team, isAdmin, meId }: {
  documents: Document[]; version?: Version; versions?: Version[]; team?: TeamMember[]; isAdmin: boolean; meId: string
}) {
  const c = reviewCounts(documents)
  const allDone = c.total > 0 && c.approved === c.total
  const withReviewer = documents.filter((d) => !!d.reviewer).length
  const mine = myReviews(documents, meId).docs
  const myCount = reviewCounts(mine)
  const processCount = new Set(documents.map((d) => d.process)).size
  const vTag = version?.tag ?? versions?.[0]?.tag ?? '—'

  const statusRow = (k: (typeof REVIEW_ORDER)[number]) => (
    <div key={k} className="flex items-center justify-between">
      <div className="flex items-center gap-[9px]">
        <span className={cn('w-2.5 h-2.5 rounded-full flex-shrink-0', STATUS_META[k].dot)} />
        <span className="text-body text-on-surface-variant">{STATUS_META[k].label}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-title font-bold text-on-surface">{c[k]}</span>
        <span className="text-caption text-[#9aa0a6] min-w-9 text-right">{pct(c[k], c.total)}%</span>
      </div>
    </div>
  )
  const infoRow = (label: string, value: ReactNode, pill?: boolean) => (
    <div className="flex items-center justify-between">
      <span className="text-xs text-outline">{label}</span>
      {pill
        ? <span className="font-mono text-caption font-bold text-secondary bg-surface-container px-[9px] py-0.5 rounded-[5px]">{value}</span>
        : <span className="font-mono text-body font-bold text-on-surface">{value}</span>}
    </div>
  )

  return (
    <div className="mb-6 grid grid-cols-[2fr_1fr_1fr] gap-4 items-stretch">
      <div className="bg-white border border-outline-variant rounded-xl p-6 flex items-center gap-8">
        <div className="flex-shrink-0"><Donut docs={documents} /></div>
        <div className="flex-1">
          <div className="flex items-center justify-between gap-2 mb-4">
            <p className={cn('text-on-surface-variant uppercase', KPI_LABEL)}>Approval · {vTag}</p>
            <span title="A version is Approved when every one of its documents is">
              <StatusBadge status={allDone ? 'approved' : 'in_review'} />
            </span>
          </div>
          <div className="flex flex-col gap-[11px]">{REVIEW_ORDER.map(statusRow)}</div>
        </div>
      </div>

      {isAdmin ? (
        <div className="bg-white border border-outline-variant rounded-xl p-5">
          <p className={cn('text-on-surface-variant uppercase mb-3', KPI_LABEL)}>Reviewers</p>
          <div className="flex items-baseline gap-1 mb-2.5">
            <span className="font-mono text-[32px] font-bold text-on-surface leading-none">{withReviewer}</span>
            <span className="text-body text-[#9aa0a6] leading-none">/ {c.total} have a reviewer</span>
          </div>
          <div className="h-1.5 rounded-full bg-[#e8eaed] overflow-hidden mb-2.5">
            {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
            <div className={cn('h-full rounded-full', c.needsReviewer === 0 ? 'bg-[#00a572]' : 'bg-secondary')} style={{ width: `${pct(withReviewer, c.total)}%` }} />
          </div>
          {c.needsReviewer > 0
            ? <p className="text-xs text-[#b45309]"><span className="font-semibold">{c.needsReviewer} {c.needsReviewer === 1 ? 'needs' : 'need'} a reviewer</span> · see the review queue</p>
            : <p className="text-xs text-[#00a572] font-medium">Every open document has a reviewer</p>}
        </div>
      ) : (
        <div className="bg-white border border-outline-variant rounded-xl p-5">
          <p className={cn('text-on-surface-variant uppercase mb-3', KPI_LABEL)}>My reviews</p>
          <div className="flex items-baseline gap-1 mb-2.5">
            <span className="font-mono text-[32px] font-bold text-on-surface leading-none">{mine.length}</span>
            <span className="text-body text-[#9aa0a6] leading-none">/ {c.total} documents</span>
          </div>
          <StateBar docs={mine} className="h-1.5 mb-2.5" />
          <div className="flex gap-x-3 gap-y-1 flex-wrap">
            {(['changes_requested', 'in_review', 'submitted', 'approved'] as const).filter((k) => myCount[k]).map((k) => (
              k === 'changes_requested' ? (
                <span key={k} className="flex items-center gap-1 text-caption text-error font-semibold">
                  <Icon name="undo" size={13} />{myCount[k]} changes requested
                </span>
              ) : (
                <span key={k} className="flex items-center gap-[5px] text-caption text-outline">
                  <span className={cn('w-[7px] h-[7px] rounded-full', STATUS_META[k].dot)} />{myCount[k]} {STATUS_META[k].label.toLowerCase()}
                </span>
              )
            ))}
            {mine.length === 0 && <span className="text-caption text-outline">None yet — claim one below</span>}
          </div>
        </div>
      )}

      <div className="bg-white border border-outline-variant rounded-xl p-5">
        <p className={cn('text-on-surface-variant uppercase mb-3', KPI_LABEL)}>Project Info</p>
        <div className="flex flex-col gap-2.5">
          {infoRow('Latest version', versions?.[0]?.tag ?? '—', true)}
          {infoRow('Team members', team?.length ?? 0)}
          {infoRow('Processes', processCount)}
          {infoRow('Versions', versions?.length ?? 0)}
        </div>
      </div>
    </div>
  )
}

/* Admin: per process, the approval of its documents and who reviews them. */
export function AdminDocsCard({ documents, go, projectId }: { documents: Document[]; go: Nav; projectId: string }) {
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <Text as="h2" variant="heading" className="text-on-surface">Documents</Text>
        <a onClick={(e) => { e.preventDefault(); go(`/projects/${projectId}/documents`) }} href="#" className="hover:underline inline-flex items-center gap-1 text-xs text-secondary font-medium">
          View all<Icon name="arrow_forward" size={14} />
        </a>
      </div>
      <table className="w-full">
        <thead>
          <tr className="bg-surface-container-low border-b border-outline-variant">
            <th className="text-left px-5 py-2.5 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[.07em]">Process</th>
            <th className={cn(DOC_TH, 'w-[250px]')}>Approval</th>
            <th className={cn(DOC_TH, 'w-40')}>Reviewers</th>
            <th className="w-11" />
          </tr>
        </thead>
        <tbody>
          {/* A row per process the app makes (one with no document of this version is muted), and
              any other with a document: never a placeholder row for a process nothing makes. */}
          {processRows(documents).map((p) => {
            const docs = documents.filter((d) => d.process === p.key)
            const total = docs.length
            if (total === 0) {
              return (
                <tr key={p.key} className="border-b border-outline-variant last:border-0">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2.5 opacity-60">
                      <span className="font-mono text-caption font-bold text-on-surface-variant bg-surface-container px-2 py-0.5 rounded-[5px] flex-shrink-0">{p.key}</span>
                      <div>
                        <div className="text-body font-medium text-on-surface-variant leading-[1.3]">{p.label}</div>
                        <div className="text-caption text-outline">0 docs</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3" colSpan={2}>
                    <span className="text-caption text-outline-variant italic">Not generated yet</span>
                  </td>
                  <td className="px-3 py-2" />
                </tr>
              )
            }
            const c = reviewCounts(docs)
            const reviewers = [...new Map(docs.filter((d) => d.reviewer).map((d) => [d.reviewer!.userId, d.reviewer!])).values()]
            const shown = reviewers.slice(0, 4)
            const extra = reviewers.length - shown.length
            return (
              <tr key={p.key} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors cursor-pointer" onClick={() => go(`/projects/${projectId}/documents`)}>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2.5">
                    <span className="font-mono text-caption font-bold text-secondary bg-surface-container px-2 py-0.5 rounded-[5px] flex-shrink-0">{p.key}</span>
                    <div>
                      <div className="text-body font-medium text-on-surface leading-[1.3]">{p.label}</div>
                      <div className="text-caption text-outline">{total} doc{total !== 1 ? 's' : ''}</div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <StateBar docs={docs} className="flex-1 h-[5px] min-w-[72px]" />
                    <span className={cn('text-caption font-semibold whitespace-nowrap', c.approved === total ? 'text-[#00a572]' : 'text-on-surface-variant')}>{c.approved} / {total} approved</span>
                  </div>
                  {(c.submitted > 0 || c.needsReviewer > 0) && (
                    <div className="flex gap-1 flex-wrap mt-1.5">
                      {c.submitted > 0 && <Chip status="submitted" text={`${c.submitted} ready for approval`} />}
                      {c.needsReviewer > 0 && <Chip status="in_review" text={`${c.needsReviewer} ${c.needsReviewer === 1 ? 'needs' : 'need'} a reviewer`} />}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3">
                  {shown.length === 0
                    ? (c.needsReviewer ? <span className="text-caption text-[#b45309] italic">Needs a reviewer</span> : <span className="text-caption text-outline-variant">—</span>)
                    : (
                      <div className="flex items-center">
                        {shown.map((r, i) => <Avatar key={r.userId} person={r} size={24} className={cn('border-2 border-white', i > 0 && '-ml-1.5')} />)}
                        {extra > 0 && <div className="-ml-1.5 w-6 h-6 rounded-full bg-[#f3f4f6] border-2 border-white flex items-center justify-center text-micro font-bold text-on-surface-variant">+{extra}</div>}
                      </div>
                    )}
                </td>
                <td className="px-3 py-2 text-right"><Icon name="arrow_forward" size={14} className="text-on-surface-variant" /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Chip({ status, text }: { status: 'submitted' | 'in_review'; text: string }) {
  return <span className={cn('text-label font-semibold px-1.5 rounded-full border whitespace-nowrap', STATUS_META[status].badge)}>{text}</span>
}

/* Developer: every document I review, its state, and what it needs next — what needs me first. */
export function MyReviewsCard({ documents, meId, go, projectId }: { documents: Document[]; meId: string; go: Nav; projectId: string }) {
  const { docs, toDo } = myReviews(documents, meId)
  const downloadDoc = useDownloadDoc(projectId)
  const open = (doc: Document) => go(docPath(projectId, doc, doc.status !== 'approved'))
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <div>
          <Text as="h2" variant="heading" className="text-on-surface">My reviews</Text>
          <Text as="p" variant="caption" className="font-mono mt-0.5">
            {docs.length} document{docs.length !== 1 ? 's' : ''} you review{toDo ? ` · ${toDo} need${toDo === 1 ? 's' : ''} you now` : ''}
          </Text>
        </div>
        <a onClick={(e) => { e.preventDefault(); go(`/projects/${projectId}/documents`) }} href="#" className="hover:underline inline-flex items-center gap-1 text-xs text-secondary font-medium">
          All Documents<Icon name="arrow_forward" size={14} />
        </a>
      </div>
      {docs.length === 0 ? (
        <p className="px-5 py-6 text-on-surface-variant text-xs">No documents to review yet — claim one below.</p>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="bg-surface-container-low border-b border-outline-variant">
              <th className="text-left px-5 py-2.5 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[.07em]">Document</th>
              <th className={cn(DOC_TH, 'w-[90px]')}>Process</th>
              <th className={cn(DOC_TH, 'w-[165px]')}>Status</th>
              <th className={cn(DOC_TH, 'w-[230px]')}>Next step</th>
              <th className="w-[72px]" />
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => {
              const needsMe = doc.status === 'in_review' || doc.status === 'changes_requested'
              return (
                <tr key={doc.id} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors cursor-pointer" onClick={() => open(doc)}>
                  <td className="px-5 py-[13px]">
                    <div className="text-body font-medium text-on-surface leading-[1.3]">{doc.name}</div>
                    <div className="text-caption text-outline mt-0.5">{doc.subtitle ?? doc.process}</div>
                  </td>
                  <td className="px-4 py-[13px]"><span className="font-mono text-caption font-bold text-secondary bg-surface-container px-2 py-0.5 rounded-[5px]">{doc.process}</span></td>
                  <td className="px-4 py-[13px]"><StatusBadge status={doc.status} /></td>
                  <td className="px-4 py-[11px]">
                    {doc.status === 'approved' ? (
                      <div className="flex items-center gap-1 text-xs text-outline">
                        <Icon name="lock" size={13} />{NEXT_STEP.approved}{doc.review.carriedFrom ? ` · carried from ${doc.review.carriedFrom.tag}` : ''}
                      </div>
                    ) : (
                      <>
                        <div className={cn('text-xs leading-[1.35]', needsMe ? 'text-on-surface font-semibold' : 'text-outline')}>{NEXT_STEP[doc.status]}</div>
                        {doc.status === 'changes_requested' && doc.review.changesComment && (
                          <div className="text-caption leading-[1.35] text-error mt-[3px] line-clamp-2">“{doc.review.changesComment}”</div>
                        )}
                      </>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1">
                      <button onClick={(e) => { e.stopPropagation(); open(doc) }} title="Open" className="flex items-center justify-center w-7 h-7 border border-[#e2e3e8] rounded-md bg-white text-outline hover:border-secondary hover:text-secondary"><Icon name="open_in_new" size={14} /></button>
                      <button onClick={(e) => { e.stopPropagation(); void downloadDoc(doc.id, docxFileName(doc)) }} title="Download" className="flex items-center justify-center w-7 h-7 border border-[#e2e3e8] rounded-md bg-white text-outline hover:border-secondary hover:text-secondary"><Icon name="download" size={14} /></button>
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* Developer: a document with no reviewer that is not approved; claiming it makes you its reviewer. */
export function ClaimPoolCard({ documents, onClaim, claiming }: { documents: Document[]; onClaim: (id: string) => void; claiming: boolean }) {
  const pool = documents.filter((d) => !d.reviewer && d.status !== 'approved')
  if (!pool.length) return null
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-5 py-3.5 border-b border-outline-variant">
        <Text as="h2" variant="heading" className="text-on-surface">Available to claim</Text>
        <Text as="p" variant="caption" className="font-mono mt-0.5">
          {pool.length} document{pool.length !== 1 ? 's' : ''} without a reviewer · claim one to review it
        </Text>
      </div>
      <div>
        {pool.map((doc) => (
          <div key={doc.id} className="flex items-center gap-3 px-5 py-3 border-b border-[#e2e3e8] last:border-0">
            <Icon name="description" size={18} className="text-outline-variant flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-body font-medium text-on-surface truncate">{doc.name}</div>
              <div className="flex items-center gap-1.5 mt-[3px]">
                <span className="font-mono text-label font-bold text-secondary bg-surface-container px-[7px] py-px rounded-lg">{doc.process}</span>
                <span className="text-caption text-outline">{doc.subtitle ?? ''}</span>
              </div>
            </div>
            <button onClick={() => onClaim(doc.id)} disabled={claiming} className="inline-flex items-center gap-[5px] px-3 py-[5px] rounded-lg border border-secondary bg-white text-secondary text-xs font-semibold whitespace-nowrap flex-shrink-0 hover:bg-surface-container-low disabled:opacity-50">
              <Icon name="front_hand" size={14} />Claim
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

/* Admin: three queues — Ready for approval (the reviewer's comment, Review), Needs a reviewer
   (Assign), Changes requested (with whom, and why). */
export function ReviewQueueCard({ documents, go, projectId, onAssign }: {
  documents: Document[]; go: Nav; projectId: string; onAssign: (doc: Document) => void
}) {
  const q = reviewQueues(documents)
  const open = q.ready.length + q.needsReviewer.length + q.changes.length
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <Text as="h2" variant="heading" className="text-on-surface">Review Queue</Text>
        <span className="font-mono text-label font-bold bg-surface-container text-secondary px-2.5 py-0.5 rounded-full">{open ? `${open} to act on` : 'All clear'}</span>
      </div>
      <QueueSection first title="Ready for approval" status="submitted" icon="pending_actions" docs={q.ready}
        row={(d) => (
          <QueueRow key={d.id} doc={d} onOpen={() => go(docPath(projectId, d, true))}
            sub={<><span className="text-on-surface-variant font-medium">{d.reviewer?.name ?? 'Its reviewer'}:</span> “{d.review.comment || 'Submitted for approval'}”</>}
            action={<button onClick={(e) => { e.stopPropagation(); go(docPath(projectId, d, true)) }} className="flex-shrink-0 px-[11px] py-1 rounded-md border border-secondary bg-secondary text-white text-caption font-semibold hover:bg-secondary-container">Review</button>} />
        )} />
      <QueueSection title="Needs a reviewer" status="in_review" icon="person_add" docs={q.needsReviewer}
        row={(d) => (
          <QueueRow key={d.id} doc={d} onOpen={() => go(docPath(projectId, d))}
            sub="In review · no reviewer yet"
            action={(
              <button onClick={(e) => { e.stopPropagation(); onAssign(d) }} className="flex-shrink-0 inline-flex items-center gap-[5px] px-2.5 py-[3px] border-[1.5px] border-dashed border-outline-variant rounded-full text-caption text-outline hover:border-secondary hover:text-secondary whitespace-nowrap">
                <Icon name="person_add" size={13} />Assign
              </button>
            )} />
        )} />
      <QueueSection title="Changes requested" status="changes_requested" icon="undo" docs={q.changes}
        row={(d) => (
          <QueueRow key={d.id} doc={d} onOpen={() => go(docPath(projectId, d, true))}
            sub={<>Back with <span className="text-on-surface-variant font-medium">{d.reviewer?.name ?? 'its reviewer'}</span>{d.review.changesComment ? <>: “{d.review.changesComment}”</> : ''}</>}
            action={<button onClick={(e) => { e.stopPropagation(); go(docPath(projectId, d, true)) }} className="flex-shrink-0 px-[11px] py-1 rounded-md border border-outline-variant bg-white text-on-surface-variant text-caption font-semibold hover:border-secondary hover:text-secondary">Open</button>} />
        )} />
    </div>
  )
}

function QueueSection({ first, title, status, icon, docs, row }: {
  first?: boolean; title: string; status: 'submitted' | 'in_review' | 'changes_requested'; icon: string
  docs: Document[]; row: (d: Document) => ReactNode
}) {
  const m = STATUS_META[status]
  return (
    <>
      <div className={cn('flex items-center gap-[7px] px-4 py-[9px] bg-surface border-b border-[#e2e3e8]', !first && 'border-t')}>
        <Icon name={icon} size={15} className={m.text} />
        <span className="text-xs font-semibold text-on-surface">{title}</span>
        <span className={cn('ml-auto font-mono text-label font-bold px-2 rounded-full border', m.badge)}>{docs.length}</span>
      </div>
      {docs.length
        ? <div className="divide-y divide-outline-variant">{docs.map(row)}</div>
        : <p className="px-4 py-2.5 text-caption text-[#9aa0a6]">Nothing here.</p>}
    </>
  )
}

function QueueRow({ doc, sub, action, onOpen }: { doc: Document; sub: ReactNode; action: ReactNode; onOpen: () => void }) {
  return (
    <div className="px-4 py-2.5 flex items-center gap-3 hover:bg-surface-container-low transition-colors cursor-pointer" onClick={onOpen}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-mono text-micro font-bold text-secondary bg-surface-container px-[5px] py-px rounded flex-shrink-0">{doc.process}</span>
          <p className="text-xs text-on-surface font-medium truncate">{doc.name}</p>
        </div>
        <p className="text-caption text-outline leading-[1.35] mt-[3px] line-clamp-2">{sub}</p>
      </div>
      {action}
    </div>
  )
}

/* What happened: the review record of the version on screen (A11), newest first. A developer
   sees what concerns them; a run's per-document events read as one line. */
export function LastActionsCard({ events, documents, versions, isAdmin, meId, nameOf, isLoading }: {
  events?: ReviewEvent[]; documents: Document[]; versions?: Version[]; isAdmin: boolean; meId: string
  nameOf: (userId: string) => string | undefined; isLoading: boolean
}) {
  const myDocIds = new Set(documents.filter((d) => d.reviewer?.userId === meId).map((d) => d.id))
  const shown = (events ?? []).filter((e) => isAdmin || concernsMe(e, myDocIds, meId))
  const lines = foldRunEvents(shown).slice(0, 6)
  const tagOf = (vid: string) => versions?.find((v) => v.id === vid)?.tag ?? 'the version'
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden flex-1 flex flex-col">
      <div className="px-4 py-3.5 border-b border-outline-variant">
        <Text as="h2" variant="heading" className="text-on-surface">Last Actions</Text>
      </div>
      <div className="flex-1 overflow-y-auto">
        {isLoading && <p className="px-4 py-3 text-xs text-on-surface-variant">Loading…</p>}
        {!isLoading && lines.length === 0 && <p className="px-4 py-3 text-xs text-on-surface-variant">Nothing yet.</p>}
        {lines.map(({ event: e, count }) => {
          const k = eventMeta(e.kind)
          const doc = e.document ? `${e.document.name} (${e.document.process})` : 'a document'
          let actor: string | null
          let text: string
          if (e.kind === 'generated' && count > 1) {
            actor = null
            text = `The run generated ${count} documents of ${tagOf(e.versionId)}, every one in review`
          } else if (e.kind === 'carried' && count > 1) {
            const from = typeof e.payload.from_tag === 'string' ? e.payload.from_tag : 'an earlier version'
            actor = null
            text = `${count} approvals carried from ${from}: their content is unchanged`
          } else {
            ({ actor, text } = describeEvent(e, { doc, nameOf, meId }))
          }
          const sha = e.kind === 'approved' && typeof e.payload.docx_sha256 === 'string' ? e.payload.docx_sha256 : null
          return (
            <div key={e.id} className="flex items-start gap-2.5 px-4 py-3 border-b border-[#f0f1f3]">
              <Icon name={k.icon} size={15} fill className={cn('flex-shrink-0 mt-px', k.text)} />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-on-surface leading-[1.4]">{actor && <b className="font-semibold">{actor} </b>}{text}</p>
                {e.comment && <p title={e.comment} className="text-caption text-on-surface-variant leading-[1.35] mt-[3px] truncate">“{e.comment}”</p>}
                {sha && <p className="text-label text-outline mt-0.5 font-mono">Word file sha256 {shortHash(sha)}</p>}
                <p className="text-label text-[#9aa0a6] mt-0.5 font-mono">{relativeTime(e.at)}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
